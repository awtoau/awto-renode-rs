using System.Security.Cryptography;
using System.Text;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Operations;

namespace RenodeIngest;

/// <summary>
/// Walks one file's declarations and IOperation trees into a <see cref="FileResult"/>.
///
/// Runs on a worker thread. SemanticModel reads are thread-safe once the
/// compilation exists, so files walk in parallel; nothing here mutates shared
/// state, and every list is ordered by the deterministic syntax walk rather than
/// by completion.
/// </summary>
public static class Walker
{
    /// <summary>
    /// Symbol display format used as the cross-file join key. Fully qualified
    /// and including parameter types, so overloads stay distinct -- Renode's
    /// register DSL has 20 combinators with heavy overloading, and collapsing
    /// those would merge patterns that must stay separate.
    /// </summary>
    private static readonly SymbolDisplayFormat KeyFormat = new(
        globalNamespaceStyle: SymbolDisplayGlobalNamespaceStyle.Omitted,
        typeQualificationStyle: SymbolDisplayTypeQualificationStyle.NameAndContainingTypesAndNamespaces,
        genericsOptions: SymbolDisplayGenericsOptions.IncludeTypeParameters,
        memberOptions: SymbolDisplayMemberOptions.IncludeParameters
                     | SymbolDisplayMemberOptions.IncludeContainingType,
        parameterOptions: SymbolDisplayParameterOptions.IncludeType
                        | SymbolDisplayParameterOptions.IncludeParamsRefOut,
        miscellaneousOptions: SymbolDisplayMiscellaneousOptions.UseSpecialTypes);

    public static string Key(ISymbol s) => s.ToDisplayString(KeyFormat);

    /// <summary>
    /// Key for a call/reference TARGET, normalised to the generic definition.
    ///
    /// A call to `WithFlag&lt;DoubleWordRegister&gt;` constructs the generic, and the
    /// constructed symbol's display string does not match the declaration's
    /// (`WithFlag&lt;T&gt;`). Keying on the constructed form made 1,109 register-DSL
    /// calls resolve as external despite the DSL being in corpus, which would
    /// have made is_leaf and the whole topological work queue wrong.
    ///
    /// OriginalDefinition maps a constructed generic -- method or containing
    /// type -- back to the declaration the corpus actually holds.
    /// </summary>
    public static string TargetKey(ISymbol s) => Key(s.OriginalDefinition);

    public static FileResult Walk(Compilation compilation, SyntaxTree tree, string treeRoot)
    {
        var model = compilation.GetSemanticModel(tree);
        var text = tree.GetText();
        var relative = Relative(tree.FilePath, treeRoot);

        var result = new FileResult
        {
            Path = relative,
            Sha256 = Sha256Of(text.ToString()),
            Loc = text.Lines.Count,
        };

        var nextOpId = 0;

        foreach (var typeDecl in tree.GetRoot().DescendantNodes().OfType<BaseTypeDeclarationSyntax>())
        {
            if (model.GetDeclaredSymbol(typeDecl) is not INamedTypeSymbol type) continue;

            var typeRec = new TypeRec
            {
                Key = Key(type),
                Namespace = type.ContainingNamespace?.ToDisplayString() ?? "",
                Name = type.Name,
                Kind = type.TypeKind.ToString().ToLowerInvariant(),
                // object is every class's base and carries no information.
                BaseKey = type.BaseType is { SpecialType: not SpecialType.System_Object } b
                          ? Key(b) : null,
                IsAbstract = type.IsAbstract,
                IsStatic = type.IsStatic,
                IsGeneric = type.IsGenericType,
                Accessibility = type.DeclaredAccessibility.ToString().ToLowerInvariant(),
            };
            foreach (var i in type.Interfaces) typeRec.Interfaces.Add(Key(i));
            result.Types.Add(typeRec);

            foreach (var member in type.GetMembers())
            {
                // Compiler-generated accessors and backing fields are not source
                // constructs; translating them would duplicate the property.
                if (member.IsImplicitlyDeclared) continue;
                if (member is IMethodSymbol { MethodKind: MethodKind.PropertyGet
                                                       or MethodKind.PropertySet
                                                       or MethodKind.EventAdd
                                                       or MethodKind.EventRemove }) continue;

                var rec = BuildMember(member, typeRec.Key);
                if (rec is null) continue;
                result.Members.Add(rec);

                if (rec.Method is null) continue;
                // Partial methods keep their body on the implementation part.
                var bodyOwner = member is IMethodSymbol pm && pm.PartialImplementationPart is { } impl
                                ? impl : member;
                foreach (var reference in bodyOwner.DeclaringSyntaxReferences)
                {
                    if (reference.SyntaxTree != tree) continue;
                    var node = reference.GetSyntax();
                    var body = model.GetOperation(node);
                    if (body is null) continue;
                    WalkOperations(body, rec.Key, result, ref nextOpId, model);
                }
            }
        }

        return result;
    }

    /// Does this property or event have a compiler-generated backing field?
    ///
    /// This is the auto-implemented test, and Roslyn already answers it: the
    /// backing field's AssociatedSymbol points back at the property. Asking the
    /// symbol table beats inspecting accessor syntax, which gets expression-bodied
    /// and partial declarations wrong.
    ///
    /// It matters because a COMPUTED property stores nothing. `STM32_UART.BaudRate`
    /// derives from two register fields; emitting it as state would invent storage
    /// the C# does not have.
    /// Does this event store a delegate?
    ///
    /// The backing-field test does NOT work here: for a field-like event the
    /// backing field is synthesized during emit and is absent from the source
    /// symbol's GetMembers(), so every one of the corpus's 9 events reported
    /// no storage. The signal Roslyn does give is the accessors -- a field-like
    /// event has implicitly-declared add/remove, a custom one declares them.
    private static bool IsFieldLikeEvent(IEventSymbol e) =>
        e.AddMethod is null || e.AddMethod.IsImplicitlyDeclared;

    private static bool HasBackingField(ISymbol member) =>
        member.ContainingType is { } ct
        && ct.GetMembers().OfType<IFieldSymbol>().Any(
            f => SymbolEqualityComparer.Default.Equals(f.AssociatedSymbol, member));

    private static MemberRec? BuildMember(ISymbol member, string typeKey)
    {
        switch (member)
        {
            case IFieldSymbol f:
                return new MemberRec
                {
                    Key = Key(f), TypeKey = typeKey, Kind = "field", Name = f.Name,
                    DeclaredType = f.Type.ToDisplayString(),
                    Accessibility = f.DeclaredAccessibility.ToString().ToLowerInvariant(),
                    IsStatic = f.IsStatic, IsReadOnly = f.IsReadOnly,
                };
            case IPropertySymbol p:
                return new MemberRec
                {
                    Key = Key(p), TypeKey = typeKey, Kind = "property", Name = p.Name,
                    DeclaredType = p.Type.ToDisplayString(),
                    Accessibility = p.DeclaredAccessibility.ToString().ToLowerInvariant(),
                    IsStatic = p.IsStatic, IsReadOnly = p.IsReadOnly,
                    HasStorage = HasBackingField(p),
                };
            case IEventSymbol e:
                return new MemberRec
                {
                    Key = Key(e), TypeKey = typeKey, Kind = "event", Name = e.Name,
                    DeclaredType = e.Type.ToDisplayString(),
                    Accessibility = e.DeclaredAccessibility.ToString().ToLowerInvariant(),
                    IsStatic = e.IsStatic, IsReadOnly = false,
                    HasStorage = IsFieldLikeEvent(e),
                };
            case IMethodSymbol m:
            {
                var method = new MethodRec
                {
                    Signature = m.ToDisplayString(),
                    ReturnType = m.ReturnType.ToDisplayString(),
                    IsVirtual = m.IsVirtual,
                    IsAbstract = m.IsAbstract,
                    IsOverride = m.IsOverride,
                    IsExtension = m.IsExtensionMethod,
                    HasBody = HasRealBody(m),
                };
                foreach (var p in m.Parameters)
                {
                    method.Parameters.Add(new ParamRec(
                        p.Ordinal, p.Name, p.Type.ToDisplayString(),
                        p.RefKind == RefKind.Out, p.RefKind == RefKind.Ref,
                        p.IsParams, p.HasExplicitDefaultValue));
                }
                return new MemberRec
                {
                    Key = Key(m), TypeKey = typeKey,
                    Kind = m.MethodKind == MethodKind.Constructor ? "ctor" : "method",
                    Name = m.Name, DeclaredType = m.ReturnType.ToDisplayString(),
                    Accessibility = m.DeclaredAccessibility.ToString().ToLowerInvariant(),
                    IsStatic = m.IsStatic, IsReadOnly = false,
                    Method = method,
                };
            }
            default:
                return null;
        }
    }

    /// <summary>
    /// Depth-first over the IOperation tree, recording one row per node plus the
    /// call and field-access edges. Iterative rather than recursive: some
    /// generated register-definition chains nest deeply enough to matter.
    /// </summary>
    private static void WalkOperations(IOperation root, string methodKey, FileResult result,
                                       ref int nextId, SemanticModel model)
    {
        var stack = new Stack<(IOperation Op, int? Parent, int Ordinal, int Depth)>();
        stack.Push((root, null, 0, 0));

        while (stack.Count > 0)
        {
            var (op, parent, ordinal, depth) = stack.Pop();
            var id = nextId++;

            ISymbol? symbol = op switch
            {
                // An argument's BOUND PARAMETER. C# named arguments may appear
                // out of positional order -- `Define(this, name: "USART_DR")`
                // skips resetValue -- so binding by position silently reads the
                // wrong value. Roslyn already resolved this; record it.
                IArgumentOperation arg => arg.Parameter,
                IInvocationOperation inv => inv.TargetMethod,
                IObjectCreationOperation oc => oc.Constructor,
                IFieldReferenceOperation fr => fr.Field,
                IPropertyReferenceOperation pr => pr.Property,
                IMethodReferenceOperation mr => mr.Method,
                ILocalReferenceOperation lr => lr.Local,
                IParameterReferenceOperation pr2 => pr2.Parameter,
                IEventReferenceOperation er => er.Event,
                _ => null,
            };

            // Per-kind detail, chosen from what `--audit` reports each kind
            // exposes rather than from what happened to be needed. Emitted as
            // JSON so adding a fact does not need a schema change.
            var detail = new List<string>();
            void Add(string k, object? v)
            {
                if (v is null) return;
                var s = v is bool b ? (b ? "true" : "false") : $"\"{v}\"";
                detail.Add($"\"{k}\":{s}");
            }
            switch (op)
            {
                case IBinaryOperation b2:
                    // IsChecked drives whether arithmetic must emit wrapping_*.
                    Add("checked", b2.IsChecked);
                    Add("lifted", b2.IsLifted);
                    break;
                case IConversionOperation cv2:
                    Add("implicit", cv2.Conversion.IsImplicit);
                    Add("numeric", cv2.Conversion.IsNumeric);
                    Add("checked", cv2.IsChecked);
                    break;
                case IInvocationOperation inv2:
                    // The CALL SITE's virtualness, which differs from the
                    // target method's own IsVirtual.
                    Add("virtual", inv2.IsVirtual);
                    break;
                case IVariableDeclaratorOperation vd:
                    Add("local", vd.Symbol.Name);
                    Add("type", vd.Symbol.Type.ToDisplayString());
                    break;
                case ILocalFunctionOperation lf:
                    Add("fn", lf.Symbol.Name);
                    break;
                case IAnonymousFunctionOperation af:
                    Add("lambda", af.Symbol.ToDisplayString());
                    // The lambda's OWN parameter names. Without them a callback
                    // body referencing `(idx, val) =>` cannot be emitted: the
                    // signature's names are the DSL's, not the source's.
                    // Roslyn had these all along on af.Symbol.Parameters.
                    Add("params", string.Join(" ", af.Symbol.Parameters.Select(pp => pp.Name)));
                    Add("returns", af.Symbol.ReturnType.ToDisplayString());
                    break;
                case IInstanceReferenceOperation ir:
                    Add("refkind", ir.ReferenceKind.ToString());
                    break;
                case ISimpleAssignmentOperation sa:
                    Add("ref", sa.IsRef);
                    break;
            }

            // Operator kind for expressions where `Kind` alone is ambiguous.
            // A `Binary` node says nothing about whether it is `&&`, `+` or
            // `==`, and no expression emitter can work without that. Stored in
            // `symbol`, which is otherwise unused for these kinds.
            string? opKind = op switch
            {
                IBinaryOperation b => b.OperatorKind.ToString(),
                IUnaryOperation u => u.OperatorKind.ToString(),
                ICompoundAssignmentOperation c => c.OperatorKind.ToString(),
                IIncrementOrDecrementOperation i => i.IsPostfix ? "Postfix" : "Prefix",
                IConversionOperation cv => cv.Conversion.IsImplicit ? "Implicit" : "Explicit",
                _ => null,
            };

            result.Operations.Add(new OperationRec
            {
                LocalId = id,
                ParentLocalId = parent,
                MethodKey = methodKey,
                Ordinal = ordinal,
                Depth = depth,
                Kind = op.Kind.ToString(),
                Type = op.Type?.ToDisplayString(),
                Symbol = symbol is not null ? TargetKey(symbol) : opKind,
                ConstValue = op.ConstantValue.HasValue
                             ? op.ConstantValue.Value?.ToString() ?? "null" : null,
                Detail = detail.Count > 0 ? "{" + string.Join(",", detail) + "}" : null,
                SpanStart = op.Syntax.Span.Start,
                SpanLen = op.Syntax.Span.Length,
            });

            switch (op)
            {
                case IInvocationOperation inv:
                    result.Calls.Add(new CallSiteRec(
                        methodKey, TargetKey(inv.TargetMethod), null, id,
                        inv.TargetMethod.IsVirtual || inv.TargetMethod.IsAbstract));
                    break;
                case IObjectCreationOperation { Constructor: not null } oc:
                    result.Calls.Add(new CallSiteRec(methodKey, TargetKey(oc.Constructor),
                                                     null, id, false));
                    break;
                case IFieldReferenceOperation fr:
                    result.FieldAccesses.Add(new FieldAccessRec(
                        methodKey, TargetKey(fr.Field), id, IsWriteTarget(fr)));
                    break;
            }

            // Push in reverse so children pop in source order, which keeps the
            // emitted ordering identical between runs and thread counts.
            var children = op.ChildOperations.ToList();
            for (var i = children.Count - 1; i >= 0; i--)
                stack.Push((children[i], id, i, depth + 1));
        }
    }

    /// <summary>
    /// Whether the method actually has a body, determined from syntax.
    ///
    /// `!IsAbstract &amp;&amp; !IsExtern` is NOT sufficient and gets this wrong at scale:
    /// a `partial void Foo();` declaration with no implementation is neither
    /// abstract nor extern yet has no body. Renode has 5,188 partial method
    /// declarations, mostly in generated peripherals, so the naive test
    /// mis-reported 24.7% of all body-bearing methods -- silently, because
    /// nothing throws. Found by the breadth ingest; invisible in the 36-file cut.
    /// </summary>
    private static bool HasRealBody(IMethodSymbol m)
    {
        // For a partial method the body lives on the implementation part, whose
        // syntax the definition symbol does not reference.
        var target = m.PartialImplementationPart ?? m;
        foreach (var reference in target.DeclaringSyntaxReferences)
        {
            switch (reference.GetSyntax())
            {
                case BaseMethodDeclarationSyntax b
                    when b.Body is not null || b.ExpressionBody is not null:
                case AccessorDeclarationSyntax a
                    when a.Body is not null || a.ExpressionBody is not null:
                case ArrowExpressionClauseSyntax:
                case LocalFunctionStatementSyntax l
                    when l.Body is not null || l.ExpressionBody is not null:
                    return true;
            }
        }
        return false;
    }

    /// <summary>True when this reference is the target of an assignment.</summary>
    private static bool IsWriteTarget(IOperation op) =>
        op.Parent switch
        {
            IAssignmentOperation a => ReferenceEquals(a.Target, op),
            IIncrementOrDecrementOperation i => ReferenceEquals(i.Target, op),
            _ => false,
        };

    private static string Relative(string path, string root)
    {
        var norm = path.Replace('\\', '/');
        var r = root.Replace('\\', '/').TrimEnd('/') + "/";
        return norm.StartsWith(r, StringComparison.Ordinal) ? norm[r.Length..] : norm;
    }

    private static string Sha256Of(string s) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(s))).ToLowerInvariant();
}

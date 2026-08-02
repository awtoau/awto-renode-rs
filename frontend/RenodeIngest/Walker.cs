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
                // Compiler-generated backing fields are not source constructs.
                if (member.IsImplicitlyDeclared) continue;

                // Accessors were skipped wholesale, on the grounds that
                // translating them would duplicate the property. That holds for
                // an AUTO-property, whose accessors carry no code -- but a
                // COMPUTED property's getter body is the only code there is, and
                // skipping it meant `BaudRate` had zero operations in the corpus
                // while being called twice from WriteChar. Accessors of members
                // that have storage are still skipped; the rest are walked.
                if (member is IMethodSymbol { AssociatedSymbol: { } assoc,
                        MethodKind: MethodKind.PropertyGet or MethodKind.PropertySet
                                 or MethodKind.EventAdd or MethodKind.EventRemove }
                    && HasStorageFor(assoc)) continue;

                var rec = BuildMember(member, typeRec.Key);
                if (rec is null) continue;
                result.Members.Add(rec);

                if (rec.Method is null)
                {
                    WalkInitializer(member, rec.Key, tree, model, result, ref nextOpId);
                    continue;
                }
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

    /// <summary>
    /// A field's, property's or event's INITIALISER, walked as its own operation
    /// tree and attached to the member.
    ///
    /// Operations were walked only for members that had a METHOD, so every
    /// initialiser written at the declaration was absent from the corpus --
    /// nothing thrown, no count to notice. `private bool x = true;` was
    /// therefore indistinguishable from `private bool x;`, which inverts the
    /// initial value, and an array's DECLARED length
    /// (`new IValueRegisterField[19]`) existed nowhere, so a length could only
    /// be inferred from the highest index later code happened to bind.
    ///
    /// Not a Roslyn limitation, and not subtle:
    /// `GetOperation(EqualsValueClauseSyntax)` returns the
    /// `IFieldInitializerOperation` / `IPropertyInitializerOperation` directly,
    /// and always has. Measured, not assumed -- 1,414 of 1,414 initialisers in
    /// the tree bind through it.
    ///
    /// A member whose declaration HAS an `= ...` clause and binds to nothing is
    /// counted in <see cref="FileResult.InitialisersUnbound"/> and fails the
    /// run, rather than being skipped. An initialiser that silently walks to
    /// nothing looks exactly like a member that has none.
    ///
    /// Two exclusions, both because the value is already on the member row and
    /// re-recording it would be a second source of truth:
    ///   * enum members -- the discriminant is `member.const_value`;
    ///   * const fields -- likewise, and Roslyn has already folded them.
    /// </summary>
    private static void WalkInitializer(ISymbol member, string key, SyntaxTree tree,
                                        SemanticModel model, FileResult result,
                                        ref int nextId)
    {
        if (member is IFieldSymbol { HasConstantValue: true }) return;
        foreach (var reference in member.DeclaringSyntaxReferences)
        {
            if (reference.SyntaxTree != tree) continue;
            var equals = reference.GetSyntax() switch
            {
                VariableDeclaratorSyntax v => v.Initializer,
                PropertyDeclarationSyntax p => p.Initializer,
                _ => null,
            };
            if (equals is null) continue;

            var op = model.GetOperation(equals);
            if (op is null)
            {
                result.InitialisersUnbound++;
                continue;
            }
            WalkOperations(op, key, result, ref nextId, model);
            result.InitialisersWalked++;
        }
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

    /// Does the member this accessor belongs to have storage? Auto-properties
    /// and field-like events do; computed properties do not, and their
    /// accessors carry the code.
    private static bool HasStorageFor(ISymbol assoc) => assoc switch
    {
        IEventSymbol e => IsFieldLikeEvent(e),
        _ => HasBackingField(assoc),
    };

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
                    // Enum discriminants land here; they are written into
                    // registers, so losing them would renumber the hardware.
                    ConstValue = f.HasConstantValue
                        ? Convert.ToString(f.ConstantValue,
                            System.Globalization.CultureInfo.InvariantCulture)
                        : null,
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
                        p.IsParams, p.HasExplicitDefaultValue,
                        DefaultValueOf(p)));
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
    /// A parameter's DEFAULT VALUE, as an invariant-culture string.
    ///
    /// `has_default` was recorded as a bare flag, so the corpus could say a
    /// parameter was optional but never what omitting it MEANS. That blocks
    /// every optional-argument call site (2,698 in the tree) and blocks folding
    /// a constructor into `Default`, because both need the value, not the flag.
    /// `IParameterSymbol.ExplicitDefaultValue` has always had it.
    ///
    /// ENCODING, and why it needs no sentinel: null is returned both when there
    /// is no default and when the default IS null (`= null`, or `= default` for
    /// a reference or non-primitive struct type). `has_default` separates those
    /// two -- (has_default = 1, default_value = NULL) means the default is
    /// null. A "null" string sentinel would instead collide with the string
    /// literal `"null"`.
    ///
    /// Values are formatted invariantly so the corpus is byte-identical on a
    /// machine with a different locale; `ToString()` on a double is
    /// locale-sensitive and would otherwise write `1,5`.
    /// </summary>
    private static string? DefaultValueOf(IParameterSymbol p)
    {
        // ExplicitDefaultValue THROWS when there is no explicit default -- it is
        // not a null-returning property.
        if (!p.HasExplicitDefaultValue) return null;
        return p.ExplicitDefaultValue switch
        {
            null => null,
            IFormattable f => f.ToString(null, System.Globalization.CultureInfo.InvariantCulture),
            var v => v.ToString(),
        };
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
                case IUnaryOperation u2:
                    // The SAME two facts Binary carries, and IUnaryOperation has
                    // always exposed them. Without `checked`, unary minus cannot
                    // be routed to the runtime the way Subtract was: every Unary
                    // row's detail was empty, so the emitter would have had to
                    // ASSUME an unchecked context -- a guess dressed as a
                    // mapping. `-int.MinValue` is the case that separates them.
                    Add("checked", u2.IsChecked);
                    Add("lifted", u2.IsLifted);
                    break;
                case ICatchClauseOperation cc:
                    // `catch (E e) when (cond)` -- an exception FILTER. It was
                    // to be recorded so a FUTURE corpus would fail loudly; the
                    // current one already holds five of 268 clauses, a count
                    // that was never re-taken after the corpus stopped being a
                    // hand-picked subset. A filter is not a guard at the top of
                    // the handler: it runs BEFORE unwinding and may DECLINE,
                    // leaving the exception to propagate with the stack intact,
                    // so translating one as an `if` inside the body is wrong.
                    // The exception type is recorded with it because a catch
                    // clause's type is not on `op.Type`.
                    Add("filter", cc.Filter is not null);
                    Add("extype", cc.ExceptionType?.ToDisplayString());
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
                case ILoopOperation lp:
                    // For, ForEach, While and Do all arrive as kind `Loop`.
                    // They have different child shapes and different Rust
                    // spellings, so without this the emitter cannot tell a
                    // `for(;;)` from a `foreach`.
                    Add("loop", lp.LoopKind.ToString());
                    if (lp is IForEachLoopOperation fe
                        && fe.Locals.FirstOrDefault() is { } fev)
                    {
                        Add("var", fev.Name);
                        Add("vartype", fev.Type?.ToDisplayString() ?? "");
                    }
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
                // PATTERNS carry an operator kind for exactly the same reason
                // expressions do, and it was not being read. `RelationalPattern`
                // without it cannot distinguish `> 5` from `< 5`; `BinaryPattern`
                // without it cannot distinguish `and` from `or`. Both are
                // `Microsoft.CodeAnalysis.Operations.BinaryOperatorKind`, the
                // same enum stored for IBinaryOperation above, so it lands in
                // the same column the emitters already read.
                //
                // The ninth ingest gap, and again a property Roslyn always
                // exposed. It was invisible until the corpus cut was removed:
                // the cut contained no C# pattern matching at all.
                IRelationalPatternOperation rp => rp.OperatorKind.ToString(),
                IBinaryPatternOperation bp => bp.OperatorKind.ToString(),
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

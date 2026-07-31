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
                foreach (var reference in member.DeclaringSyntaxReferences)
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
                };
            case IEventSymbol e:
                return new MemberRec
                {
                    Key = Key(e), TypeKey = typeKey, Kind = "event", Name = e.Name,
                    DeclaredType = e.Type.ToDisplayString(),
                    Accessibility = e.DeclaredAccessibility.ToString().ToLowerInvariant(),
                    IsStatic = e.IsStatic, IsReadOnly = false,
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
                    HasBody = !m.IsAbstract && !m.IsExtern,
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

            result.Operations.Add(new OperationRec
            {
                LocalId = id,
                ParentLocalId = parent,
                MethodKey = methodKey,
                Ordinal = ordinal,
                Depth = depth,
                Kind = op.Kind.ToString(),
                Type = op.Type?.ToDisplayString(),
                Symbol = symbol is null ? null : Key(symbol),
                ConstValue = op.ConstantValue.HasValue
                             ? op.ConstantValue.Value?.ToString() ?? "null" : null,
                SpanStart = op.Syntax.Span.Start,
                SpanLen = op.Syntax.Span.Length,
            });

            switch (op)
            {
                case IInvocationOperation inv:
                    result.Calls.Add(new CallSiteRec(
                        methodKey, Key(inv.TargetMethod), null, id, inv.TargetMethod.IsVirtual
                                                                   || inv.TargetMethod.IsAbstract));
                    break;
                case IObjectCreationOperation { Constructor: not null } oc:
                    result.Calls.Add(new CallSiteRec(methodKey, Key(oc.Constructor), null, id, false));
                    break;
                case IFieldReferenceOperation fr:
                    result.FieldAccesses.Add(new FieldAccessRec(
                        methodKey, Key(fr.Field), id, IsWriteTarget(fr)));
                    break;
            }

            // Push in reverse so children pop in source order, which keeps the
            // emitted ordering identical between runs and thread counts.
            var children = op.ChildOperations.ToList();
            for (var i = children.Count - 1; i >= 0; i--)
                stack.Push((children[i], id, i, depth + 1));
        }
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

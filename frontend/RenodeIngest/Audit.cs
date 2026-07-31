using System.Reflection;
using Microsoft.CodeAnalysis;

namespace RenodeIngest;

/// <summary>
/// Report what Roslyn EXPOSES per IOperation kind, by reflection.
///
/// Written after six ingest gaps in a row turned out to be properties Roslyn
/// already provided and this tool simply did not read: `IBinaryOperation
/// .OperatorKind`, `IArgumentOperation.Parameter`, `PartialImplementationPart`,
/// `ISymbol.OriginalDefinition`, `IVariableDeclaratorOperation.Symbol`,
/// `ILocalFunctionOperation.Symbol`. **None were Roslyn limitations.**
///
/// `check_ingest.py` could only ask "did we extract anything for this kind",
/// and the list of kinds it deemed structural was hand-declared — the same
/// fallible judgement that produced the gaps. This replaces the judgement with
/// the API surface itself: if an interface declares a data-bearing property,
/// either the corpus carries it or there is a recorded reason it does not.
/// </summary>
public static class Audit
{
    /// Properties every operation has. They describe position in the tree, not
    /// content, and the walk already captures them.
    private static readonly HashSet<string> Universal = new()
    {
        "Kind", "Syntax", "Type", "ConstantValue", "Children", "ChildOperations",
        "Language", "IsImplicit", "SemanticModel", "Parent",
    };

    public static void Run()
    {
        var asm = typeof(IOperation).Assembly;
        var kinds = asm.GetTypes()
            .Where(t => t.IsInterface
                        && t.Name.StartsWith("I", StringComparison.Ordinal)
                        && t.Name.EndsWith("Operation", StringComparison.Ordinal)
                        && typeof(IOperation).IsAssignableFrom(t)
                        && t != typeof(IOperation))
            .OrderBy(t => t.Name);

        Console.WriteLine("kind\tproperty\ttype");
        foreach (var t in kinds)
        {
            // DeclaredOnly: inherited members belong to the base interface's rows.
            var props = t.GetProperties(BindingFlags.Public | BindingFlags.Instance
                                      | BindingFlags.DeclaredOnly)
                .Where(p => !Universal.Contains(p.Name))
                // A property returning an operation is a CHILD, which the tree
                // walk already records. Only leaf data needs extracting.
                .Where(p => !typeof(IOperation).IsAssignableFrom(p.PropertyType))
                .Where(p => !IsOperationSequence(p.PropertyType))
                .OrderBy(p => p.Name);

            var kind = t.Name[1..^9];  // IBinaryOperation -> Binary
            foreach (var p in props)
            {
                Console.WriteLine($"{kind}\t{p.Name}\t{Short(p.PropertyType)}");
            }
        }
    }

    private static bool IsOperationSequence(Type t) =>
        t.IsGenericType && t.GetGenericArguments()
            .Any(a => typeof(IOperation).IsAssignableFrom(a));

    private static string Short(Type t)
    {
        var n = t.Name;
        if (t.IsGenericType)
        {
            var args = string.Join(",", t.GetGenericArguments().Select(a => a.Name));
            n = $"{n.Split('`')[0]}<{args}>";
        }
        return n;
    }
}

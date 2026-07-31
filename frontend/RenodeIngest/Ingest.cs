using System.Diagnostics;
using Microsoft.CodeAnalysis;

namespace RenodeIngest;

/// <summary>Placeholder until the IOperation walk lands. See issue #30.</summary>
public static class Ingest
{
    public static Task<bool> RunAsync(Compilation compilation, IReadOnlyList<SyntaxTree> trees,
                                      string dbPath, Stopwatch total)
    {
        Console.WriteLine("\ningest    not implemented yet -- run with --dry-run");
        return Task.FromResult(false);
    }
}

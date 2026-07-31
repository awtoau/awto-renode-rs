using System.Diagnostics;
using Microsoft.Build.Locator;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.MSBuild;

namespace RenodeIngest;

/// <summary>
/// Roslyn corpus ingest. Issue #30 (R1).
///
/// Loads Renode's compilation, filters to the ARM/STM32F427 cut, walks the
/// IOperation tree, and writes the corpus to SQLite. The translator reads only
/// from that database -- see docs/rulesdb-design.md.
///
/// Started on MSBuildWorkspace deliberately: the design doc calls for bypassing
/// it with CSharpCompilation.Create, but says to MEASURE the serial load before
/// doing so. The load time is reported on every run and is the Amdahl floor for
/// the whole pipeline.
///
/// Paths come from RENODE_SRC; nothing here embeds an absolute path.
/// </summary>
public static class Program
{
    public static async Task<int> Main(string[] args)
    {
        var dryRun = args.Contains("--dry-run");
        var dbPath = ArgValue(args, "--db") ?? "rulesdb/patterns.db";

        var renodeSrc = Environment.GetEnvironmentVariable("RENODE_SRC");
        if (string.IsNullOrWhiteSpace(renodeSrc))
        {
            Console.Error.WriteLine("RENODE_SRC not set (see .env.example)");
            return 1;
        }

        var project = Path.Combine(renodeSrc,
            "src", "Infrastructure", "src", "Infrastructure.csproj");
        if (!File.Exists(project))
        {
            Console.Error.WriteLine($"project not found under RENODE_SRC: {project}");
            return 1;
        }

        // MSBuildLocator must run before any MSBuild type is touched.
        if (!MSBuildLocator.IsRegistered)
        {
            var instance = MSBuildLocator.QueryVisualStudioInstances()
                .OrderByDescending(i => i.Version).FirstOrDefault();
            if (instance is null)
            {
                Console.Error.WriteLine("no MSBuild instance found -- is the .NET SDK installed?");
                return 1;
            }
            Console.WriteLine($"msbuild   {instance.Version} at {Path.GetFileName(instance.MSBuildPath)}");
            MSBuildLocator.RegisterInstance(instance);
        }

        return await Run(project, dbPath, dryRun);
    }

    // Kept in its own method so MSBuildLocator.RegisterInstance completes before
    // the JIT resolves any MSBuild-dependent type referenced here.
    private static async Task<int> Run(string project, string dbPath, bool dryRun)
    {
        var total = Stopwatch.StartNew();

        using var workspace = MSBuildWorkspace.Create();
        workspace.SkipUnrecognizedProjects = true;

        var diagnostics = new List<WorkspaceDiagnostic>();
        workspace.WorkspaceFailed += (_, e) => diagnostics.Add(e.Diagnostic);

        // THE SERIAL SECTION. Everything after this parallelises per file; this
        // does not, because cross-file type resolution needs the whole
        // compilation. Reported so the Amdahl ceiling is a measured number.
        var loadTimer = Stopwatch.StartNew();
        Console.WriteLine($"loading   {Path.GetFileName(project)} ...");
        var proj = await workspace.OpenProjectAsync(project);
        var compilation = await proj.GetCompilationAsync();
        loadTimer.Stop();

        if (compilation is null)
        {
            Console.Error.WriteLine("compilation was null");
            foreach (var d in diagnostics.Take(10)) Console.Error.WriteLine($"  {d.Message}");
            return 1;
        }

        var errors = diagnostics.Where(d => d.Kind == WorkspaceDiagnosticKind.Failure).ToList();
        Console.WriteLine($"loaded    {loadTimer.Elapsed.TotalSeconds:F1}s  "
                        + $"[SERIAL -- this is the Amdahl floor]");
        Console.WriteLine($"          {compilation.SyntaxTrees.Count()} syntax trees, "
                        + $"{proj.MetadataReferences.Count} metadata refs, "
                        + $"{errors.Count} workspace failures");
        foreach (var d in errors.Take(5)) Console.WriteLine($"  ! {Truncate(d.Message, 120)}");

        // Resolve the corpus cut against real documents, and report anything
        // that did not match -- a silently-missing file would quietly shrink
        // the corpus and invalidate every coverage number downstream.
        var trees = compilation.SyntaxTrees
            .Where(t => !string.IsNullOrEmpty(t.FilePath) && CorpusCut.Contains(t.FilePath))
            .ToList();

        var matched = new HashSet<string>();
        foreach (var t in trees)
        {
            var norm = t.FilePath.Replace('\\', '/');
            foreach (var s in CorpusCut.All())
                if (norm.EndsWith(s, StringComparison.Ordinal)) matched.Add(s);
        }
        var missing = CorpusCut.All().Where(s => !matched.Contains(s)).ToList();

        var loc = trees.Sum(t => t.GetText().Lines.Count);
        Console.WriteLine();
        Console.WriteLine($"corpus    {trees.Count}/{CorpusCut.All().Count()} files resolved, {loc:N0} lines");
        if (missing.Count > 0)
        {
            Console.WriteLine($"          {missing.Count} NOT FOUND -- corpus is incomplete:");
            foreach (var m in missing) Console.WriteLine($"            {m}");
        }

        // Compilation diagnostics tell us whether the semantic model is
        // trustworthy. Ingesting from a compilation with unresolved types would
        // silently produce null symbols throughout.
        var compErrors = compilation.GetDiagnostics()
            .Where(d => d.Severity == DiagnosticSeverity.Error).ToList();
        Console.WriteLine($"semantics {compErrors.Count} compilation errors");
        foreach (var d in compErrors.Take(5))
            Console.WriteLine($"          ! {Truncate(d.GetMessage(), 110)}");

        if (dryRun)
        {
            Console.WriteLine($"\ndry run -- nothing written. total {total.Elapsed.TotalSeconds:F1}s");
            return missing.Count == 0 ? 0 : 1;
        }

        var written = await Ingest.RunAsync(compilation, trees, dbPath, total);
        Console.WriteLine($"\ntotal     {total.Elapsed.TotalSeconds:F1}s");
        return written ? 0 : 1;
    }

    private static string? ArgValue(string[] args, string name)
    {
        var i = Array.IndexOf(args, name);
        return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
    }

    private static string Truncate(string s, int n) =>
        s.Length <= n ? s : s[..n] + "...";
}

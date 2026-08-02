using System.Diagnostics;
using Microsoft.Build.Locator;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.MSBuild;

namespace RenodeIngest;

/// <summary>
/// Roslyn corpus ingest. Issue #30 (R1).
///
/// Loads Renode's compilation, walks the IOperation tree of EVERY file in it,
/// and writes the corpus to SQLite. The translator reads only from that
/// database -- see docs/rulesdb-design.md.
///
/// There is no corpus cut. It was a hand-typed file list that was not
/// transitively closed -- it held types whose base classes and interfaces it
/// lacked -- so it truncated 69% of inheritance chains and hid two real field
/// collisions. It was also the wrong proxy: trace availability is a fact about
/// which peripherals have recorded traces, not about which files an ingest
/// walked. See docs/decisions/remove-the-cut.md.
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
        // Resolved against the REPO ROOT, not the current directory. The default
        // used to be the bare relative path, so `dotnet run` from
        // frontend/RenodeIngest -- the natural place to run it from -- wrote a
        // SECOND corpus at frontend/RenodeIngest/rulesdb/patterns.db. Its `-shm`
        // and `-wal` were then committed and pushed, because .gitignore anchored
        // its rulesdb patterns to the top level.
        //
        // Worse than the stray files: two corpora, and the emitter reads the
        // top-level one. An ingest that appeared to succeed could leave the
        // corpus the converter actually uses untouched.
        //
        // This is CLAUDE.md's rule for scripts -- resolve the workspace with
        // `git rev-parse --show-toplevel`, never a hardcoded or cwd-relative
        // root -- which the C# frontend was not following.
        var dbPath = ArgValue(args, "--db") ?? Path.Combine(RepoRoot(), "rulesdb", "patterns.db");
        var threads = int.TryParse(ArgValue(args, "-j"), out var j) && j > 0
                      ? j : Environment.ProcessorCount;
        // `--all` NO LONGER SELECTS SCOPE. Every run reads every file, so there
        // is nothing left for it to widen. What it still declares is the run's
        // PURPOSE: this is a TOOLING HEALTH CHECK -- does the walker crash, does
        // it lose data silently (scripts/check_breadth.py) -- and not the
        // canonical corpus.
        //
        // The guard below is deliberately KEPT, and not because it still gates
        // tiering: `rule_commit_threshold` now counts `oracle_tier > 0`, so a
        // run's config can no longer manufacture a `committed` rule
        // (scripts/check_commit_tier.py). It is kept because a health-check run
        // goes to a scratch database that may be truncated, re-run mid-walk or
        // left half-written, and every rule/cluster consumer -- analyse_corpus,
        // census, rules.py -- refuses a database tagged 'breadth' rather than
        // silently deriving work from one. Overwriting the canonical corpus with
        // a smoke test is a real way to lose a corpus, and costs nothing to
        // refuse.
        var all = args.Contains("--all");

        // Reflection audit of Roslyn's own API surface. Needs no corpus and no
        // Renode tree, so it runs before any path handling.
        if (args.Contains("--audit"))
        {
            Audit.Run();
            return 0;
        }

        var renodeSrc = Environment.GetEnvironmentVariable("RENODE_SRC");
        if (string.IsNullOrWhiteSpace(renodeSrc))
        {
            Console.Error.WriteLine("RENODE_SRC not set (see .env.example)");
            return 1;
        }

        if (all && Path.GetFullPath(dbPath).EndsWith(
                Path.Combine("rulesdb", "patterns.db"), StringComparison.Ordinal))
        {
            Console.Error.WriteLine(
                "--all is a tooling health check and must not write the canonical corpus.\n" +
                "It reads the same files a normal run does -- it differs only in that its\n" +
                "output is scratch. Pass --db tmp/breadth.db instead.");
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

        return await Run(project, renodeSrc, dbPath, dryRun, threads, all);
    }

    // Kept in its own method so MSBuildLocator.RegisterInstance completes before
    // the JIT resolves any MSBuild-dependent type referenced here.
    private static async Task<int> Run(string project, string renodeSrc, string dbPath,
                                      bool dryRun, int threads, bool all)
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

        // Every document in the compilation. The only exclusion is a tree with
        // no file path -- a generated or in-memory tree, which has no source to
        // point provenance at.
        //
        // Nothing is filtered by name. The previous file list was hand-typed and
        // silently incomplete; the corpus is now defined by the compilation
        // itself, which is the one description of it that cannot drift.
        var trees = compilation.SyntaxTrees
            .Where(t => !string.IsNullOrEmpty(t.FilePath))
            .ToList();

        var skipped = compilation.SyntaxTrees.Count() - trees.Count;
        var loc = trees.Sum(t => t.GetText().Lines.Count);
        Console.WriteLine();
        Console.WriteLine($"corpus    {trees.Count} files, {loc:N0} lines"
                        + (all ? "   [HEALTH CHECK -- scratch database]" : ""));
        if (skipped > 0)
            Console.WriteLine($"          {skipped} tree(s) skipped: no file path (generated source)");

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
            // A compilation that produced no document is a broken load, not an
            // empty corpus. It is the only way a dry run can now fail: there is
            // no file list left to come up short against.
            return trees.Count > 0 ? 0 : 1;
        }

        var commit = GitCommit(renodeSrc);
        // 'tree' is the canonical corpus -- the whole compilation. 'breadth' is
        // the same files written to a scratch database as a health check, and is
        // refused by every rule/cluster consumer.
        var written = await Ingest.RunAsync(compilation, trees, dbPath, renodeSrc, commit,
                                            threads, all ? "breadth" : "tree");
        Console.WriteLine($"\ntotal     {total.Elapsed.TotalSeconds:F1}s");
        return written ? 0 : 1;
    }

    private static string GitCommit(string dir)
    {
        try
        {
            var psi = new System.Diagnostics.ProcessStartInfo("git", "rev-parse HEAD")
            { WorkingDirectory = dir, RedirectStandardOutput = true };
            using var p = System.Diagnostics.Process.Start(psi);
            return p is null ? "unknown" : p.StandardOutput.ReadToEnd().Trim();
        }
        catch { return "unknown"; }
    }

    private static string? ArgValue(string[] args, string name)
    {
        var i = Array.IndexOf(args, name);
        return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
    }

    private static string Truncate(string s, int n) =>
        s.Length <= n ? s : s[..n] + "...";

    /// <summary>
    /// The workspace root, from git — the same rule every script in this repo
    /// follows, and which this program did not.
    ///
    /// Falls back to the current directory rather than throwing: a tarball
    /// export with no `.git` should still run, and `--db` overrides this
    /// anyway. The fallback is announced, because a silent one is how the
    /// second corpus appeared in the first place.
    /// </summary>
    private static string RepoRoot()
    {
        try
        {
            using var p = System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
            {
                FileName = "git",
                Arguments = "rev-parse --show-toplevel",
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            });
            if (p is not null)
            {
                var root = p.StandardOutput.ReadToEnd().Trim();
                p.WaitForExit();
                if (p.ExitCode == 0 && root.Length > 0 && Directory.Exists(root))
                    return root;
            }
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"warn      could not ask git for the repo root: {e.Message}");
        }
        Console.Error.WriteLine(
            "warn      no git repo root; writing relative to the current directory. " +
            "Pass --db if that is not what you want.");
        return Directory.GetCurrentDirectory();
    }
}

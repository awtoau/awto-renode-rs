using System.Collections.Concurrent;
using System.Diagnostics;
using Microsoft.CodeAnalysis;
using Microsoft.Data.Sqlite;

namespace RenodeIngest;

/// <summary>
/// Drives the parallel walk and writes the corpus to SQLite.
///
/// DETERMINISM IS THE POINT. Output must be byte-identical whether the walk runs
/// on one thread or 31, or every diff against the C# reference becomes
/// scheduling noise and the oracle is worthless. Two rules deliver that:
///
///   1. Files are walked in parallel but WRITTEN in sorted path order.
///   2. Ids are assigned during the serial write, never by the workers, so they
///      depend on content ordering rather than completion ordering.
///
/// Cross-file references arrive as symbol keys and are resolved against the id
/// maps built during the write, which is why the write is a second pass.
/// </summary>
public static class Ingest
{
    public static async Task<bool> RunAsync(Compilation compilation,
                                            IReadOnlyList<SyntaxTree> trees,
                                            string dbPath, string treeRoot,
                                            string renodeCommit, int threads,
                                            string config)
    {
        // --- Pass 1: parallel walk -------------------------------------------
        var walk = Stopwatch.StartNew();
        var results = new ConcurrentDictionary<string, FileResult>();
        var failures = new ConcurrentBag<string>();

        Parallel.ForEach(trees, new ParallelOptions { MaxDegreeOfParallelism = threads }, tree =>
        {
            try
            {
                var r = Walker.Walk(compilation, tree, treeRoot);
                results[r.Path] = r;
            }
            catch (Exception ex)
            {
                failures.Add($"{Path.GetFileName(tree.FilePath)}: {ex.GetType().Name}: {ex.Message}");
            }
        });
        walk.Stop();

        Console.WriteLine($"walk      {walk.Elapsed.TotalSeconds:F1}s on {threads} threads, "
                        + $"{results.Count}/{trees.Count} files");
        foreach (var f in failures.OrderBy(x => x)) Console.WriteLine($"          ! {f}");
        if (!failures.IsEmpty) return false;

        // Sorted: this is what makes ids independent of thread scheduling.
        var ordered = results.Values.OrderBy(r => r.Path, StringComparer.Ordinal).ToList();

        // --- Pass 2: serial write --------------------------------------------
        var write = Stopwatch.StartNew();
        var full = Path.GetFullPath(dbPath);
        Directory.CreateDirectory(Path.GetDirectoryName(full)!);
        foreach (var stale in new[] { full, full + "-wal", full + "-shm" })
            if (File.Exists(stale)) File.Delete(stale);

        await using var db = new SqliteConnection($"Data Source={full}");
        await db.OpenAsync();

        var schema = FindSchema();
        if (schema is null)
        {
            Console.Error.WriteLine("rulesdb/schema.sql not found");
            return false;
        }
        await Exec(db, await File.ReadAllTextAsync(schema));

        await using var tx = (SqliteTransaction)await db.BeginTransactionAsync();

        var runId = await ScalarInsert(db, tx,
            "INSERT INTO corpus_run(started_at,renode_commit,tool_version,config,host) " +
            "VALUES ($a,$b,$c,$d,$e) RETURNING id",
            ("$a", DateTimeOffset.Now.ToString("yyyy-MM-ddTHH:mm:sszzz")),
            ("$b", renodeCommit), ("$c", ToolVersion()), ("$d", config),
            ("$e", Environment.MachineName));

        var typeIds = new Dictionary<string, long>(StringComparer.Ordinal);
        var memberIds = new Dictionary<string, long>(StringComparer.Ordinal);
        var opIds = new Dictionary<(string File, int Local), long>();

        // EVERY `continue` below is a row the walk produced and the write threw
        // away. They used to be silent, and that silence cost a whole reverted
        // branch: field initialisers were walked, never landed, and the only
        // symptom was an array three elements short -- which compiles.
        //
        // A drop is not automatically a bug (a field access whose target is a
        // BCL member has nothing in the corpus to point at), so this counts and
        // names rather than throwing. What it removes is the ability for a
        // whole category to vanish without a number moving. The categories that
        // SHOULD be empty are a hard failure, checked before the commit.
        var drops = new SortedDictionary<string, long>(StringComparer.Ordinal);
        var dropExample = new Dictionary<string, string>(StringComparer.Ordinal);
        void Drop(string what, string example)
        {
            drops[what] = drops.GetValueOrDefault(what) + 1;
            if (!dropExample.ContainsKey(what)) dropExample[what] = example;
        }

        // 2a. files, types, members, methods
        foreach (var f in ordered)
        {
            var fileId = await ScalarInsert(db, tx,
                "INSERT INTO file(run_id,path,sha256,loc) VALUES ($r,$p,$s,$l) RETURNING id",
                ("$r", runId), ("$p", f.Path), ("$s", f.Sha256), ("$l", f.Loc));

            foreach (var t in f.Types)
            {
                if (typeIds.ContainsKey(t.Key)) continue;   // partial classes
                var id = await ScalarInsert(db, tx,
                    "INSERT INTO type(run_id,file_id,key,namespace,name,kind,is_abstract," +
                    "is_static,is_generic,accessibility) " +
                    "VALUES ($r,$f,$y,$n,$m,$k,$a,$s,$g,$c) RETURNING id",
                    ("$r", runId), ("$f", fileId), ("$y", t.Key),
                    ("$n", t.Namespace), ("$m", t.Name),
                    ("$k", t.Kind), ("$a", t.IsAbstract ? 1 : 0), ("$s", t.IsStatic ? 1 : 0),
                    ("$g", t.IsGeneric ? 1 : 0), ("$c", t.Accessibility));
                typeIds[t.Key] = id;
            }

            foreach (var m in f.Members)
            {
                if (memberIds.ContainsKey(m.Key)) continue;
                if (!typeIds.TryGetValue(m.TypeKey, out var typeId))
                {
                    Drop("member: containing type not written", m.Key);
                    continue;
                }
                var id = await ScalarInsert(db, tx,
                    "INSERT INTO member(run_id,type_id,key,kind,name,declared_type," +
                    "accessibility,is_static,is_readonly,has_storage,const_value) " +
                    "VALUES ($r,$t,$y,$k,$n,$d,$a,$s,$o,$h,$cv) RETURNING id",
                    ("$r", runId), ("$t", typeId), ("$y", m.Key),
                    ("$k", m.Kind), ("$n", m.Name),
                    ("$d", m.DeclaredType), ("$a", m.Accessibility),
                    ("$s", m.IsStatic ? 1 : 0), ("$o", m.IsReadOnly ? 1 : 0),
                    ("$h", m.HasStorage ? 1 : 0),
                    ("$cv", (object?)m.ConstValue ?? DBNull.Value));
                memberIds[m.Key] = id;

                if (m.Method is not { } mm) continue;
                await Exec(db, tx,
                    "INSERT INTO method(member_id,signature,return_type,is_virtual,is_abstract," +
                    "is_override,is_extension,has_body) VALUES ($i,$s,$r,$v,$a,$o,$e,$b)",
                    ("$i", id), ("$s", mm.Signature), ("$r", mm.ReturnType),
                    ("$v", mm.IsVirtual ? 1 : 0), ("$a", mm.IsAbstract ? 1 : 0),
                    ("$o", mm.IsOverride ? 1 : 0), ("$e", mm.IsExtension ? 1 : 0),
                    ("$b", mm.HasBody ? 1 : 0));

                foreach (var p in mm.Parameters)
                    await Exec(db, tx,
                        "INSERT INTO parameter(method_id,ordinal,name,type,is_out,is_ref," +
                        "is_params,has_default,default_value) " +
                        "VALUES ($m,$o,$n,$t,$u,$r,$p,$d,$v)",
                        ("$m", id), ("$o", p.Ordinal), ("$n", p.Name), ("$t", p.Type),
                        ("$u", p.IsOut ? 1 : 0), ("$r", p.IsRef ? 1 : 0),
                        ("$p", p.IsParams ? 1 : 0), ("$d", p.HasDefault ? 1 : 0),
                        ("$v", (object?)p.DefaultValue ?? DBNull.Value));
            }
        }

        // 2b. resolve bases and interfaces, now that every type has an id
        var seenType = new HashSet<string>(StringComparer.Ordinal);
        foreach (var f in ordered)
        foreach (var t in f.Types)
        {
            if (!seenType.Add(t.Key)) continue;
            if (!typeIds.TryGetValue(t.Key, out var id)) continue;
            if (t.BaseKey is not null)
            {
                var known = typeIds.TryGetValue(t.BaseKey, out var b);
                await Exec(db, tx,
                    "UPDATE type SET base_type_id=$b, base_extern=$e WHERE id=$i",
                    ("$b", known ? b : DBNull.Value),
                    ("$e", known ? DBNull.Value : t.BaseKey),
                    ("$i", id));
            }
            foreach (var iface in t.Interfaces)
                await Exec(db, tx,
                    "INSERT OR IGNORE INTO type_implements(run_id,type_id,interface_id," +
                    "interface_name) VALUES ($r,$t,$i,$n)",
                    ("$r", runId), ("$t", id),
                    ("$i", typeIds.TryGetValue(iface, out var iid) ? iid : DBNull.Value),
                    ("$n", iface));
        }

        // 2c. operations
        foreach (var f in ordered)
        foreach (var o in f.Operations)
        {
            if (!memberIds.TryGetValue(o.MethodKey, out var methodId))
            {
                Drop("operation: owning member not written", $"{o.Kind} in {o.MethodKey}");
                continue;
            }
            object parentId = o.ParentLocalId is { } pl && opIds.TryGetValue((f.Path, pl), out var p)
                              ? p : DBNull.Value;
            var id = await ScalarInsert(db, tx,
                "INSERT INTO operation(run_id,method_id,parent_id,ordinal,depth,kind,type," +
                "symbol,const_value,detail,span_start,span_len) " +
                "VALUES ($r,$m,$p,$o,$d,$k,$t,$s,$c,$e,$b,$l) RETURNING id",
                ("$r", runId), ("$m", methodId), ("$p", parentId), ("$o", o.Ordinal),
                ("$d", o.Depth), ("$k", o.Kind), ("$t", (object?)o.Type ?? DBNull.Value),
                ("$s", (object?)o.Symbol ?? DBNull.Value),
                ("$c", (object?)o.ConstValue ?? DBNull.Value),
                ("$e", (object?)o.Detail ?? DBNull.Value),
                ("$b", o.SpanStart), ("$l", o.SpanLen));
            opIds[(f.Path, o.LocalId)] = id;
        }

        // 2d. graphs
        foreach (var f in ordered)
        {
            foreach (var c in f.Calls)
            {
                if (!memberIds.TryGetValue(c.CallerKey, out var caller))
                {
                    Drop("call_site: caller not written", c.CallerKey);
                    continue;
                }
                if (!opIds.TryGetValue((f.Path, c.OperationLocalId), out var opId))
                {
                    Drop("call_site: call operation not written", c.CallerKey);
                    continue;
                }
                var inCorpus = c.CalleeKey is not null && memberIds.ContainsKey(c.CalleeKey);
                await Exec(db, tx,
                    "INSERT INTO call_site(run_id,caller_id,callee_id,callee_extern," +
                    "operation_id,is_virtual) VALUES ($r,$c,$e,$x,$o,$v)",
                    ("$r", runId), ("$c", caller),
                    ("$e", inCorpus ? memberIds[c.CalleeKey!] : DBNull.Value),
                    ("$x", inCorpus ? DBNull.Value : (object?)c.CalleeKey ?? DBNull.Value),
                    ("$o", opId), ("$v", c.IsVirtual ? 1 : 0));
            }
            foreach (var a in f.FieldAccesses)
            {
                if (!memberIds.TryGetValue(a.MethodKey, out var mid))
                {
                    Drop("field_access: accessing member not written", a.MethodKey);
                    continue;
                }
                // EXPECTED and not a bug: the field is outside the corpus (a BCL
                // or third-party member), so there is no row to point at.
                // Counted anyway -- a sudden jump means the corpus shrank.
                if (!memberIds.TryGetValue(a.MemberKey, out var fid))
                {
                    Drop("field_access: target field outside the corpus", a.MemberKey);
                    continue;
                }
                if (!opIds.TryGetValue((f.Path, a.OperationLocalId), out var opId))
                {
                    Drop("field_access: reference operation not written", a.MemberKey);
                    continue;
                }
                await Exec(db, tx,
                    "INSERT INTO field_access(run_id,method_id,member_id,operation_id,is_write) " +
                    "VALUES ($r,$m,$f,$o,$w)",
                    ("$r", runId), ("$m", mid), ("$f", fid), ("$o", opId),
                    ("$w", a.IsWrite ? 1 : 0));
            }
        }

        var walked = ordered.Sum(r => (long)r.InitialisersWalked);
        var unbound = ordered.Sum(r => (long)r.InitialisersUnbound);
        Console.WriteLine($"initialisers {walked:N0} walked, {unbound} that had an "
                        + "`= ...` clause and bound to no operation");

        Console.WriteLine();
        if (drops.Count == 0)
        {
            Console.WriteLine("drops     none -- every walked row was written");
        }
        else
        {
            Console.WriteLine("drops     rows the walk produced and the write discarded");
            foreach (var (what, n) in drops)
                Console.WriteLine($"          {n,8:N0}  {what}   e.g. {Truncate(dropExample[what], 90)}");
        }

        // The categories that must be empty. A member the walk built and the
        // write could not place, or an operation with no owning member, means
        // the two passes disagree about what exists -- the exact failure that
        // made field initialisers vanish while every count that existed stayed
        // green.
        //
        // Checked BEFORE the commit, and the transaction is abandoned, so an
        // incomplete corpus never reaches disk. A written-but-refused database
        // is how a stale corpus gets used by the next tool: the ingest exits
        // non-zero, and whoever ignores that finds a file where they expect one.
        var fatal = drops.Where(d => !d.Key.StartsWith("field_access: target field outside",
                                                       StringComparison.Ordinal)).ToList();
        if (fatal.Count > 0 || unbound > 0)
        {
            Console.Error.WriteLine();
            Console.Error.WriteLine("INGEST INCOMPLETE -- the walk produced rows the write did not store.");
            foreach (var (what, n) in fatal)
                Console.Error.WriteLine($"  {n:N0}  {what}");
            if (unbound > 0)
                Console.Error.WriteLine($"  {unbound:N0}  initialiser clause bound to no operation");
            Console.Error.WriteLine("Nothing was committed.");
            await tx.RollbackAsync();
            return false;
        }

        await Exec(db, tx, "UPDATE corpus_run SET finished_at=$f WHERE id=$i",
                   ("$f", DateTimeOffset.Now.ToString("yyyy-MM-ddTHH:mm:sszzz")), ("$i", runId));
        await tx.CommitAsync();
        write.Stop();

        Console.WriteLine($"write     {write.Elapsed.TotalSeconds:F1}s [SERIAL -- ids assigned here, "
                        + "so they never depend on thread scheduling]");

        await Report(db, full);
        return true;
    }

    private static string Truncate(string s, int n) => s.Length <= n ? s : s[..n] + "...";

    private static async Task Report(SqliteConnection db, string dbPath)
    {
        async Task<long> C(string t)
        {
            await using var c = db.CreateCommand();
            c.CommandText = $"SELECT COUNT(*) FROM {t}";
            return Convert.ToInt64(await c.ExecuteScalarAsync() ?? 0L);
        }
        Console.WriteLine();
        Console.WriteLine($"corpus    {await C("type")} types, {await C("member")} members, "
                        + $"{await C("method")} methods, {await C("parameter")} parameters");
        Console.WriteLine($"          {await C("operation"):N0} operation nodes, "
                        + $"{await C("call_site"):N0} call sites, "
                        + $"{await C("field_access"):N0} field accesses");
        Console.WriteLine($"db        {new FileInfo(dbPath).Length / 1024.0 / 1024.0:F1} MB");
    }

    private static string? FindSchema()
    {
        var dir = new DirectoryInfo(Directory.GetCurrentDirectory());
        while (dir is not null)
        {
            var candidate = Path.Combine(dir.FullName, "rulesdb", "schema.sql");
            if (File.Exists(candidate)) return candidate;
            dir = dir.Parent;
        }
        return null;
    }

    private static string ToolVersion() =>
        typeof(Ingest).Assembly.GetName().Version?.ToString() ?? "0.0.0";

    private static async Task Exec(SqliteConnection db, string sql)
    {
        await using var c = db.CreateCommand();
        c.CommandText = sql;
        await c.ExecuteNonQueryAsync();
    }

    private static async Task Exec(SqliteConnection db, SqliteTransaction tx, string sql,
                                   params (string, object?)[] ps)
    {
        await using var c = db.CreateCommand();
        c.Transaction = tx;
        c.CommandText = sql;
        foreach (var (n, v) in ps) c.Parameters.AddWithValue(n, v ?? DBNull.Value);
        await c.ExecuteNonQueryAsync();
    }

    private static async Task<long> ScalarInsert(SqliteConnection db, SqliteTransaction tx,
                                                 string sql, params (string, object?)[] ps)
    {
        await using var c = db.CreateCommand();
        c.Transaction = tx;
        c.CommandText = sql;
        foreach (var (n, v) in ps) c.Parameters.AddWithValue(n, v ?? DBNull.Value);
        return Convert.ToInt64(await c.ExecuteScalarAsync());
    }
}

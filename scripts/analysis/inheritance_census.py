#!/usr/bin/env python3
"""Measure what inheritance actually costs, so issue #56 is decided on numbers.

Issue #56 asks whether a derived type's base should be MERGED (base members
become siblings of the derived members in one flat `State`, which is what the
emitter does today) or EMBEDDED (`struct Derived { parent: Base, ... }`, which
is what IL2CPP, Servo, QEMU and c2rust all do). That question was argued in
`docs/research/inheritance.md` and never measured, so this measures it.

WHY A SCRIPT AND NOT A TABLE IN A DOC
-------------------------------------
CLAUDE.md forbids a second source of truth. A hand-typed "10 derived types, 9
base calls" in a decision doc is a copy that drifts the moment the cut changes
-- and the decision would keep citing a number that stopped being true, while
reading exactly as it did when it was. So the numbers live in
`docs/status/inheritance.json`, this script produces them, and the doc points
at the file.

WHAT IS COUNTED, AND WHAT EACH NUMBER DECIDES
---------------------------------------------
1. `chains`      -- every class's ancestor chain, and where it leaves the cut.
                    Decides how much of the problem either model can even see:
                    a base outside the cut cannot be flattened OR embedded,
                    because its members are unknown.

2. `collisions`  -- a member name declared at two levels of one chain. MERGE
                    puts both in one struct and one of them is lost; EMBED
                    cannot collide, because the base's members live behind a
                    field. This is the measurement that most directly separates
                    the two models, so it is counted twice: on the C# name, and
                    on the snake_case name the emitter actually writes (two C#
                    names can collide only after snake-casing).

3. `base_access` -- every site in derived code that reaches a member declared
                    on an ancestor: `base.X()`, an inherited call through
                    `this`, a read of a protected base field. Each carries what
                    it costs under each model, so the cost is a sum over real
                    sites rather than an opinion.

4. `overrides`   -- virtual/override/abstract counts, and how many overrides
                    shadow a base member of the same name. The shadowed set is
                    exactly the set MERGE must invent a qualified name for.

NOT MEASURED HERE, DELIBERATELY
-------------------------------
Whether the output is CORRECT. Per CLAUDE.md only trace replay can say that, and
traces exist for a handful of peripherals, not for a layout choice. This counts
shapes and sites; it makes no claim about behaviour.

ONE CORPUS NOW, AND STILL ONLY A DISCOVERY TIER
-----------------------------------------------
This used to run over two corpora and write two files, because the cut had 29
classes with a base -- too small a population for "zero collisions" to mean
anything, and it duly reported that base and derived field names never collide.
They do; the cut could not see it.

The cut is gone (docs/decisions/remove-the-cut.md), so there is one corpus:

    python3 scripts/inheritance_census.py
        -> docs/status/inheritance.json            the whole Renode tree

A wider corpus does not promote this above DISCOVERY. Counting shapes is not
validating output, and the tier line in the file says so.

`docs/status/inheritance-breadth.json` is kept as the exact artefact
docs/decisions/inheritance-layout.md cites; it is no longer regenerated, because
it would now be a byte-for-byte second copy of the file above.

Log:  ./tmp/logs/inheritance_census.log
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # for `emitter`
from emitter.core import snake  # noqa: E402  -- the emitter's own naming rule


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def split_symbol(symbol: str) -> tuple[str, str] | None:
    """A Roslyn display string -> (declaring type name, member name).

    Naive `rsplit('.')` is wrong here and quietly so: a symbol carries its
    parameter list, and a parameter type is itself dotted and may be generic --
    `Foo.Bar(Antmicro.Renode.Core.IMachine)` would yield a "member" of
    `Bar(Antmicro`. Cut the parameter list first, then split only on dots that
    are outside `<>`.
    """
    if not symbol:
        return None
    depth = 0
    cut = len(symbol)
    for i, ch in enumerate(symbol):
        if ch in "<[":
            depth += 1
        elif ch in ">]":
            depth -= 1
        elif ch == "(" and depth == 0:
            cut = i
            break
    head = symbol[:cut]
    parts: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in head:
        if ch in "<[":
            depth += 1
        elif ch in ">]":
            depth -= 1
        if ch == "." and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    if len(parts) < 2:
        return None
    # Strip generic arity from the declaring type: `SimpleContainer<T>` and
    # `SimpleContainer` are one type as far as the corpus's `type.name` goes.
    decl = parts[-2].split("<")[0].strip()
    return decl, parts[-1].split("<")[0].strip()


def extern_base_name(base_extern: str) -> str:
    """`Antmicro.Renode.Core.Structure.SimpleContainer<X>` -> `SimpleContainer`."""
    head = base_extern.split("<")[0]
    return head.rsplit(".", 1)[-1].strip()


class Census:
    def __init__(self, con: sqlite3.Connection, log: logging.Logger,
                 max_sites: int = 400):
        self.con = con
        self.log = log
        self.max_sites = max_sites
        self._storage_collisions: list[dict] | None = None
        self.types = {}          # id -> row dict
        self.by_name = {}        # name -> [ids]
        for tid, name, kind, base_id, base_extern, is_abstract in con.execute(
                "SELECT id, name, kind, base_type_id, base_extern, is_abstract "
                "FROM type ORDER BY id"):
            self.types[tid] = dict(id=tid, name=name, kind=kind,
                                   base_id=base_id,
                                   base_extern=base_extern or "",
                                   is_abstract=bool(is_abstract))
            self.by_name.setdefault(name, []).append(tid)

    # ---- 1. chains -----------------------------------------------------

    def chain(self, tid: int) -> tuple[list[int], str]:
        """(in-cut ancestor ids nearest first, name of the first base OUTSIDE
        the cut or "").

        The second value is the whole point: a chain that ends in an out-of-cut
        base is TRUNCATED, and neither merging nor embedding can supply members
        the corpus has never seen. Reporting only the in-cut depth would make
        the hierarchy look shallower than it is -- which is exactly what the
        `max depth 1` figure in the research doc turned out to be.
        """
        out: list[int] = []
        seen = {tid}
        cur = self.types[tid]
        while True:
            if cur["base_id"] and cur["base_id"] not in seen:
                seen.add(cur["base_id"])
                out.append(cur["base_id"])
                cur = self.types[cur["base_id"]]
                continue
            if cur["base_id"] and cur["base_id"] in seen:
                # A self-referential base edge. It exists: `PeripheralRegister`
                # and `RegisterField` each appear twice under one name (generic
                # and non-generic), and an id-keyed walk still terminates,
                # while the emitter's NAME-keyed walk would not distinguish
                # them at all. Recorded, not silently skipped.
                self.log.warning("cycle in base chain at %s (id %d)",
                                 cur["name"], cur["id"])
                return out, "<cycle>"
            return out, (extern_base_name(cur["base_extern"])
                         if cur["base_extern"] else "")

    # ---- members -------------------------------------------------------

    def members(self, tid: int, kinds: tuple[str, ...]) -> list[tuple[str, str]]:
        q = ",".join("?" for _ in kinds)
        return self.con.execute(
            f"SELECT name, kind FROM member WHERE type_id=? AND kind IN ({q}) "
            f"AND is_static=0 ORDER BY name", (tid, *kinds)).fetchall()

    def storage_members(self, tid: int) -> list[str]:
        """Instance members that actually STORE something -- the ones that
        become `State` fields. A computed property holds nothing, so it is not
        a layout question at all and counting it would inflate collisions."""
        return [n for (n,) in self.con.execute(
            "SELECT name FROM member WHERE type_id=? AND is_static=0 "
            "AND has_storage=1 AND kind IN ('field','property') ORDER BY name",
            (tid,))]

    # ---- 2. collisions --------------------------------------------------

    def storage_collisions(self) -> list[dict]:
        """The uncapped collision list, computed once. Consumers that ANALYSE
        it must use this; only the JSON section gets the capped copy."""
        if getattr(self, "_storage_collisions", None) is None:
            self.collisions()
        return self._storage_collisions

    def collisions(self) -> dict:
        raw: list[dict] = []
        for tid, t in self.types.items():
            if t["kind"] != "class":
                continue
            anc, _ = self.chain(tid)
            if not anc:
                continue
            # EVERY PAIR OF LEVELS, not just derived-against-each-ancestor.
            # Merging flattens the whole chain into ONE struct, so two
            # ancestors that share a name collide with each other even when the
            # derived type declares neither. Checking only against the derived
            # type missed three such names on `DMALDP` -- `length`, `name` and
            # `currentByteCount`, all declared by both `DMA_LD_ST_base` and
            # `Instruction` -- which the emitter does in fact emit twice.
            levels = [(t["name"], self.storage_members(tid))] + \
                     [(self.types[a]["name"], self.storage_members(a))
                      for a in anc]
            for i, (lname, lmembers) in enumerate(levels):
                by_snake: dict[str, list[str]] = {}
                for n in lmembers:
                    by_snake.setdefault(snake(n), []).append(n)
                for uname, umembers in levels[i + 1:]:
                    for bn in umembers:
                        for dn in by_snake.get(snake(bn), []):
                            raw.append(dict(
                                type=t["name"], lower=lname, upper=uname,
                                lower_member=dn, upper_member=bn,
                                same_csharp_name=(bn == dn)))
        # A method name declared on both levels is a different failure: it does
        # not lose storage, it makes the emitted FUNCTION name ambiguous, which
        # is the case `inheritance.qualified_call` already handles.
        method_raw: list[dict] = []
        for tid, t in self.types.items():
            if t["kind"] != "class":
                continue
            anc, _ = self.chain(tid)
            if not anc:
                continue
            own = {snake(n) for n, _ in self.members(tid, ("method",))}
            for a in anc:
                for bn, _ in self.members(a, ("method",)):
                    if snake(bn) in own:
                        method_raw.append(dict(derived=t["name"],
                                               base=self.types[a]["name"],
                                               member=bn))
        storage = dict(
            n=len(raw),
            n_types_affected=len({r["type"] for r in raw}),
            n_same_csharp_name=sum(1 for r in raw if r["same_csharp_name"]),
            n_only_after_snake_case=sum(
                1 for r in raw if not r["same_csharp_name"]),
        )
        # Storage collisions are the decision input and are always listed --
        # there are 77 of them tree-wide and each one names a type. Method-name
        # collisions are already handled by `qualified_call`, so their count is
        # the finding and 1,585 rows of it is noise.
        # Cached UNCAPPED, because two later sections work from this list. If
        # they read the capped copy they would quietly analyse a prefix, which
        # is the silent-loss failure this project keeps paying for.
        self._storage_collisions = sorted(
            raw, key=lambda r: (r["type"], r["upper_member"]))
        self._cap(storage, "sites", self._storage_collisions)
        method = dict(n=len(method_raw),
                      n_types_affected=len({r["derived"] for r in method_raw}))
        self._cap(method, "sites",
                  sorted(method_raw, key=lambda r: (r["derived"], r["member"])))
        return dict(storage=storage, method=method)

    # ---- 3. base access sites -------------------------------------------

    def base_access(self) -> dict:
        """Every operation in a derived type that names a member of an ancestor.

        Includes `base.X()`, an inherited non-virtual call through `this`, and a
        read or write of a protected base field. All three cost the same thing
        under each model -- MERGE reaches them as siblings, EMBED reaches them
        through the parent field -- so all three are counted.
        """
        rows = self.con.execute(
            "SELECT o.id, o.kind, o.symbol, o.detail, t.id, t.name, mb.name "
            "FROM operation o "
            "JOIN member mb ON mb.id = o.method_id "
            "JOIN type t ON t.id = mb.type_id "
            "WHERE o.symbol IS NOT NULL AND o.kind IN "
            "('Invocation','FieldReference','PropertyReference') "
            "ORDER BY o.id").fetchall()
        chain_names: dict[int, list[str]] = {}
        chain_extern: dict[int, str] = {}
        for tid in self.types:
            anc, ext = self.chain(tid)
            chain_names[tid] = [self.types[a]["name"] for a in anc]
            chain_extern[tid] = ext

        sites: list[dict] = []
        for oid, kind, symbol, detail, tid, tname, caller in rows:
            parsed = split_symbol(symbol)
            if parsed is None:
                continue
            decl, member = parsed
            if decl == tname:
                continue
            in_cut = decl in chain_names.get(tid, ())
            # An out-of-cut base is named only as a string on the type row, so
            # membership of the chain can be tested for exactly one level.
            out_of_cut = (not in_cut) and decl == chain_extern.get(tid, "")
            if not (in_cut or out_of_cut):
                continue
            virtual = None
            if detail:
                try:
                    virtual = json.loads(detail).get("virtual")
                except (ValueError, TypeError):
                    virtual = None
            # The derived type declaring the same name is what forces MERGE to
            # invent `{base}_{name}`; without it the plain name is free.
            shadowed = snake(member) in {
                snake(n) for n, _ in self.members(tid, ("method", "field",
                                                        "property"))}
            sites.append(dict(
                operation=oid, kind=kind, derived=tname, caller=caller,
                base=decl, member=member, base_in_cut=in_cut,
                is_virtual=virtual, shadowed_by_derived=shadowed))

        n = len(sites)
        shadowed = sum(1 for s in sites if s["shadowed_by_derived"])
        pairs: dict[str, int] = {}
        for s in sites:
            pairs[f"{s['derived']} -> {s['base']}"] = \
                pairs.get(f"{s['derived']} -> {s['base']}", 0) + 1
        out = dict(
            n=n,
            n_base_outside_cut=sum(1 for s in sites if not s["base_in_cut"]),
            by_kind={k: sum(1 for s in sites if s["kind"] == k)
                     for k in sorted({s["kind"] for s in sites})},
            # THE COST LINE. Under MERGE a site needs an invented qualified
            # name exactly when the derived type declares the same name;
            # otherwise the plain name works. Under EMBED every site needs the
            # parent hop and none needs an invented name.
            cost=dict(
                merge_invented_names=shadowed,
                merge_plain_names=n - shadowed,
                embed_parent_hops=n,
                embed_invented_names=0,
            ),
            by_pair=dict(sorted(pairs.items())),
        )
        return self._cap(out, "sites", sites)

    def _cap(self, out: dict, key: str, rows: list) -> dict:
        """Per-site detail, or a count saying it was dropped.

        A breadth run has thousands of sites and a committed status file has to
        stay readable. Dropping them silently would leave a file that looks
        like the whole picture, so the omission is recorded as a number.
        """
        if len(rows) <= self.max_sites:
            out[key] = rows
        else:
            out[key] = []
            out[f"{key}_omitted"] = len(rows)
            out[f"{key}_omitted_why"] = (
                f"more than --max-sites={self.max_sites}; aggregates above "
                f"carry the measurement, per-site rows are reproducible with "
                f"a higher cap")
        return out

    # ---- 5. what the emitter actually does with a collision ---------------

    def emitter_duplicates(self, db_path: Path) -> dict:
        """Run the REAL `state_fields` on every colliding type and see.

        The census above measures the C#. This measures the converter, and the
        two are not the same claim: `state_fields` drops handle types, elided
        types and anything with no Rust mapping, so a name that collides in the
        corpus may never reach the struct. Only this can say whether merging
        breaks today, and "it would break" is exactly the kind of assertion
        this project has been burned by. So it is executed, not argued.

        SINCE THE GUARD LANDED THIS MEASURES SOMETHING ELSE, and the file has to
        say so or a reader takes the new zero for the old question's answer.
        `state_fields` now WITHHOLDS every copy of a colliding name and reports
        a gap, so `n_types_with_duplicate_fields` is the count of collisions the
        guard MISSED and must stay 0. The population that used to be counted
        there is now `n_types_guarded`: types whose struct would not have
        compiled and which now name the collision instead.
        """
        try:
            import logging as _logging
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
            import emit as _emit
        except Exception as exc:                      # noqa: BLE001
            return dict(ran=False, why=f"could not import emit.py: {exc}")
        quiet = _logging.getLogger("inheritance_census.emit")
        quiet.addHandler(_logging.NullHandler())
        quiet.propagate = False
        con = sqlite3.connect(db_path)
        try:
            em = _emit.Emitter(con, quiet)
        except Exception as exc:                      # noqa: BLE001
            con.close()
            return dict(ran=False, why=f"emitter would not start: {exc}")
        rows: list[dict] = []
        for name in sorted({r["type"] for r in self.storage_collisions()}):
            em._sub_fields = {}
            try:
                fields, _gaps = em.state_fields(name)
            except Exception as exc:                  # noqa: BLE001
                rows.append(dict(type=name, error=f"{type(exc).__name__}: {exc}"))
                continue
            names = [n for n, _ in fields]
            dup = sorted({n for n in names if names.count(n) > 1})
            guarded = sorted(g for g in _gaps if "E0124" in g)
            if dup or guarded:
                rows.append(dict(type=name, duplicate_state_fields=dup,
                                 guarded=guarded))
        con.close()
        return dict(
            ran=True,
            what=("`state_fields` returning one name twice means the emitted "
                  "`struct State` declares the field twice, which is rustc "
                  "E0124 -- the type does not compile at all. Embedding cannot "
                  "produce this, because the base's members sit behind a field."),
            guard=("The emitter now withholds every copy of a colliding name "
                   "and reports the collision as a gap, so a duplicate should "
                   "no longer reach the struct. n_types_with_duplicate_fields "
                   "is therefore what the GUARD MISSED and must be 0; "
                   "n_types_guarded is the population it used to count. "
                   "scripts/check_inheritance.py asserts the guard fires."),
            n_types_with_duplicate_fields=len(
                [r for r in rows if r.get("duplicate_state_fields")]),
            n_duplicate_names=sum(len(r.get("duplicate_state_fields", ()))
                                  for r in rows),
            n_types_guarded=len([r for r in rows if r.get("guarded")]),
            n_guarded_names=sum(len(r.get("guarded", ())) for r in rows),
            detail=rows,
        )

    # ---- 6. does any of it reach the deliverable? -------------------------

    def cut_overlap(self, cut_db: Path) -> dict:
        """Which findings also land on a type present in a SECOND corpus.

        Kept as a general intersection against another database, because the
        question it answers is still real -- a collision on `LiteX_Framebuffer`
        and a collision on a type the workspace ships are different facts. With
        the cut removed there is no second corpus to pass by default, so this
        runs only when `--cut-db` is given, and answers nothing about tiers.
        """
        con = sqlite3.connect(cut_db)
        names = {n for (n,) in con.execute("SELECT DISTINCT name FROM type")}
        cfg = con.execute(
            "SELECT config FROM corpus_run ORDER BY id LIMIT 1").fetchone()[0]
        con.close()
        sites = self.storage_collisions()
        hits = sorted({s["type"] for s in sites} & names)
        return dict(
            against=cfg,
            n_colliding_types_in_that_corpus=len(hits),
            colliding_types_in_that_corpus=hits,
            sites=[s for s in sites if s["type"] in names],
        )

    def tier(self) -> str:
        """Which validated tier this file belongs to, stated IN the file.

        Always DISCOVERY, and the wider corpus did not change that. A census
        counts shapes that EXIST in real C#; the oracle is trace replay, and it
        reaches only the handful of peripherals with recorded traces. Saying so
        in the file is the point -- otherwise the next reader takes 24
        collisions for a validated fact about the output.
        """
        cfg = self.con.execute(
            "SELECT config FROM corpus_run ORDER BY id LIMIT 1").fetchone()[0]
        scratch = " Read from a SCRATCH health-check database." if cfg == "breadth" else ""
        return ("DISCOVERY. Whole-tree run: it shows which shapes EXIST in "
                "real C#. It cannot validate any translation -- traces cover a "
                "few peripherals, not this. Do not quote it as coverage."
                + scratch)

    # ---- 4. overrides ----------------------------------------------------

    def overrides(self) -> dict:
        row = self.con.execute(
            "SELECT SUM(is_virtual), SUM(is_abstract), SUM(is_override), "
            "COUNT(*) FROM method").fetchone()
        return dict(virtual=row[0] or 0, abstract=row[1] or 0,
                    override=row[2] or 0, methods=row[3] or 0)

    # ---- assemble --------------------------------------------------------

    def run(self, db_path: Path, cut_db: Path | None = None) -> dict:
        chains = []
        for tid, t in sorted(self.types.items(), key=lambda kv: kv[1]["name"]):
            if t["kind"] != "class":
                continue
            anc, ext = self.chain(tid)
            if not anc and not ext:
                continue
            chains.append(dict(
                type=t["name"],
                in_cut_ancestors=[self.types[a]["name"] for a in anc],
                in_cut_depth=len(anc),
                truncated_at=ext,
                base_fields_visible=sum(len(self.storage_members(a))
                                        for a in anc),
            ))
        n_classes = sum(1 for t in self.types.values() if t["kind"] == "class")
        truncated = [c for c in chains if c["truncated_at"]]
        # THE DUPLICATION SHAPE. Merging copies a base's members into every
        # derived type, so the cost is O(base members x derived count) and the
        # number that matters is the fan-out, not today's line count. Embedding
        # names the base once however many derive from it.
        fanout: dict[str, int] = {}
        for c in chains:
            for a in c["in_cut_ancestors"]:
                fanout[a] = fanout.get(a, 0) + 1
        base_size = {}
        for name, ids in self.by_name.items():
            if name in fanout:
                base_size[name] = max(len(self.storage_members(i)) for i in ids)
        duplication = sorted(
            ({"base": b, "derived_count": n,
              "storage_members": base_size.get(b, 0),
              "member_copies_under_merge": n * base_size.get(b, 0)}
             for b, n in fanout.items()),
            key=lambda r: (-r["member_copies_under_merge"], r["base"]))
        chains_block = dict(
            n_with_a_base=len(chains),
            n_truncated_by_the_cut=len(truncated),
            max_in_cut_depth=max((c["in_cut_depth"] for c in chains),
                                 default=0),
            depth_histogram={
                str(d): sum(1 for c in chains if c["in_cut_depth"] == d)
                for d in sorted({c["in_cut_depth"] for c in chains})},
            duplication=dict(
                total_member_copies_under_merge=sum(
                    r["member_copies_under_merge"] for r in duplication),
                distinct_base_members=sum(base_size.get(b, 0) for b in fanout),
                worst=duplication[:20],
            ),
        )
        self._cap(chains_block, "detail", chains)
        return dict(
            note=("GENERATED by scripts/inheritance_census.py. Do not hand-edit "
                  "and do not retype these numbers into prose -- "
                  "docs/decisions/ reads this file."),
            tier=self.tier(),
            corpus=dict(
                run=self.con.execute(
                    "SELECT config FROM corpus_run ORDER BY id LIMIT 1"
                ).fetchone()[0],
                renode_commit=self.con.execute(
                    "SELECT renode_commit FROM corpus_run ORDER BY id LIMIT 1"
                ).fetchone()[0],
                classes=n_classes,
                types=len(self.types),
            ),
            chains=chains_block,
            collisions=self.collisions(),
            emitter_duplicates=self.emitter_duplicates(db_path),
            cut_overlap=(self.cut_overlap(cut_db) if cut_db
                         else dict(ran=False, why="no --cut-db given")),
            base_access=self.base_access(),
            overrides=self.overrides(),
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rulesdb/patterns.db")
    ap.add_argument("--out", default="docs/status/inheritance.json")
    ap.add_argument("--max-sites", type=int, default=400,
                    help="per-site rows above this are replaced by a count")
    ap.add_argument("--cut-db", default=None,
                    help="second corpus to intersect findings against, so a "
                         "finding somewhere in Renode can be told from one on "
                         "a type this workspace ships. No default: the corpus "
                         "cut that used to supply it is gone")
    args = ap.parse_args()

    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("inheritance_census")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "inheritance_census.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    db = root / args.db
    if not db.exists():
        log.error("no corpus at %s -- the database is gitignored; ingest first",
                  args.db)
        return 1
    con = sqlite3.connect(db)
    cut_db = (root / args.cut_db) if args.cut_db else None
    if cut_db is not None and not cut_db.exists():
        log.error("no corpus at %s for --cut-db", args.cut_db)
        return 1
    data = Census(con, log, max_sites=args.max_sites).run(db, cut_db)
    con.close()
    data["produced_by"] = (
        f"python3 scripts/inheritance_census.py --db {args.db} "
        f"--out {args.out} --max-sites {args.max_sites}"
        + (f" --cut-db {args.cut_db}" if args.cut_db else ""))

    out = root / args.out
    out.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")

    c = data["chains"]
    col = data["collisions"]
    ba = data["base_access"]
    log.info("cut=%s  %d classes", data["corpus"]["run"], data["corpus"]["classes"])
    log.info("chains: %d with a base, %d truncated by the cut, max in-cut depth %d",
             c["n_with_a_base"], c["n_truncated_by_the_cut"], c["max_in_cut_depth"])
    log.info("collisions: %d storage-member over %d type(s) (%d same C# name, "
             "%d only after snake_case), %d method-name",
             col["storage"]["n"], col["storage"]["n_types_affected"],
             col["storage"]["n_same_csharp_name"],
             col["storage"]["n_only_after_snake_case"], col["method"]["n"])
    ed = data["emitter_duplicates"]
    if ed.get("ran"):
        log.info("emitter: %d type(s) emit a DUPLICATE State field today "
                 "(%d names) -- rustc E0124",
                 ed["n_types_with_duplicate_fields"], ed["n_duplicate_names"])
    else:
        log.warning("emitter cross-check skipped: %s", ed.get("why"))
    ov = data["cut_overlap"]
    if ov.get("against"):
        log.info("of those colliding types, %d also exist in the '%s' corpus: %s",
                 ov["n_colliding_types_in_that_corpus"], ov["against"],
                 ", ".join(ov["colliding_types_in_that_corpus"]) or "(none)")
    log.info("base access: %d site(s), %d onto a base outside the cut",
             ba["n"], ba["n_base_outside_cut"])
    log.info("  merge: %d invented `{base}_{name}`, %d plain",
             ba["cost"]["merge_invented_names"], ba["cost"]["merge_plain_names"])
    log.info("  embed: %d parent hops, %d invented names",
             ba["cost"]["embed_parent_hops"], ba["cost"]["embed_invented_names"])
    log.info("wrote %s", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

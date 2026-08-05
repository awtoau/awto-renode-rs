#!/usr/bin/env python3
"""Can the converter emit a dispatch trait today? Answered by compiling one.

Issue #56 turns on a claim that was recorded as verified: an additive dispatch
trait works across peripherals with different `State` types, in ~60-90 lines,
changing no existing generated line. That claim was checked with HAND-WRITTEN
Rust. This checks it with CONVERTER OUTPUT, which is a different question and
gets a different answer.

WHAT IT DOES
------------
1. Asks the corpus which dispatch trait is even available (`--report`).
2. Generates the trait, a receiver type per implementing peripheral, and the
   impls -- all from the corpus, no hand-written Rust.
3. Writes a scratch crate under `tmp/dispatch_spike/` and COMPILES it, with a
   test that puts two peripherals whose `State` types differ into one
   `Vec<Rc<RefCell<dyn _>>>` and calls through the trait.

Nothing under `src/` is touched. `scripts/check_refactor.py` stays green,
which is the point: this measures what a change WOULD cost before anyone pays
it.

WHAT IT FOUND, AND WHY THE SPIKE IS NOT A LANDING
-------------------------------------------------
Two blockers, both facts about the corpus and the emitted shape rather than
opinions about trait design. Both are printed by `--report` so they stay true
as the corpus moves:

  * THE INTERFACE IS NOT IN THE CUT. Dispatch in the C# goes through
    `IDoubleWordPeripheral`, and `type_implements.interface_id` is NULL for
    every interface the cut's peripherals declare bar one. A trait declared
    with methods chosen by hand would be exactly the thing CLAUDE.md forbids --
    a hand-written file wearing a rule's name. The spike therefore derives the
    trait from an in-cut BASE CLASS's virtual members, which is a general rule
    and available today, and says so rather than pretending it emitted the
    interface.

  * THE FORWARDING TARGET IS PRIVATE. Emitted methods are `fn`, not `pub fn`,
    so no sibling module can call them, and no generated type owns the bank and
    the state together. The receiver in the original hand-checked sketch was
    `Stm32Uart` from the HAND-WRITTEN `uart.rs`, which exists for two of the
    seven modules and is not converter output. The spike patches the
    declaration template at runtime to make them public and reports how many
    lines that moves -- it does not commit the change.

Run:   python3 scripts/dispatch_spike.py --report     # corpus facts only
       python3 scripts/dispatch_spike.py              # generate and compile
Out:   docs/status/dispatch.json
Log:   ./tmp/logs/dispatch_spike.log
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "core"))
from emitter.core import snake  # noqa: E402

# The seven modules the converter owns, as (type, method, module). Same list
# check_generated.py drives -- imported rather than retyped so the two cannot
# drift apart.
from check_generated import GENERATED  # noqa: E402


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def targets() -> list[tuple[str, str, str]]:
    """(C# type, method, rust module) for every generated peripheral."""
    out = []
    for path, argv in GENERATED:
        args = dict(zip(argv[1::2], argv[2::2]))
        out.append((args["--type"], args["--method"], args["--file"]))
    return out


# --------------------------------------------------------------------------
# 1. What the corpus can supply
# --------------------------------------------------------------------------

def interface_availability(con: sqlite3.Connection) -> dict:
    """Which interfaces the peripherals declare, and which are in the cut.

    `interface_id` is the whole answer: it is set when the interface itself was
    ingested and NULL when it was not. A trait cannot be generated from a name.
    """
    rows = con.execute(
        "SELECT t.name, ti.interface_name, ti.interface_id "
        "FROM type_implements ti JOIN type t ON t.id = ti.type_id "
        "ORDER BY t.name, ti.interface_name").fetchall()
    declared = [dict(type=t, interface=i.split("<")[0].rsplit(".", 1)[-1],
                     in_cut=iid is not None)
                for t, i, iid in rows]
    return dict(
        n_declarations=len(declared),
        n_resolvable=sum(1 for d in declared if d["in_cut"]),
        n_unresolvable=sum(1 for d in declared if not d["in_cut"]),
        why=("An interface whose id is NULL was never ingested, so its members "
             "are unknown and no trait can be derived from it. This is the "
             "supertrait-closure blocker: `IDoubleWordPeripheral` -- the "
             "interface the system bus dispatches through -- is one of them."),
        declarations=declared,
    )


def dispatch_bases(con: sqlite3.Connection) -> list[dict]:
    """In-cut base classes with virtual members: the trait sources available.

    THE GENERAL RULE, stated so it is checkable: a class that (a) is inside the
    corpus, (b) has at least one type deriving from it inside the corpus, and
    (c) declares virtual or abstract members, defines a dispatch contract. That
    is true of any C# corpus and needs no interface to be present.
    """
    out = []
    for tid, name in con.execute(
            "SELECT id, name FROM type WHERE kind='class' ORDER BY name"):
        derived = [n for (n,) in con.execute(
            "SELECT name FROM type WHERE base_type_id=? ORDER BY name", (tid,))]
        if not derived:
            continue
        members = con.execute(
            "SELECT mb.name, m.return_type, m.member_id FROM member mb "
            "JOIN method m ON m.member_id = mb.id "
            "WHERE mb.type_id=? AND (m.is_virtual=1 OR m.is_abstract=1) "
            "AND mb.accessibility='public' ORDER BY mb.name", (tid,)).fetchall()
        if not members:
            continue
        out.append(dict(base=name, derived=derived,
                        n_derived=len(derived),
                        members=[dict(name=n, returns=r, member_id=i)
                                 for n, r, i in members]))
    return out


def entry_points(root: Path) -> dict:
    """Under what NAME each generated module exposes each contract method.

    This is the instability the research doc named: the base copy is renamed
    `{base}_{name}` when the derived type DECLARES the same name, whether or
    not that derived method survives to be emitted. So the same C# method
    reaches Rust under two different names depending on a property of a
    different class, and nothing generic can call it.
    """
    per_module: dict[str, list[str]] = {}
    for _t, _m, mod in targets():
        text = (root / "src" / "renode-stm32" / "src" / f"{mod}.rs").read_text()
        per_module[mod] = sorted(
            re.findall(r"^(?:pub )?fn ([a-z_][a-z0-9_]*)\(", text, re.M))
    contracts = ("reset", "read_double_word", "write_double_word")
    names: dict[str, dict[str, str | None]] = {}
    for mod, fns in per_module.items():
        row: dict[str, str | None] = {}
        for c in contracts:
            if c in fns:
                row[c] = c
            else:
                qualified = [f for f in fns if f.endswith("_" + c)]
                row[c] = qualified[0] if qualified else None
        names[mod] = row
    distinct = {c: sorted({v[c] for v in names.values() if v[c]})
                for c in contracts}
    return dict(
        per_module=names,
        distinct_names_per_contract=distinct,
        n_modules_missing_reset=sum(1 for v in names.values()
                                    if v["reset"] is None),
        why=("A generic caller needs ONE name per contract. `reset` arrives "
             "under two, and is absent from some modules entirely."),
    )


def visibility_cost(root: Path) -> dict:
    """How many committed lines a `pub fn` change would move, exactly.

    Stated as a number because "it is only a keyword" and "it changes every
    file" are both true and only one of them is a decision input.
    """
    per_file = {}
    for _t, _m, mod in targets():
        p = root / "src" / "renode-stm32" / "src" / f"{mod}.rs"
        text = p.read_text()
        per_file[f"{mod}.rs"] = len(re.findall(r"^fn [a-z_]", text, re.M))
    return dict(
        lines_that_would_change=sum(per_file.values()),
        per_file=per_file,
        why=("Every emitted method is `fn`, private to its module. A trait "
             "impl in any other module cannot call one. Making them public is "
             "a one-token, behaviour-free edit -- and it moves this many "
             "committed lines, so it is not additive and check_refactor would "
             "go red."),
    )


# --------------------------------------------------------------------------
# 2. Generate the trait, the receivers and the impls
# --------------------------------------------------------------------------

TRAIT_RULES_DEFAULT = {
    "trait_decl": "pub trait {name} {{",
    "trait_method": "    fn {name}(&mut self{extra}) -> {ret};",
    "impl_decl": "impl {trait} for {ty} {{",
    "impl_method": "    fn {name}(&mut self{extra}) -> {ret} {{",
    "impl_forward": "        {module}::{target}(&self.bank, &mut self.st{args})",
    "receiver": ("pub struct {ty} {{\n"
                 "    pub bank: Bank<{module}::State>,\n"
                 "    pub f: {module}::Fields,\n"
                 "    pub st: {module}::State,\n"
                 "}}"),
}


class Spike:
    def __init__(self, root: Path, con: sqlite3.Connection,
                 log: logging.Logger):
        self.root = root
        self.con = con
        self.log = log
        self.rules = TRAIT_RULES_DEFAULT

    def rust_type(self, cs: str, em) -> str | None:
        return em.rust_type(cs or "")

    def build(self, em) -> tuple[str, dict]:
        """The dispatch module, as one string, plus what was withheld."""
        bases = [b for b in dispatch_bases(self.con)]
        mods = {t: m for t, _mm, m in targets()}
        # The base with the most in-cut derived types that actually have a
        # generated module. Chosen by COUNT rather than by name: naming it
        # would bake this corpus into the tool.
        best = None
        for b in bases:
            covered = [d for d in b["derived"] if d in mods]
            if best is None or len(covered) > len(best[1]):
                best = (b, covered)
        if best is None or not best[1]:
            return "", dict(withheld="no in-cut base class has a generated "
                                     "derived module")
        base, covered = best
        tname = base["base"]

        withheld: list[str] = []
        methods: list[dict] = []
        for m in base["members"]:
            ret_cs = m["returns"] or "void"
            ret = "()" if ret_cs == "void" else self.rust_type(ret_cs, em)
            if ret is None:
                withheld.append(f"{tname}.{m['name']}: return type "
                                f"`{ret_cs}` has no Rust mapping")
                continue
            params = []
            bad = False
            for pname, ptype in self.con.execute(
                    "SELECT name, type FROM parameter WHERE method_id=? "
                    "ORDER BY ordinal", (m["member_id"],)):
                prt = self.rust_type(ptype, em)
                if prt is None:
                    withheld.append(f"{tname}.{m['name']}: parameter "
                                    f"`{pname}: {ptype}` has no Rust mapping")
                    bad = True
                    break
                params.append((snake(pname), prt))
            if bad:
                continue
            methods.append(dict(name=snake(m["name"]), ret=ret, params=params))
        if not methods:
            return "", dict(withheld="; ".join(withheld) or "no typed members")

        # WHICH CONTRACT MEMBERS EVERY IMPLEMENTOR CAN ACTUALLY SUPPLY.
        # A trait method has to be implemented by every implementor, so one
        # base member that no module emits removes the method from the trait --
        # it cannot be stubbed, because a stub that returns a default is the
        # `-> ()` fallback bug in the protocol doc wearing a trait's clothes.
        #
        # This is the sharpest cost the spike found and it is not an argument
        # about traits: `OffsetToString` reads `mapper`, an unmapped base
        # field, so it is withheld from all six derived modules, and one
        # untranslatable base member therefore shrinks the contract for every
        # peripheral at once.
        exports: dict[str, set[str]] = {}
        for d in covered:
            text = (self.root / "src" / "renode-stm32" / "src"
                    / f"{mods[d]}.rs").read_text()
            exports[d] = set(re.findall(
                r"^(?:pub )?fn ([a-z_][a-z0-9_]*)\(", text, re.M))

        # Which derived types DECLARE each contract member. This is the fact
        # that makes resolution strict, and it has to come from the corpus:
        # the file cannot say whether a missing `reset` means "not overridden"
        # or "overridden and withheld", and those need opposite answers.
        declares: dict[tuple[str, str], bool] = {}
        for d in covered:
            own = {snake(n) for (n,) in self.con.execute(
                "SELECT mb.name FROM member mb JOIN type t ON t.id=mb.type_id "
                "WHERE t.name=? AND mb.kind='method'", (d,))}
            for m in base["members"]:
                declares[(d, snake(m["name"]))] = snake(m["name"]) in own

        def resolve(d: str, name: str) -> str | None:
            """The fn this type's trait method must forward to, or None.

            STRICT ON PURPOSE, and this is the spike's sharpest result. The
            obvious resolver tries the plain name and falls back to the base
            copy `{base}_{name}`. Run that way it produced an impl for all four
            peripherals -- and three of them forwarded `reset` to
            `basic_double_word_peripheral_reset`, the BASE's body, when the C#
            overrides `Reset` and the override had been withheld. Virtual
            dispatch would have called the wrong method, in code that compiles
            and passes its trace, which is failure mode #1 in
            docs/agents/transpiler-work-protocol.md arriving by a new route.

            The correct rule falls out of how the emitter names things, and it
            is simpler than the fallback: the base copy takes the PLAIN name
            unless the derived type declares that name too, in which case it is
            qualified and the plain name belongs to the override. So the plain
            name is always the dispatch target, and `{base}_{name}` is exactly
            the set of bodies that must NEVER be dispatched to -- it is what
            `base.X()` calls, not what the vtable calls.
            """
            _ = declares  # kept: it is what makes the sentence above checkable
            return name if name in exports[d] else None

        keep = []
        for m in methods:
            absent = [d for d in covered if resolve(d, m["name"]) is None]
            if absent:
                overridden = [d for d in absent
                              if declares.get((d, m["name"]))]
                why = ("their override is withheld, and forwarding to the "
                       "base body instead would dispatch to the wrong method"
                       if overridden else "no implementor emits it")
                withheld.append(
                    f"{tname}.{m['name']}: not in the trait -- "
                    f"{len(absent)} of {len(covered)} implementor(s) cannot "
                    f"supply it ({', '.join(sorted(absent))}); {why}")
                continue
            keep.append(m)
        methods = keep
        if not methods:
            return "", dict(withheld=sorted(set(withheld)))

        L: list[str] = []
        a = L.append
        a("//! GENERATED dispatch spike -- NOT a committed artefact.")
        a("//!")
        a(f"//! Trait derived from the in-cut base class `{tname}`, whose "
          f"virtual")
        a(f"//! members are the dispatch contract. {len(covered)} in-cut "
          f"type(s) implement it.")
        if withheld:
            a("//!")
            a("//! WITHHELD:")
            for w in sorted(set(withheld)):
                a(f"//!   - {w}")
        a("")
        a("use renode_regs::Bank;")
        for mod in sorted(mods[d] for d in covered):
            a(f"use crate::{mod};")
        a("")
        a(self.rules["trait_decl"].format(name=tname))
        for m in methods:
            extra = "".join(f", {n}: {t}" for n, t in m["params"])
            a(self.rules["trait_method"].format(name=m["name"], extra=extra,
                                                ret=m["ret"]))
        a("}")
        a("")

        impls = []
        for d in sorted(covered):
            mod = mods[d]
            ty = "".join(p.capitalize() for p in mod.split("_")
                         if p != "registers")
            # The base copy may live under `{base}_{name}`; resolve to what the
            # module ACTUALLY exports rather than to what it should. This is
            # the per-file rename table arriving by the back door, and the
            # trait is where it becomes visible.
            resolved = {m["name"]: resolve(d, m["name"]) for m in methods}
            a(self.rules["receiver"].format(ty=ty, module=mod))
            a("")
            a(f"impl {ty} {{")
            a("    pub fn new() -> Self {")
            a(f"        let mut bank: Bank<{mod}::State> = Bank::new();")
            a(f"        let mut f = {mod}::Fields::default();")
            a(f"        {mod}::define_registers(&mut bank, &mut f);")
            a(f"        Self {{ bank, f, st: {mod}::State::default() }}")
            a("    }")
            a("}")
            a("")
            a(self.rules["impl_decl"].format(trait=tname, ty=ty))
            for m in methods:
                extra = "".join(f", {n}: {t}" for n, t in m["params"])
                args = "".join(f", {n}" for n, _ in m["params"])
                a(self.rules["impl_method"].format(name=m["name"], extra=extra,
                                                   ret=m["ret"]))
                a(self.rules["impl_forward"].format(
                    module=mod, target=resolved[m["name"]], args=args))
                a("    }")
            a("}")
            a("")
            impls.append(dict(type=d, module=mod, rust_type=ty,
                              forwards=resolved))
        first = methods[0]
        call = first["name"] + "(" + ", ".join(
            "0" if t in ("i64", "u32", "u64", "i32", "usize") else
            "Default::default()" for _n, t in first["params"]) + ")"
        return "\n".join(L).rstrip() + "\n", dict(
            trait=tname, methods=[m["name"] for m in methods],
            call_for_test=call, impls=impls, withheld=sorted(set(withheld)))


# --------------------------------------------------------------------------
# 3. Compile it
# --------------------------------------------------------------------------

def compile_spike(root: Path, dispatch_src: str, modules: dict[str, str],
                  info: dict, log: logging.Logger) -> dict:
    """A scratch crate under tmp/, compiled for real.

    "It compiles" is explicitly NOT evidence of correctness in this project, and
    is not offered as such. What compiling proves here is exactly one thing the
    decision needs: that a `dyn` trait over peripherals with DIFFERENT `State`
    types is well-formed Rust. That is a language question, and rustc is the
    only authority on it.
    """
    out = root / "tmp" / "dispatch_spike"
    if out.exists():
        shutil.rmtree(out)
        (out / "src").mkdir(parents=True)
    (out / "src").mkdir(parents=True, exist_ok=True)
    (out / "Cargo.toml").write_text(
        "[package]\nname = \"dispatch-spike\"\nversion = \"0.0.0\"\n"
        "edition = \"2021\"\npublish = false\n\n[workspace]\n\n"
        "[dependencies]\n"
        "renode-regs = { path = \"../../src/renode-regs\" }\n"
        "csharp-rt = { path = \"../../src/csharp-rt\" }\n"
        "log = \"0.4\"\n")
    lib = ["//! Scratch crate. Regenerate with scripts/dispatch_spike.py.",
           "#![allow(dead_code, unused_imports, unused_variables, "
           "non_camel_case_types, non_upper_case_globals)]", ""]
    for mod, text in sorted(modules.items()):
        (out / "src" / f"{mod}.rs").write_text(text)
        lib.append(f"pub mod {mod};")
    (out / "src" / "dispatch.rs").write_text(dispatch_src)
    lib.append("pub mod dispatch;")
    lib.append("")
    # THE CLAIM UNDER TEST, written as a test rather than as prose: a
    # heterogeneous collection behind one trait object, over D1's Rc<RefCell<_>>.
    tys = [i["rust_type"] for i in info.get("impls", [])]
    if len(tys) >= 2 and info.get("methods"):
        trait = info["trait"]
        # Call the first contract method that takes only the offset, so the
        # test exercises real dispatch rather than a no-argument stub.
        call = info["call_for_test"]
        lib += [
            "#[cfg(test)]",
            "mod heterogeneous {",
            "    use super::dispatch::*;",
            "    use std::cell::RefCell;",
            "    use std::rc::Rc;",
            "",
            "    /// The claim issue #56 turns on: ONE trait object over "
            "peripherals",
            "    /// whose `State` types differ, with the flattened state and "
            "the",
            "    /// free-fn bodies left exactly as they are.",
            "    #[test]",
            "    fn different_state_types_share_one_trait_object() {",
            f"        let bus: Vec<Rc<RefCell<dyn {trait}>>> = vec![",
        ]
        for t in tys[:4]:
            lib.append(f"            Rc::new(RefCell::new({t}::new())),")
        lib += [
            "        ];",
            "        for p in &bus {",
            f"            let _ = p.borrow_mut().{call};",
            "        }",
            f"        assert_eq!(bus.len(), {min(len(tys), 4)});",
            "    }",
            "}",
        ]
    (out / "src" / "lib.rs").write_text("\n".join(lib) + "\n")

    r = subprocess.run(["cargo", "test", "--manifest-path",
                        str(out / "Cargo.toml")],
                       capture_output=True, text=True)
    (root / "tmp" / "logs" / "dispatch_spike_cargo.log").write_text(
        r.stdout + r.stderr)
    errors = re.findall(r"^error(\[E\d+\])?:", r.stderr, re.M)
    passed = re.search(r"test result: ok\. (\d+) passed", r.stdout)
    return dict(
        compiled=(r.returncode == 0),
        n_errors=len(errors),
        tests_passed=int(passed.group(1)) if passed else 0,
        crate="tmp/dispatch_spike",
        cargo_log="tmp/logs/dispatch_spike_cargo.log",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rulesdb/patterns.db")
    ap.add_argument("--out", default="docs/status/dispatch.json")
    ap.add_argument("--report", action="store_true",
                    help="corpus facts only; generate and compile nothing")
    args = ap.parse_args()

    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("dispatch_spike")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "dispatch_spike.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    db = root / args.db
    if not db.exists():
        log.error("no corpus at %s -- it is gitignored; ingest first", args.db)
        return 1
    con = sqlite3.connect(db)

    data = dict(
        note=("GENERATED by scripts/dispatch_spike.py. Numbers here are read "
              "by docs/decisions/; do not retype them into prose."),
        interfaces=interface_availability(con),
        dispatch_bases=dispatch_bases(con),
        entry_points=entry_points(root),
        visibility=visibility_cost(root),
    )

    iface = data["interfaces"]
    log.info("interfaces: %d declaration(s), %d resolvable in the cut, "
             "%d not", iface["n_declarations"], iface["n_resolvable"],
             iface["n_unresolvable"])
    log.info("dispatch bases available in the cut: %s",
             ", ".join(f"{b['base']} ({b['n_derived']} derived)"
                       for b in data["dispatch_bases"]) or "(none)")
    ep = data["entry_points"]
    for c, names in ep["distinct_names_per_contract"].items():
        log.info("  contract `%s` is exported under %d name(s): %s",
                 c, len(names), ", ".join(names))
    log.info("visibility: %d committed line(s) would change to `pub fn`",
             data["visibility"]["lines_that_would_change"])

    if not args.report:
        import csharp_emitter as _emit
        quiet = logging.getLogger("dispatch_spike.emit")
        quiet.addHandler(logging.NullHandler())
        quiet.propagate = False
        em = _emit.Emitter(con, quiet)
        # The one change the spike needs and does NOT commit: make emitted
        # methods callable from outside their module. Patched in memory, on the
        # rule that owns the declaration, so the committed rules are untouched.
        em.project.setdefault("peripheral_methods", {})["decl"] = (
            "pub fn {name}(bank: &Bank<State>, st: &mut State{extra}) -> {ret}")
        modules = {}
        for tname, mname, mod in targets():
            modules[mod] = em.emit_file(tname, mname, mod)
        spike = Spike(root, con, log)
        src, info = spike.build(em)
        if not src:
            log.error("no dispatch module could be generated: %s",
                      info.get("withheld"))
            data["spike"] = dict(generated=False, **info)
        else:
            (root / "tmp" / "dispatch.rs").write_text(src)
            result = compile_spike(root, src, modules, info, log)
            data["spike"] = dict(generated=True, lines=len(src.splitlines()),
                                 **info, **result)
            log.info("spike: trait `%s` over %d impl(s), %d line(s)",
                     info["trait"], len(info["impls"]), len(src.splitlines()))
            for w in info["withheld"]:
                log.info("  withheld: %s", w)
            log.info("spike: compiled=%s errors=%d tests_passed=%d (see %s)",
                     result["compiled"], result["n_errors"],
                     result["tests_passed"], result["cargo_log"])
    con.close()

    (root / args.out).write_text(json.dumps(data, indent=2) + "\n")
    log.info("wrote %s", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

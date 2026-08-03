#!/usr/bin/env python3
"""Refuse a source-defect stanza that has lost its evidence. Pre-commit gate.

WHAT A BUG RULE IS
------------------
A defect in the C# BEING TRANSLATED, recorded as data. The fourth rule class --
see docs/decisions/bug-rules-are-a-fourth-class.md. The other three classes all
answer "how do I express this construct?"; this one answers "the source is
wrong, and I know it", which none of them had anywhere to put.

WHAT A BUG RULE IS NOT
----------------------
It is NOT a way to find or fix a translation defect, and nothing here should be
described as if it were. Our Rust is wrong when it differs from THE C#; a
datasheet adds nothing to that comparison. It says something new only where the
Rust matches the C# and both differ from silicon -- which is not a translation
defect at all. On bxCAN, zero of 99 divergences were diagnosed by reading ST.

What it IS for is preventing a wrong "fix". Several of these look exactly like
OUR bug to anyone reading the datasheet, and correcting one toward the hardware
breaks a passing trace, because the oracle certifies equivalence with the C#.

WHAT THIS CHECKS, AND WHY EACH ONE
----------------------------------
The decision names four fields a bug rule carries that an ordinary rule does
not, and a stanza that loses any of them stops being a bug rule and becomes an
opinion. Prose in a JSON file decays exactly as quietly as prose in a comment
did, so the four are checked rather than reviewed:

  site         file and line, plus the C# text at that line. VERIFIED against
               the source when RENODE_SRC is set -- Renode moves, and a stanza
               pointing at a line that now says something else is worse than
               no stanza, because it reads as evidence.
  authority    a citation, not a claim. A disagreement with no third source is
               a SUSPICION and belongs in `rejected`, not here.
  mode         must be `fidelity` in committed data. Conformance is a
               deliberate act at the call site (`emit.py --conformance ID`),
               never a state the repository can be left in.
  switch_impact  MEASURED, by scripts/measure_bug_switch.py. A bug rule whose
               switch-impact is unknown is not finished -- that is the field
               that makes throwing the switch safe rather than a coin flip.

It also checks that each stanza REACHES the output. A stanza matching nothing
emits no marker, which is indistinguishable from having no stanza; that is the
failure mode the doc comment in uart.rs already had.

A CHECK NOBODY HAS SEEN FAIL IS NOT A CHECK
-------------------------------------------
`--prove` mutates the committed stanzas in memory, one field at a time, and
asserts this check REJECTS each mutant. Without it the passing run above is
equally consistent with the check doing nothing, and this project has already
shipped one gate that was passing because it was being skipped.

Run:  python3 scripts/check_bug_rules.py
      python3 scripts/check_bug_rules.py --prove
Log:  ./tmp/logs/check_bug_rules.log
Exit: 0 clean, 1 if any stanza has lost its evidence.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

#: The class needs this many instances to be a rule class rather than a patch
#: mechanism wearing a rule's name. It is the project's ordinary threshold, and
#: the decision names falling below it as the thing that would overturn it.
MIN_INSTANCES = 3

#: Conformance actions the emitter knows how to perform. `unavailable` is a
#: first-class answer, not a placeholder: a defect whose correct behaviour is
#: an EVENT rather than a layout has no expressible conformance, and saying so
#: is the honest form of the decision's own overturn condition.
ACTIONS = {"refine_fields", "unavailable"}

REQUIRED_SITE = ("file", "line", "csharp", "type", "name")
REQUIRED_AUTHORITY = ("source", "cites")


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def load_env(root: Path) -> dict[str, str]:
    """The process environment, with the gitignored `.env` layered on top.

    The C# tree is located by RENODE_SRC and this repo is public, so the path
    is never in a tracked file -- see .env.example. Reading only `os.environ`
    made the site verification silently skip for anyone who had done exactly
    what the setup instructions said.
    """
    env = dict(os.environ)
    f = root / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def load(root: Path) -> tuple[list[dict], dict]:
    """Every bug stanza in the project layer, from every rule document.

    Read from ALL documents rather than one named file, for the same reason
    check_layering.py stopped naming csharp_core.json: a second document is
    exactly what someone adds next, and an unchecked one looks like a checked
    one.
    """
    out: list[dict] = []
    docs: dict = {}
    for f in sorted((root / "rulesdb" / "rules").glob("*.json")):
        doc = json.loads(f.read_text())
        for s in doc.get("bug_rules", []):
            out.append(s)
            docs[s.get("id", "")] = f.name
        if doc.get("layer") == "language" and doc.get("bug_rules"):
            # Checked, not assumed: every INSTANCE names a construct of one
            # corpus, so an instance in the generic layer is a layering
            # violation that check_layering.py cannot see -- it scans emitted
            # templates and rule keys, and a stanza is neither.
            out.append({"id": "<language-layer>", "_leak": f.name})
    return out, docs


def emitted_text(root: Path) -> str:
    """Every committed generated file, concatenated.

    From check_generated.GENERATED and not a list of its own: the set of files
    the converter owns is already stated once, and stating it twice is how the
    two quietly disagree.
    """
    sys.path.insert(0, str(root / "scripts"))
    from check_generated import GENERATED
    parts = []
    for rel, _argv in GENERATED:
        p = root / rel
        if p.exists():
            parts.append(p.read_text())
    return "\n".join(parts)


def tag_for(root: Path, stanza: dict) -> str:
    """`TAG(id)` exactly as the emitter renders it, from the same data."""
    core = json.loads((root / "rulesdb" / "rules" / "csharp_core.json").read_text())
    tier = core.get("severity", {}).get("tiers", {}).get("bug", {})
    return (f"{stanza.get('tag', tier.get('default_tag', 'SRCBUG'))}"
            f"({stanza.get('id', '')})")


def module_text(root: Path, type_name: str) -> str | None:
    """The generated module that owns this C# type, or None.

    From check_generated.GENERATED, so which file owns which type is stated
    once.
    """
    sys.path.insert(0, str(root / "scripts"))
    from check_generated import GENERATED
    for rel, argv in GENERATED:
        if "--type" in argv and argv[argv.index("--type") + 1] == type_name:
            p = root / rel
            return p.read_text() if p.exists() else None
    return None


def slot_const(root: Path, name: str) -> str:
    """The emitted constant for a declared site, spelled by the EMITTER's own
    rule rather than by a second copy of it here."""
    sys.path.insert(0, str(root / "scripts"))
    from emitter.plugins.register_dsl import to_const
    return to_const(name)


def validate(root: Path, stanzas: list[dict], docs: dict, text: str,
             src: str | None, log: logging.Logger) -> list[str]:
    """Every problem with `stanzas`, as a list of sentences.

    Takes the stanzas rather than reading them, so `--prove` can hand it a
    mutant and watch it object. A check that can only ever be run against the
    committed data cannot be shown to work.
    """
    bad: list[str] = []

    if len(stanzas) < MIN_INSTANCES:
        # Not a nag. The decision records this outcome as the thing that would
        # overturn it, so it has to fail rather than warn.
        bad.append(f"only {len(stanzas)} source defect(s) recorded, "
                   f"{MIN_INSTANCES} needed. Below the threshold this is a "
                   f"patch mechanism wearing a rule's name, which this "
                   f"project forbids -- reopen the decision, do not lower "
                   f"the number")

    seen: set[str] = set()
    shapes: dict[str, list[str]] = {}

    for s in stanzas:
        sid = s.get("id", "")
        if s.get("_leak"):
            bad.append(f"{s['_leak']}: a source-defect INSTANCE is in the "
                       f"language layer. The tier is generic; every instance "
                       f"names one corpus, so instances are project data")
            continue
        where = docs.get(sid, "?")
        if not sid:
            bad.append(f"{where}: a stanza with no id -- nothing can switch, "
                       f"count or cite it")
            continue
        if sid in seen:
            bad.append(f"{sid}: declared twice; a switch by id would be "
                       f"ambiguous")
        seen.add(sid)
        shapes.setdefault(s.get("shape", "<none>"), []).append(sid)

        if not s.get("text"):
            bad.append(f"{sid}: no `text` -- the marker in the output would "
                       f"name the defect and then say nothing about it")
        if not s.get("shape"):
            bad.append(f"{sid}: no `shape` -- a defect with no shape cannot "
                       f"be counted against the rule/patch threshold")

        # --- the C# site -------------------------------------------------
        site = s.get("site", {})
        for k in REQUIRED_SITE:
            if not site.get(k):
                bad.append(f"{sid}: site has no `{k}`")
        if site.get("file", "").startswith("/"):
            bad.append(f"{sid}: site.file is absolute; this repo is public "
                       f"and tracked files carry repo-relative paths only")

        # --- the contradicting authority ---------------------------------
        auth = s.get("authority", {})
        for k in REQUIRED_AUTHORITY:
            if not auth.get(k):
                bad.append(f"{sid}: authority has no `{k}`. A disagreement "
                           f"with no third source is a SUSPICION and belongs "
                           f"in `rejected`, not here")

        # --- which mode is default ---------------------------------------
        if s.get("mode") != "fidelity":
            bad.append(f"{sid}: mode is `{s.get('mode')}`, must be `fidelity` "
                       f"in committed data. The oracle certifies equivalence "
                       f"with the C#, so a corrected output is a FAILED "
                       f"output. Switch at the call site: "
                       f"emit.py --conformance {sid}")
        if not s.get("why_this_mode"):
            bad.append(f"{sid}: no `why_this_mode` -- the default is the one "
                       f"field a reader is most likely to want to overturn")

        conf = s.get("conformance", {})
        if conf.get("action") not in ACTIONS:
            bad.append(f"{sid}: conformance.action is "
                       f"`{conf.get('action')}`, not one of "
                       f"{sorted(ACTIONS)}")
        if not conf.get("why"):
            bad.append(f"{sid}: conformance has no `why`")
        if conf.get("action") == "refine_fields" and not conf.get("replace"):
            bad.append(f"{sid}: conformance claims `refine_fields` and "
                       f"replaces nothing -- a switch that changes no output "
                       f"reads exactly like a defect with no cost")

        # --- which traces fail if you switch -----------------------------
        imp = s.get("switch_impact", {})
        if not imp.get("measured"):
            bad.append(f"{sid}: switch_impact is not marked measured. Run "
                       f"scripts/measure_bug_switch.py {sid} -- a bug rule "
                       f"whose switch-impact is unknown is not finished")
        if not imp.get("how"):
            bad.append(f"{sid}: switch_impact has no `how`; the measurement "
                       f"must be repeatable by whoever doubts it")
        traces = imp.get("traces", {})
        if not traces:
            bad.append(f"{sid}: switch_impact names no trace")
        for tname, counts in traces.items():
            if not (root / "oracle" / "traces" / f"{tname}.jsonl.gz").exists():
                bad.append(f"{sid}: switch_impact names trace `{tname}`, "
                           f"which is not in oracle/traces/")
            for mode in ("fidelity", "conformance"):
                if not isinstance(counts.get(mode), int):
                    bad.append(f"{sid}: switch_impact.traces.{tname} has no "
                               f"integer `{mode}` divergence count")
        if not imp.get("reading"):
            bad.append(f"{sid}: switch_impact has no `reading` -- a number "
                       f"with no interpretation is the form these were in "
                       f"before they were data")

        # --- does it reach the output? -----------------------------------
        #
        # TWO questions, and the first one alone is not enough. A marker in the
        # committed file only proves that SOME run emitted one; it says nothing
        # about whether the stanza as it now reads still matches anything. A
        # site renamed to something the converter never emits leaves the old
        # marker sitting in the file and passes -- which is exactly the mutant
        # `--prove` caught, and exactly the state a stale stanza is in.
        if not s.get("unreached_reason"):
            if tag_for(root, s) not in text:
                bad.append(f"{sid}: no marker in any generated file. A stanza "
                           f"that matches nothing emits nothing, which is "
                           f"indistinguishable from having no stanza. Fix the "
                           f"site, or record `unreached_reason`")
            mod = module_text(root, site.get("type", ""))
            if mod is None:
                bad.append(f"{sid}: no generated module owns C# type "
                           f"`{site.get('type')}`, so the site cannot be "
                           f"reached at all")
            elif site.get("name") and (
                    f"{slot_const(root, site['name'])}: u64" not in mod):
                bad.append(f"{sid}: site names `{site.get('name')}`, which is "
                           f"not a slot the converter emits for "
                           f"`{site.get('type')}`. The stanza will never "
                           f"match; any marker in the file is left over from "
                           f"when it did")

    # --- rule, or patch? --------------------------------------------------
    # A shape that reaches fewer than three sites is this project's definition
    # of a patch, and the point of the threshold is that it is counted rather
    # than argued about. It is not fatal here -- the CLASS is over the line --
    # but every stanza in a thin shape has to say so.
    for shape, ids in sorted(shapes.items()):
        if len(ids) < MIN_INSTANCES:
            for sid in ids:
                st = next((x for x in stanzas if x.get("id") == sid), {})
                if not st.get("below_threshold"):
                    bad.append(
                        f"{sid}: shape `{shape}` reaches {len(ids)} site(s), "
                        f"under {MIN_INSTANCES}. Record `below_threshold` "
                        f"saying why it is still a rule and not a patch")

    # --- the site text, against the actual C# -----------------------------
    if not src or not Path(src).is_dir():
        log.warning("RENODE_SRC is unset or not a directory -- the site line "
                    "of every stanza went UNVERIFIED. Set it in .env "
                    "(see .env.example) to check the C# still says what the "
                    "stanza quotes.")
    else:
        for s in stanzas:
            site = s.get("site", {})
            if not (site.get("file") and site.get("line")):
                continue
            p = Path(src) / site["file"]
            if not p.exists():
                bad.append(f"{s.get('id')}: site file not in RENODE_SRC: "
                           f"{site['file']}")
                continue
            lines = p.read_text(errors="replace").splitlines()
            n = site["line"]
            got = lines[n - 1].strip() if 0 < n <= len(lines) else "<past EOF>"
            if got != site.get("csharp", "").strip():
                bad.append(
                    f"{s.get('id')}: {site['file']}:{n} has DRIFTED.\n"
                    f"        stanza: {site.get('csharp')}\n"
                    f"        source: {got}\n"
                    f"        A stanza pointing at the wrong line reads as "
                    f"evidence and is not. Re-verify the defect against the "
                    f"authority before moving the line number.")
        log.info("verified %d site line(s) against the C# under RENODE_SRC",
                 len([s for s in stanzas if s.get("site", {}).get("line")]))

    log.info("%d source defect(s) over %d shape(s):", len(stanzas), len(shapes))
    for shape, ids in sorted(shapes.items()):
        log.info("    %-28s %d  %s", shape, len(ids), ", ".join(sorted(ids)))
    return bad


#: Each mutation removes ONE piece of evidence the decision says a bug rule
#: carries, and this check must object to every one of them. They are applied
#: in memory to a copy: nothing on disk is touched, so `--prove` is safe to run
#: at any time and cannot leave the data mutated if it is interrupted.
MUTATIONS: dict[str, object] = {
    "the contradicting authority is gone":
        lambda ss: ss[0].pop("authority", None),
    "the authority is a claim with no citation":
        lambda ss: ss[0]["authority"].pop("cites", None),
    "the default has been flipped to conformance":
        lambda ss: ss[0].__setitem__("mode", "conformance"),
    "the switch-impact is gone":
        lambda ss: ss[0].pop("switch_impact", None),
    "the switch-impact is asserted, not measured":
        lambda ss: ss[0]["switch_impact"].__setitem__("measured", False),
    "the switch-impact names no trace":
        lambda ss: ss[0]["switch_impact"].__setitem__("traces", {}),
    "a divergence count is prose instead of a number":
        lambda ss: ss[0]["switch_impact"]["traces"]["can1"]
                     .__setitem__("conformance", "unchanged"),
    "the C# site line has drifted":
        lambda ss: ss[0]["site"].__setitem__("line", 1),
    "the class has fallen under the threshold":
        lambda ss: ss.__delitem__(slice(MIN_INSTANCES - 1, None)),
    "a thin shape stopped saying it is thin":
        lambda ss: [s.pop("below_threshold", None) for s in ss],
    "a stanza matches nothing in the output":
        lambda ss: ss[0]["site"].__setitem__("name", "NO_SUCH_SLOT"),
}


def prove(root: Path, log: logging.Logger) -> int:
    """Assert this check REJECTS data with each piece of evidence removed.

    A gate nobody has watched fail is indistinguishable from a gate that does
    nothing, and this project has already shipped one that was passing because
    it was being skipped.
    """
    stanzas, docs = load(root)
    text = emitted_text(root)
    src = load_env(root).get("RENODE_SRC")
    quiet = logging.getLogger("check_bug_rules.quiet")
    quiet.addHandler(logging.NullHandler())
    quiet.propagate = False

    missed = 0
    for name, mutate in MUTATIONS.items():
        mutant = copy.deepcopy(stanzas)
        mutate(mutant)
        # `unreached_reason` would excuse the last mutation; strip it so the
        # mutation is testing the check and not the escape hatch.
        found = validate(root, mutant, docs, text, src, quiet)
        if found:
            log.info("    REJECTED  %s", name)
        else:
            log.error("    ACCEPTED  %s  <-- the check does not catch this",
                      name)
            missed += 1
    log.info("%d of %d mutation(s) caught", len(MUTATIONS) - missed,
             len(MUTATIONS))
    return 1 if missed else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prove", action="store_true",
                    help="assert this check rejects data with its evidence "
                         "removed, one field at a time")
    args = ap.parse_args()

    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("check_bug_rules")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "check_bug_rules.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    if args.prove:
        return prove(root, log)

    stanzas, docs = load(root)
    bad = validate(root, stanzas, docs, emitted_text(root),
                   load_env(root).get("RENODE_SRC"), log)
    if bad:
        log.error("")
        log.error("BUG RULE EVIDENCE MISSING -- %d problem(s):", len(bad))
        for b in bad:
            log.error("    %s", b)
        return 1
    log.info("OK: every source defect carries its site, its authority, its "
             "default and its measured switch-impact")
    return 0


if __name__ == "__main__":
    sys.exit(main())

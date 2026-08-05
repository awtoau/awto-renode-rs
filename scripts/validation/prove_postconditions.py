#!/usr/bin/env python3
"""BREAK the emitter on purpose and prove each postcondition rejects it.

A postcondition that has never rejected anything is decoration. `check_
postconditions.py` reports that every rule's output has the shape it promised,
which is exactly what it would report if the mechanism did nothing at all --
the two outcomes are indistinguishable from the outside, and that is the failure
mode this whole repository keeps finding in its own tooling.

So this is the negative control, and it is a TEST rather than a demonstration:
it fails if a break goes UNDETECTED. Each mutation reproduces a defect that has
actually happened here.

  1  an extra link on the chain
     An emitter helper is corrupted so a fluent chain grows a second call the
     source never asked for. This is the `.with_reserved(9, 23)` that reached a
     translated file: behaviourally inert, invisible to a 33,000-access trace,
     and shaped like every other line. Rejected by `combinators`.

  2  a template retargeted at a reserved emitter
     A storing combinator's template is pointed at a tagging one. This is the
     regression that sent 171 anonymous fields to a tag, so their writes were
     dropped and every trace still scored zero divergences. Rejected by
     `emits_call` and by `must_not_emit`.

  3  a slot dropped from a template
     A bound callback loses its slot, so the field keeps its handle and silently
     loses its behaviour -- and nothing reports it, because the call still looks
     complete. Rejected by `arity`.

  4  a forbidden shape arriving through a SUBSTITUTED slot
     The template is clean and the OUTPUT is not. This is the one the
     template-level check in `negative` cannot see, and the reason the
     postcondition reads emitted text rather than the rule.

Run:  python3 scripts/prove_postconditions.py
Log:  ./tmp/logs/prove_postconditions.log
Exit: 1 if any deliberate break was NOT caught.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import sqlite3
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True).strip())


ROOT = repo_root()
sys.path.insert(0, str(ROOT / "scripts" / "core"))
sys.path.insert(0, str(ROOT / "scripts"))  # for `emitter`

import csharp_emitter as emit  # noqa: E402
import emitter.plugins.register_dsl as dsl  # noqa: E402
from emitter.lang.postcondition import PostconditionViolation, check  # noqa: E402

DB = ROOT / "rulesdb" / "patterns.db"
# A type whose emitted output is the fluent chain these rules produce. Chosen by
# being in the generated set, not by being special -- any of them proves it.
PROBE = ("STM32_UART", "DefineRegisters")


def load_rules() -> list[dict]:
    out: list[dict] = []
    for f in sorted((ROOT / "rulesdb" / "rules").glob("*.json")):
        for r in json.loads(f.read_text()).get("rules", []):
            out.append(r)
    return out


def rule_named(rs: list[dict], name: str) -> dict:
    for r in rs:
        if r["name"] == name:
            return copy.deepcopy(r)
    raise SystemExit(f"no rule named {name} -- this proof names rules that must "
                     f"exist, so a rename must break it rather than skip it")


def filled(template: str) -> str:
    return re.sub(r"\{[a-z_]+\}", "X", template)


def break_the_emitter(log: logging.Logger) -> tuple[bool, str]:
    """Mutation 1: corrupt a helper so every chain grows a second link."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    quiet = logging.getLogger("quiet")
    quiet.addHandler(logging.NullHandler())
    em = emit.Emitter(con, quiet)
    # `render_mode` is a METHOD on the RegisterDsl mixin, not a module
    # function -- it moved there when the FieldMode table stopped being a
    # hardcoded dict. Patched on the class so the break survives that move.
    original = dsl.RegisterDsl.render_mode
    # The corruption is in a HELPER the emitter calls, not in the check and not
    # in the rule data: the emitter genuinely produces a chain of two where its
    # rule promises one, exactly as an editing accident would.
    dsl.RegisterDsl.render_mode = lambda self, const: (original(self, const)
                                                       + ").with_reserved(9, 23")
    try:
        em.emit_file(*PROBE, "probe")
    except PostconditionViolation as exc:
        return True, str(exc).splitlines()[1].strip()
    except Exception as exc:                                # noqa: BLE001
        return False, (f"broke, but with {type(exc).__name__} rather than a "
                       f"postcondition violation: {exc}")
    finally:
        dsl.RegisterDsl.render_mode = original
        con.close()
    return False, ("the emitter produced a chain of two where the rule promises "
                   "one, and nothing objected")


def main() -> int:
    logdir = ROOT / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(message)s",
        handlers=[logging.FileHandler(logdir / "prove_postconditions.log",
                                      mode="w"),
                  logging.StreamHandler(sys.stdout)])
    log = logging.getLogger("prove_postconditions")

    rs = load_rules()
    results: list[tuple[str, bool, str]] = []

    # ---- control: unbroken, nothing fires -------------------------------
    clean = [m for r in rs if r.get("postcondition")
             for m in check(r["name"], r["postcondition"], filled(r["emit"]))]
    results.append(("CONTROL: unmutated rules pass", not clean,
                    "; ".join(clean) or "no violations, as expected"))

    # ---- 1: an extra link on the chain ----------------------------------
    caught, detail = break_the_emitter(log)
    results.append(("1  extra combinator on the chain "
                    "(the `.with_reserved(9, 23)` defect)", caught, detail))

    # ---- 2: a template retargeted at a reserved emitter ------------------
    r = rule_named(rs, "WITH_VALUE_ANONYMOUS")
    r["emit"] = ".with_tag({pos}, {width})"
    bad = check(r["name"], r["postcondition"], filled(r["emit"]))
    results.append(("2  storing template retargeted at a tag "
                    "(the 171 dropped fields)", bool(bad),
                    bad[0] if bad else "NOT CAUGHT"))

    # ---- 3: a slot dropped from a template -------------------------------
    r = rule_named(rs, "WITH_FLAG_BOUND_COMPUTED")
    r["emit"] = ".with_flag_cb({pos}, &mut f.{field}, {mode}, {provider_fn})"
    bad = check(r["name"], r["postcondition"], filled(r["emit"]))
    results.append(("3  callback slot dropped from a template", bool(bad),
                    bad[0] if bad else "NOT CAUGHT"))

    # ---- 4: forbidden shape through a SUBSTITUTED slot -------------------
    # The template is clean; only the OUTPUT is not. This is the case a check
    # that reads the rule text cannot reach, which is why the postcondition
    # reads emitted text instead.
    r = rule_named(rs, "WITH_VALUE_BOUND")
    text = ".with_value(0, 4, &mut f.with_reserved_lookalike, FieldMode::READ_WRITE)"
    tmpl_ok = not check(r["name"], r["postcondition"], filled(r["emit"]))
    bad = check(r["name"], r["postcondition"], text)
    results.append(("4  forbidden shape arriving through a substituted slot",
                    bool(bad) and tmpl_ok,
                    bad[0] if bad else "NOT CAUGHT -- the template was clean "
                                       "and the output was not"))

    log.info("")
    log.info("%-62s %s", "deliberate break", "caught")
    log.info("%s", "-" * 74)
    failed = 0
    for what, ok, detail in results:
        log.info("%-62s %s", what, "yes" if ok else "NO")
        log.info("    %s", detail[:200])
        if not ok:
            failed += 1
    log.info("%s", "-" * 74)
    log.info("%d of %d break(s) went undetected", failed, len(results))
    if failed:
        log.error("")
        log.error("A postcondition that cannot reject anything is decoration. "
                  "This is the check that says the mechanism is load-bearing, "
                  "and it just said it is not.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

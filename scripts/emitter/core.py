"""Dispatch registry for the emitter.

The point of this module is the LAYER BOUNDARY, which CLAUDE.md states as a
hard rule and which was previously only a convention about which JSON file a
rule lived in. `emit.py` handled `Binary` and `Conversion` -- generic C# -- in
the same file, and by the same mechanism, as Renode's register collection and
`this.Log`. Nothing structural stopped Renode knowledge leaking into the
transpiler; only care did, and care is not enforcement.

Two layers, and they are not peers:

    lang/     GENERIC C# to Rust. Must hold for ANY corpus. May not mention
              Renode, a peripheral, or a register -- `check_layering.py` fails
              the commit if it does.

    plugins/  Corpus-specific. Renode lives here, and so would anything else.
              Free to know about register banks and peripherals.

A plugin is consulted BEFORE the language layer, so a corpus idiom can override
a generic mapping -- which is what lets `IRQ.Set(x)` mean something particular
without the generic invocation rule knowing it exists.

Adding a construct is a new file in one directory or the other. Two people
adding two constructs touch two different files, which is what makes parallel
work on the transpiler safe.
"""

from __future__ import annotations

from typing import Callable

def snake(name: str) -> str:
    """C# camelCase field name -> Rust snake_case.

    A naming rule, not a cosmetic one: emitted code must be idiomatic Rust or it
    will not survive review, and hand-fixing every name afterwards is exactly the
    per-file patching this pipeline exists to avoid.
    """
    out: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper():
            prev_lower = i > 0 and name[i - 1].islower()
            next_lower = i + 1 < len(name) and name[i + 1].islower()
            if i > 0 and (prev_lower or next_lower):
                out.append("_")
            out.append(ch.lower())
        else:
            out.append(ch)
    return "".join(out)


# kind -> [(priority, handler)]. Lower priority number wins; plugins register
# at 0 and the language layer at 100, so a corpus idiom is always tried first.
PLUGIN = 0
LANGUAGE = 100

_EXPR: dict[str, list[tuple[int, Callable]]] = {}
_STMT: dict[str, list[tuple[int, Callable]]] = {}


def _register(table: dict, kinds: tuple[str, ...], priority: int, fn: Callable):
    for k in kinds:
        table.setdefault(k, []).append((priority, fn))
        table[k].sort(key=lambda pair: pair[0])
    return fn


# Normalisation passes, keyed by rule name. A pass rewrites the operation
# tree into an equivalent shape BEFORE the emit rules see it; it returns True
# if it changed anything, which is what drives the fixpoint.
_NORMALISE: dict[str, Callable] = {}


def normalise(name: str):
    """Register a normalisation pass under its name in the rules data.

    Order comes from the DATA (`normalisations.passes[].order`), never from
    registration order or dict iteration -- two passes matching the same node
    give different results depending on which ran first, and output must be
    byte-identical at -j1 and -j32.
    """
    def deco(fn):
        _NORMALISE[name] = fn
        return fn
    return deco


def normalise_pass(name: str):
    return _NORMALISE.get(name)


def run_normalisations(em, method_id: int, spec: dict) -> int:
    """Apply every registered pass in declared order, to a fixpoint.

    Returns the number of passes run. Raises if the cap is exceeded: a rule set
    that never settles is a bug, and emitting the half-normalised tree would
    hide it behind plausible output.
    """
    passes = sorted(spec.get("passes", []), key=lambda p: (p.get("order", 0),
                                                          p.get("name", "")))
    # A pass declared in data with no registered handler, or a handler with no
    # data entry, is a WIRING ERROR -- not a rule that legitimately does not
    # apply. The two are indistinguishable at runtime otherwise, which is
    # exactly how the ConditionalAccessStatement lookup broke: `.get()`
    # returned a default, the branch fell through, and nothing errored.
    declared = {p.get("name") for p in passes}
    registered = set(_NORMALISE)
    if declared != registered:
        missing = sorted(declared - registered)
        orphan = sorted(registered - declared)
        raise RuntimeError(
            "normalisation wiring mismatch: "
            + (f"declared with no handler {missing}; " if missing else "")
            + (f"registered with no data entry {orphan}; " if orphan else "")
            + "a silent no-op here is indistinguishable from a rule that "
              "correctly does not apply")
    cap = int(spec.get("max_passes", 8))
    for n in range(1, cap + 1):
        changed = False
        for rule in passes:
            fn = _NORMALISE.get(rule.get("name", ""))
            if fn is not None and fn(em, method_id, rule):
                changed = True
        if not changed:
            return n
    raise RuntimeError(
        f"normalisation did not reach a fixpoint in {cap} passes on method "
        f"{method_id}; a rule set that never settles is a bug -- see "
        f"normalisations.max_passes_why")


def must_explain(fn):
    """Wrap an emitter so that producing NOTHING must be explained.

    The invariant, which held only by convention until six paths broke it in
    one session:

        a code path that produces no output MUST record why -- a gap, an
        `unhandled` entry, or an exception. Silence is never valid.

    Two of those six were reported as landed in commit messages before anyone
    noticed, and one survived two commits. Every case looked identical to a
    rule that correctly declined, which is why review never caught them: there
    is nothing to see.

    This makes the silence loud at the moment it happens.
    """
    import functools

    @functools.wraps(fn)
    def wrapper(self, *a, **kw):
        gaps_before = len(getattr(self, "gaps", ()))
        unhandled_before = len(getattr(self, "unhandled", ()))
        result = fn(self, *a, **kw)
        empty = result is None or (isinstance(result, (list, tuple, str))
                                   and len(result) == 0)
        if empty:
            explained = (len(getattr(self, "gaps", ())) > gaps_before
                         or len(getattr(self, "unhandled", ())) > unhandled_before)
            if not explained:
                raise RuntimeError(
                    f"{fn.__name__} produced nothing and explained nothing "
                    f"(args={a[:2]}). A path that emits no output must record a "
                    f"gap or an unhandled kind -- silence is indistinguishable "
                    f"from a rule that correctly declines. See issue #53.")
        return result

    return wrapper


def expr(*kinds: str, priority: int = LANGUAGE):
    """Register an EXPRESSION handler for one or more operation kinds.

    The handler is called as fn(em, ctx) and returns Rust source, or None to
    decline -- declining falls through to the next handler, which is how a
    plugin can handle only the cases it recognises.
    """
    def deco(fn):
        return _register(_EXPR, kinds, priority, fn)
    return deco


def stmt(*kinds: str, priority: int = LANGUAGE):
    """Register a STATEMENT handler. Returns a list of lines, or None."""
    def deco(fn):
        return _register(_STMT, kinds, priority, fn)
    return deco


def expr_handlers(kind: str):
    return [fn for _, fn in _EXPR.get(kind, ())]


def stmt_handlers(kind: str):
    return [fn for _, fn in _STMT.get(kind, ())]


def registered_kinds() -> dict[str, list[str]]:
    """Which kinds have a handler, and from which layer. Used by the coverage
    report so 'handled' is a fact about the registry rather than a grep."""
    out: dict[str, list[str]] = {}
    for table, what in ((_EXPR, "expr"), (_STMT, "stmt")):
        for kind, entries in table.items():
            for prio, fn in entries:
                layer = "plugin" if prio < LANGUAGE else "lang"
                out.setdefault(kind, []).append(f"{what}:{layer}:{fn.__module__}")
    return out

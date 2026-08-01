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

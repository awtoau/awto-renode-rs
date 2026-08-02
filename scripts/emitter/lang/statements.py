"""Statement DISPATCH. The constructs themselves are one file each.

LANGUAGE LAYER. Nothing here may name anything specific to the corpus being
translated. `scripts/check_layering.py` fails the commit if it does, because a
transpiler that knows about one codebase is not a transpiler.

(That check is deliberately blunt and matches on words, so even a docstring
explaining the rule can trip it. A rename costs seconds; a leak costs reuse.)

Structure comes from `rulesdb/rules/csharp_core.json`; a construct module
decides which rule applies and how the pieces nest, never what the Rust looks
like.

This module used to hold twelve constructs in one `if kind == ...` chain, which
made it the one file every agent adding a statement had to edit. Each is now a
`stmt_*.py` sibling registered through `core.stmt`, and what is left here is the
dispatch and the fallback that reports an unknown kind.

Two things about the dispatch are load-bearing and easy to undo by accident:

  * ORDER. Handlers run before the fallback, and among themselves in PRIORITY
    order. Two modules claim `ExpressionStatement` and the more specific one
    must run first, so they declare priorities rather than relying on the order
    the modules happen to be imported in.

  * DECLINING. A handler returns None to mean "not mine", and dispatch then
    keeps looking. A handler that returned an empty list instead would stop the
    search and silently emit nothing -- which is why an empty return is only
    correct where it means "there was nothing to emit", and every other path
    either returns None or records a gap.
"""

from __future__ import annotations

from emitter import core


class Statements:
    """Mixin: statement dispatch, and a block of statements."""

    def emit_stmt(self, oid: int, indent: int = 0) -> list[str]:
        """One statement, possibly nested. Structure from the LANGUAGE rules."""
        pad = "    " * indent
        row = self.con.execute(
            "SELECT kind FROM operation WHERE id=?", (oid,)).fetchone()
        if row is None:
            return []
        kind = row[0]

        # Registered handlers first, so a NEW construct is a new file rather
        # than another branch below. Without this the registry in core.py was
        # decoration: every new statement kind meant editing this chain, which
        # is the single file the work protocol promises agents will not share.
        # The chain that used to follow is gone: every construct is a sibling
        # module now, so this loop is the whole of dispatch.
        for fn in core.stmt_handlers(kind):
            got = fn(self, oid, indent)
            if got is not None:
                return got

        self.unhandled[f"stmt:{kind}"] = self.unhandled.get(f"stmt:{kind}", 0) + 1
        return [f"{pad}/* {kind} */"]

    def emit_block(self, oid: int, indent: int) -> list[str]:
        """A Block, or a single statement used as one."""
        row = self.con.execute("SELECT kind FROM operation WHERE id=?", (oid,)).fetchone()
        if row and row[0] == "Block":
            out: list[str] = []
            for cid, _k, _s, _c, _t in self.children(oid):
                out.extend(self.emit_stmt(cid, indent))
            return out
        return self.emit_stmt(oid, indent)


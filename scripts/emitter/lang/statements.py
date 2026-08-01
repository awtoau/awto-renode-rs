"""Statements and control flow: generic C# to Rust.

LANGUAGE LAYER. Nothing here may name anything specific to the corpus being
translated. `scripts/check_layering.py` fails the commit if it does, because a
transpiler that knows about one codebase is not a transpiler.

(That check is deliberately blunt and matches on words, so even a docstring
explaining the rule can trip it. A rename costs seconds; a leak costs reuse.)

Structure comes from `rulesdb/rules/csharp_core.json`; this module decides
which rule applies and how the pieces nest, never what the Rust looks like.

Two things here are load-bearing and easy to undo by accident:

  * A loop's KIND comes from the corpus (Roslyn's LoopKind), not from guessing
    at the child shape. For, ForEach, While and Do all arrive as kind `Loop`
    and have different children; inferring instead of reading it produced a
    `for(;;)` emitted as a `foreach`.

  * An increment in STATEMENT position routes here, where prefix and postfix
    are indistinguishable. In EXPRESSION position they are not, so that case
    reports a gap rather than silently dropping the difference.
"""

from __future__ import annotations

import json

from emitter import core
from emitter.core import snake


class Statements:
    """Mixin: statement and control-flow emission."""

    def emit_stmt(self, oid: int, indent: int = 0) -> list[str]:
        """One statement, possibly nested. Structure from the LANGUAGE rules."""
        pad = "    " * indent
        row = self.con.execute(
            "SELECT kind, symbol, detail FROM operation WHERE id=?", (oid,)).fetchone()
        if row is None:
            return []
        kind, _symbol, detail = row
        kids = self.children(oid)

        # Registered handlers first, so a NEW construct is a new file rather
        # than another branch below. Without this the registry in core.py was
        # decoration: every new statement kind meant editing this chain, which
        # is the single file the work protocol promises agents will not share.
        for fn in core.stmt_handlers(kind):
            got = fn(self, oid, indent)
            if got is not None:
                return got

        if kind == "Loop":
            return self.emit_loop(oid, indent)

        if kind == "Switch" and kids:
            return self.emit_switch(oid, indent)

        if kind in ("Increment", "Decrement") and kids:
            tmpl = self.language.get("increment", {}).get(kind)
            if tmpl:
                return [pad + tmpl.format(target=self.emit_expr(kids[0][0]))]
        stmts = self.language.get("statements", {})

        if kind == "ExpressionStatement":
            if not kids:
                return []
            # An Increment here is in STATEMENT position, where prefix and
            # postfix are indistinguishable; route it to the statement rule
            # rather than the expression one, which reports a gap.
            if self.kind_of(kids[0][0]) in ("Increment", "Decrement"):
                return self.emit_stmt(kids[0][0], indent)
            return [pad + self.emit_expr(kids[0][0]) + ";"]

        if kind == "SimpleAssignment":
            return [pad + self.emit_assignment(oid)]

        if kind == "Return":
            tmpl = stmts.get("Return", {})
            if kids:
                val = self.emit_expr(kids[0][0])
                coerce = getattr(self, "_coerce_ret", None)
                if coerce:
                    val = self.language.get("coercions", {}).get(
                        coerce, "{expr}").format(expr=val)
                return [pad + tmpl.get("with_value", "return {value};")
                        .format(value=val)]
            return [pad + tmpl.get("bare", "return;")]

        if kind == "Conditional" and len(kids) >= 2:
            cond = self.emit_expr(kids[0][0])
            then = self.emit_block(kids[1][0], indent + 1)
            out = [f"{pad}if {cond} {{"] + then
            if len(kids) >= 3:
                out.append(f"{pad}}} else {{")
                out.extend(self.emit_block(kids[2][0], indent + 1))
            out.append(pad + "}")
            return out

        if kind in ("VariableDeclarationGroup", "VariableDeclaration"):
            out: list[str] = []
            for cid, _k, _s, _c, _t in kids:
                out.extend(self.emit_stmt(cid, indent))
            return out

        if kind == "VariableDeclarator":
            name = "value"
            if detail:
                try:
                    name = snake(json.loads(detail).get("local", "value"))
                except json.JSONDecodeError:
                    pass
            init = None
            for cid, ckind, _s, _c, _t in kids:
                if ckind == "VariableInitializer":
                    inner = self.children(cid)
                    if inner:
                        init = self.emit_expr(inner[0][0])
            tmpl = stmts.get("VariableDeclarator", {})
            if init is not None:
                return [pad + tmpl.get("with_init", "let mut {name} = {init};")
                        .format(name=name, init=init)]
            return [pad + tmpl.get("bare", "let mut {name};").format(name=name)]

        self.unhandled[f"stmt:{kind}"] = self.unhandled.get(f"stmt:{kind}", 0) + 1
        return [f"{pad}/* {kind} */"]

    def emit_switch(self, oid: int, indent: int) -> list[str]:
        """C# switch as a Rust match.

        The `break` that C# demands at the end of every section is dropped: it
        encodes a syntax rule, not behaviour, and Rust arms do not fall
        through. A Branch that is NOT that break is real control flow (a
        `goto case`) and is reported rather than silently discarded."""
        pad = "    " * indent
        rules = self.language.get("switch", {})
        kids = list(self.children(oid))
        subject = self.emit_expr(kids[0][0])
        out = [pad + rules.get("match", "match {subject} {{").format(subject=subject)]
        saw_default = False
        for cid, ckind, _s, _c, _t in kids[1:]:
            if ckind != "SwitchCase":
                continue
            labels, body = [], []
            for gid, gkind, _s2, _c2, _t2 in self.children(cid):
                if gkind in ("CaseClause", "SingleValueCaseClause",
                             "DefaultCaseClause", "ConstantPattern"):
                    vals = list(self.children(gid))
                    if not vals:
                        labels.append(rules.get("default_label", "_"))
                        saw_default = True
                    else:
                        labels.append(self.emit_expr(vals[0][0]))
                elif gkind == "Branch":
                    continue          # the mandatory C# break
                else:
                    body.extend(self.emit_stmt(gid, indent + 2))
            if not labels:
                labels = [rules.get("default_label", "_")]
            out.append(pad + "    " + rules.get("arm", "{labels} => {{").format(
                labels=rules.get("label_sep", " | ").join(labels)))
            out.extend(body)
            out.append(pad + "    }")
        if not saw_default:
            # Rust demands exhaustiveness; C# simply falls out of a switch that
            # matches nothing, so the added arm does nothing.
            out.append(pad + "    _ => {}")
        out.append(pad + "}")
        return out

    def emit_loop(self, oid: int, indent: int) -> list[str]:
        """A C# loop. The kind comes from the corpus (LoopKind), not from the
        child shape, so a For and a ForEach are never confused."""
        pad = "    " * indent
        rules = self.language.get("loops", {})
        det = (self.con.execute("SELECT detail FROM operation WHERE id=?", (oid,))
               .fetchone() or [None])[0]
        info = {}
        if det:
            try:
                info = json.loads(det)
            except json.JSONDecodeError:
                info = {}
        lk = info.get("loop")
        kids = list(self.children(oid))
        body_id = next((c[0] for c in kids if c[1] == "Block"), None)
        body = self.emit_block(body_id, indent + 1) if body_id is not None else []

        if lk == "ForEach" and len(kids) >= 2:
            coll = self.emit_expr(kids[0][0])
            var = snake(info.get("var") or "item")
            return [pad + f"for {var} in {coll} {{", *body, pad + "}"]

        if lk == "While":
            cond = self.emit_expr(kids[0][0]) if kids else "true"
            return [pad + f"while {cond} {{", *body, pad + "}"]

        if lk == "For":
            init = [c for c in kids if c[1] == "VariableDeclarationGroup"]
            cond = [c for c in kids if c[1] == "Binary"]
            incr = [c for c in kids if c[1] == "ExpressionStatement"]
            out = []
            for c in init:
                out.extend(self.emit_stmt(c[0], indent))
            cond_txt = self.emit_expr(cond[0][0]) if cond else "true"
            out.append(pad + f"while {cond_txt} {{")
            out.extend(body)
            for c in incr:
                out.extend(self.emit_stmt(c[0], indent + 1))
            out.append(pad + "}")
            return out

        self.unhandled[f"loop:{lk}"] = self.unhandled.get(f"loop:{lk}", 0) + 1
        return []

    def emit_block(self, oid: int, indent: int) -> list[str]:
        """A Block, or a single statement used as one."""
        row = self.con.execute("SELECT kind FROM operation WHERE id=?", (oid,)).fetchone()
        if row and row[0] == "Block":
            out: list[str] = []
            for cid, _k, _s, _c, _t in self.children(oid):
                out.extend(self.emit_stmt(cid, indent))
            return out
        return self.emit_stmt(oid, indent)


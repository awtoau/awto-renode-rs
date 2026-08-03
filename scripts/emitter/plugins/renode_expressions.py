"""Renode-specific expression handling.

This is the PLUGIN layer. It knows what a register bank, a peripheral and a
log level are, and it is consulted BEFORE the language layer so a corpus idiom
can override a generic mapping -- which is how `IRQ.Set(x)` means something
particular without the generic invocation rule knowing it exists.

Nothing here is reusable on another corpus, and that is the point: keeping it
in its own file is what lets `scripts/emitter/lang/` stay clean, and
`scripts/check_layering.py` enforces that separation as a build failure.

Handlers return emitted Rust, or None to decline -- declining falls through to
the language layer.
"""

from __future__ import annotations

from emitter.core import snake
from emitter.plugins.register_dsl import to_const


class RenodeExpressions:
    """Mixin: corpus-specific expression handlers, tried before the language."""

    @staticmethod
    def _log_message_args(rest: list[str]) -> list[str]:
        """Renode's message argument is a C# string, but not always a Rust
        string LITERAL: an interpolated string arrives as `format!(..)` (unwrap
        it, its own literal+args pass straight through) while a plain
        expression (a local variable, a `.ToString()` call, ...) is neither --
        the log macros require the first argument to be a literal, so that
        case is wrapped as `"{}", expr` rather than passed bare."""
        if len(rest) == 1 and rest[0].startswith("format!(") and rest[0].endswith(")"):
            return [rest[0][len("format!("):-1]]
        if rest and not rest[0].startswith('"'):
            return [f'"{{}}", {rest[0]}', *rest[1:]]
        return rest

    def plugin_expr(self, oid, kind, symbol, const, rtype, detail, kids, args, all_kids):
        """Corpus idioms. Returns Rust, or None to fall through."""
        # The register-offset enum (e.g. `Registers.Control`) is never declared
        # as a Rust enum -- it is `mod reg` instead, see `_offset_enum_names` in
        # emit_file -- so a peer method's reference to it must resolve there
        # too, not to a type the language layer's generic enum rule would
        # otherwise send to a name that was correctly never declared (E0433).
        if kind == "FieldReference" and symbol and getattr(self, "_offset_enum_names", None):
            parts = symbol.split("(")[0].split(".")
            if len(parts) >= 2 and parts[-2] in self._offset_enum_names:
                return f"reg::{to_const(parts[-1])}"
        # Project idioms first: they are more specific than the language rules.
        for rule in self.expressions:
            if rule["kind"] != kind:
                continue
            if rule.get("symbol_contains") and (
                    not symbol or rule["symbol_contains"] not in symbol):
                continue
            if rule.get("type_is") and rtype != rule["type_is"]:
                continue
            env: dict[str, str] = {}
            if "{field}" in rule["emit"]:
                env["field"] = self.receiver_field(oid) or "UNKNOWN"
            for i, k in enumerate(args):
                env[f"arg{i}"] = self.emit_expr(k)
            try:
                return rule["emit"].format(**env)
            except KeyError:
                self.unhandled[f"{rule['name']}:binding"] = 1
        rc = self.project.get("register_collection", {})
        if (kind == "Invocation" and symbol
                and rc.get("symbol_contains", "\0") in symbol):
            meth = symbol.split("(")[0].split(".")[-1]
            tmpl = rc.get("members", {}).get(meth)
            if tmpl:
                vals = [self.emit_expr(a) for a in args]
                fmt = {f"arg{i}": v for i, v in enumerate(vals)}
                fmt["args"] = ", ".join(vals)
                return tmpl.format(**fmt)

        logrule = self.project.get("logging", {})
        method_levels = logrule.get("method_levels", {})
        mname = symbol.split("(")[0].split(".")[-1] if kind == "Invocation" and symbol else None
        if kind == "Invocation" and mname in method_levels:
            # `this.WarningLog(msg)` etc: the level is the METHOD NAME, not an
            # operand, so unlike Log() below there is no level arg to skip --
            # arg 0 is still the peripheral receiver, arg 1+ is the message.
            vals = [self.emit_expr(a) for a in args]
            rest = self._log_message_args(vals[1:])
            return logrule.get("emit", "log::{level}!({args})").format(
                level=method_levels[mname], args=", ".join(rest))

        if (kind == "Invocation" and symbol
                and logrule.get("symbol_contains", "\0") in symbol):
            # Renode's Log extension: (this, level, format, args...). It is
            # STATIC, so arg 0 is the peripheral and arg 1 the level -- taking
            # the arguments from the front would log at level "self".
            levels = logrule.get("levels", {})
            vals = [self.emit_expr(a) for a in args]
            lvl, rest = logrule.get("default_level", "info"), vals[2:]
            if len(vals) > 1:
                # The level is a FieldReference BELOW the Argument node, so the
                # argument's own symbol is the parameter and never the level.
                raw = ""
                stack = [args[1]]
                while stack:
                    cur = stack.pop()
                    for cid, sym in self.con.execute(
                            "SELECT id, symbol FROM operation WHERE parent_id=?", (cur,)):
                        if sym and "LogLevel." in sym:
                            raw = sym
                            stack = []
                            break
                        stack.append(cid)
                lvl = levels.get(raw.split(".")[-1], lvl)
            # log! takes format arguments itself; a nested format!() is a
            # compile error (the macro needs a literal). See unwrap_format.
            rest = self._log_message_args(rest)
            return logrule.get("emit", "log::{level}!({args})").format(
                level=lvl, args=", ".join(rest))

        if kind == "Invocation" and symbol and self._current_type:
            # A call on `this` whose target is declared on a BASE type is
            # `base.Foo()`. Emitting it as a self-call is unbounded recursion
            # that compiles -- see peripheral_methods.base_call.
            decl = symbol.split("(")[0].rsplit(".", 1)[0].split(".")[-1]
            recv0 = next((c[0] for c in all_kids if c[1] != "Argument"), None)
            rk = self.kind_of(recv0) if recv0 is not None else None
            if decl and decl != self._current_type and rk == "InstanceReference":
                mname = symbol.split("(")[0].rsplit(".", 1)[-1]
                qual = self.project.get("inheritance", {}).get(
                    "qualified_call", "{base}_{name}").format(
                    base=snake(decl), name=snake(mname))
                if qual in self._emitted_fns or snake(mname) in self._emitted_fns:
                    target = qual if qual in self._emitted_fns else snake(mname)
                    arg_txt = ", ".join(self.emit_expr(a) for a in args)
                    return (f"{target}(bank, st, {arg_txt})" if arg_txt
                            else f"{target}(bank, st)")
                spec = self.project.get("peripheral_methods", {}).get("base_call", {})
                self.gaps.append(spec.get("gap", "base call to {name}").format(
                    name=mname, type=decl))
                return "/* GAP: base-class call */"

        return None

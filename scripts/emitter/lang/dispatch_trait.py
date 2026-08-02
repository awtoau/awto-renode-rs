"""Virtual dispatch as a Rust trait, derived from a base CLASS.

LANGUAGE LAYER -- see `scripts/check_layering.py`.

Generic C#. What this module knows about the input it asks the corpus database:
which classes have subclasses, which of their members are `virtual` or
`abstract`, and what each subclass's translated module exports. The templates
come from the rules; nothing about any particular corpus is written here.

THE RULE
--------
A class that (a) is inside the corpus, (b) has at least one subclass inside the
corpus, and (c) declares public `virtual` or `abstract` members, defines a
DISPATCH CONTRACT. Its subclasses implement that contract, and a caller holding
`dyn Contract` reaches whichever body the subclass supplies. That is true of any
C# corpus and needs no interface to be present.

THE APPROXIMATION, AND IT IS RECORDED IN THE OUTPUT
--------------------------------------------------
A base class is not the interface. Where the C# dispatches through an interface,
this trait is a DIFFERENT type with a different name, and `x is ISomething` is
not served by it. That approximation exists only because the corpus does not
hold those interfaces: their members are unknown, so a trait declared from them
would have members chosen by hand rather than derived.

It is emitted into the generated file's header rather than left in a document,
because an approximation that is invisible in the output stops being an
approximation and becomes a mistranslation nobody is looking for. When the
ingest closes over the declared interfaces this rule should give way to them.

WHY RESOLUTION IS STRICT
------------------------
The emitter flattens a base's bodies into the subclass's module. A body whose
name the subclass also declares is qualified by its declaring class, so the
PLAIN name always belongs to the most-derived body and the qualified name is
what an explicit base call reaches.

The obvious resolver forwards a trait method to the plain name and falls back to
the qualified one. Run that way, three of four subclasses got a `reset` that ran
the BASE's body -- each of them overrides it in C#, and each override was
withheld for an unrelated reason, so the fallback found the base copy and used
it. That compiles, and a replay oracle cannot see it, because the code is not
absent, it is wrong.

So the qualified name is exactly the set of bodies a vtable must never reach.
Resolution takes the plain name or nothing:

    strict      plain name, or the method leaves the trait
    permissive  plain name, else any export ending `_<name>`   <-- the bug

`permissive` exists so `scripts/check_inheritance.py` can demonstrate the
failure against the real corpus rather than against a mock. Nothing that emits
ever passes `strict=False`.

The cost is real and was accepted knowingly: one untranslatable base member
shrinks the contract for EVERY implementor at once, because a trait method must
be supplied by all of them. It cannot be stubbed -- a stub returning a default
is the "unmapped return type became `-> ()`" bug wearing a trait's clothes.

SIGNATURES COME FROM THE IMPLEMENTORS, NOT FROM A TYPE MAPPING
--------------------------------------------------------------
The trait's parameter and return types are read back out of the modules that
will implement it, using a pattern supplied by the rules. Mapping the C# types
again here would give a second mapping engine that can disagree with the one
that emitted the bodies -- and it would disagree silently, as a signature
mismatch that only rustc sees. If the implementors do not all agree on a
signature, the method leaves the trait and the disagreement is named.
"""

from __future__ import annotations

import re

from emitter.core import snake


def dispatch_target(name: str, exports: set[str], strict: bool = True) -> str | None:
    """The function a trait method must forward to, or None.

    Pure, and the whole correctness argument is in these four lines -- see the
    module docstring. `strict=False` is the resolver that dispatched three of
    four subclasses to their base's body; it is kept so a test can fail on it.
    """
    if name in exports:
        return name
    if strict:
        return None
    return next((e for e in sorted(exports) if e.endswith("_" + name)), None)


class DispatchTrait:
    """Mixin: a base class's virtual members as a Rust trait."""

    # ---------------------------------------------------------------- corpus

    def dispatch_contracts(self) -> list[dict]:
        """Every in-corpus class that defines a dispatch contract.

        Never empty for the wrong reason: a class with subclasses but no virtual
        member is not a contract and is skipped, and a class with virtual
        members but no subclass has nobody to dispatch between.
        """
        out: list[dict] = []
        for tid, name in self.con.execute(
                "SELECT id, name FROM type WHERE kind='class' ORDER BY name"):
            subclasses = [n for (n,) in self.con.execute(
                "SELECT name FROM type WHERE base_type_id=? ORDER BY name",
                (tid,)) if n != name]
            if not subclasses:
                continue
            members = self.con.execute(
                "SELECT mb.name, mb.id FROM member mb "
                "JOIN method m ON m.member_id = mb.id "
                "WHERE mb.type_id=? AND (m.is_virtual=1 OR m.is_abstract=1) "
                "AND mb.accessibility='public' ORDER BY mb.name", (tid,)
            ).fetchall()
            if not members:
                continue
            out.append(dict(base=name, subclasses=subclasses,
                            members=[dict(name=n, member_id=i)
                                     for n, i in members]))
        return out

    # ------------------------------------------------------------- signatures

    @staticmethod
    def dispatch_exports(text: str, pattern: str) -> dict[str, tuple[str, str]]:
        """Callable name -> (parameter tail, return type), read from a module.

        Empty means the module exports nothing callable through a trait, which
        is a real answer and not a failure: a module may emit only data.
        """
        out: dict[str, tuple[str, str]] = {}
        for m in re.finditer(pattern, text, re.M):
            out[m.group("name")] = (m.group("extra"), m.group("ret"))
        return out

    # --------------------------------------------------------------- analysis

    def dispatch_analysis(self, targets: list[dict], pattern: str,
                          strict: bool = True) -> list[dict]:
        """Every contract, with the members that survive and why the rest do not.

        `targets` is [{"type": C# name, "module": rust module, "text": its
        source}]. A contract with no implementor among them is dropped without
        comment -- it is not about these targets at all.
        """
        by_type = {t["type"]: t for t in targets}
        exports = {t["type"]: self.dispatch_exports(t["text"], pattern)
                   for t in targets}
        report: list[dict] = []
        for contract in self.dispatch_contracts():
            covered = [d for d in contract["subclasses"] if d in by_type]
            if not covered:
                continue
            withheld: list[str] = []
            methods: list[dict] = []
            for m in contract["members"]:
                fn = snake(m["name"])
                resolved = {d: dispatch_target(fn, set(exports[d]), strict)
                            for d in covered}
                absent = sorted(d for d, r in resolved.items() if r is None)
                if absent:
                    # WHICH KIND of absence, because they are different work.
                    # A withheld override is the dangerous one: the body exists
                    # in the C# and the vtable would otherwise reach the wrong
                    # one. A member nobody implements is merely untranslated.
                    overriding = [d for d in absent
                                  if self._declares(d, m["name"])]
                    why = ("their own override is not emitted, and forwarding "
                           "to the base body instead would dispatch to the "
                           "wrong method" if overriding
                           else "no implementor emits it")
                    withheld.append(
                        f"{contract['base']}.{fn}: not in the trait -- "
                        f"{len(absent)} of {len(covered)} implementor(s) "
                        f"cannot supply it ({', '.join(absent)}); {why}")
                    continue
                sigs = {exports[d][resolved[d]] for d in covered}
                if len(sigs) != 1:
                    shown = sorted(f"{d} takes ({exports[d][resolved[d]][0]}) "
                                   f"-> {exports[d][resolved[d]][1]}"
                                   for d in covered)
                    withheld.append(
                        f"{contract['base']}.{fn}: not in the trait -- "
                        f"implementors do not agree on its signature: "
                        f"{'; '.join(shown)}")
                    continue
                extra, ret = sigs.pop()
                methods.append(dict(name=fn, extra=extra, ret=ret,
                                    forwards={d: resolved[d] for d in covered}))
            if not methods:
                withheld.append(
                    f"{contract['base']}: the whole trait is withheld -- no "
                    f"member survives, so it would be a name with no contract")
            report.append(dict(base=contract["base"], implementors=covered,
                               methods=methods, withheld=sorted(set(withheld))))
        return sorted(report, key=lambda r: r["base"])

    def _declares(self, type_name: str, member: str) -> bool:
        """Does this subclass declare a member of that name itself?

        Asked of the CORPUS, not of the emitted file: the file cannot say
        whether a missing name means "not overridden" or "overridden and not
        emitted", and those two need opposite answers.
        """
        return bool(self.con.execute(
            "SELECT 1 FROM member mb JOIN type t ON t.id=mb.type_id "
            "WHERE t.name=? AND mb.kind='method' AND mb.name=? LIMIT 1",
            (type_name, member)).fetchone())

    # --------------------------------------------------------------- emission

    def emit_dispatch_traits(self, targets: list[dict],
                             forms: dict) -> tuple[str, list[dict]]:
        """The whole dispatch module, plus the analysis it was built from.

        `forms` carries the templates that know how a translated body is
        CALLED, which is a property of the corpus's calling convention and not
        of C#; this module only fills them in.
        """
        spec = self.language.get("dispatch_traits", {})
        pattern = forms.get("signature")
        if not pattern:
            # A missing template is not a rule declining: nothing here can be
            # decided without knowing how to read a translated signature.
            raise KeyError("dispatch.signature: no rule says how to read an "
                           "emitted declaration, so no trait can be derived")
        report = self.dispatch_analysis(targets, pattern)
        by_type = {t["type"]: t for t in targets}

        emitted = [r for r in report if r["methods"]]
        used = sorted({d for r in emitted for d in r["implementors"]})

        L: list[str] = []
        a = L.append
        a("//! Virtual dispatch as traits, GENERATED from the corpus.")
        a("//!")
        a("//! Do not edit: `scripts/check_generated.py` fails the commit if this")
        a("//! file differs from converter output. To change it, change the rules")
        a("//! in `rulesdb/rules/` or the C# it is derived from.")
        for line in spec.get("deviation", "").splitlines():
            a(f"//! {line}".rstrip())
        withheld = [w for r in report for w in r["withheld"]]
        if withheld:
            a("//!")
            a("//! WITHHELD, and each of these shrinks the contract for EVERY")
            a("//! implementor at once -- a trait method must be supplied by all:")
            for w in sorted(set(withheld)):
                a(f"//!   - {w}")
        a("")
        for line in forms.get("imports", []):
            a(line)
        for mod in sorted(by_type[d]["module"] for d in used):
            a(forms.get("module_import", "use crate::{module};")
              .format(module=mod))
        a("")

        for r in emitted:
            a(f"/// Dispatch contract of C# `{r['base']}`, member for member of")
            a(f"/// what all {len(r['implementors'])} in-corpus implementor(s) "
              f"can supply.")
            a(spec.get("decl", "pub trait {name} {{").format(name=r["base"]))
            for m in r["methods"]:
                a(spec.get("method",
                           "    fn {name}(&mut self{extra}) -> {ret};")
                  .format(name=m["name"], extra=m["extra"], ret=m["ret"]))
            a("}")
            a("")

        for d in used:
            mod = by_type[d]["module"]
            ty = self.dispatch_receiver_name(d, mod)
            a(f"/// C# `{d}`, as something a trait can be implemented on: the")
            a("/// translated bodies are free functions, so the receiver is the")
            a("/// state they take, held together.")
            a(forms.get("receiver", "").format(ty=ty, module=mod))
            a("")
            a(forms.get("receiver_new", "").format(ty=ty, module=mod))
            a("")
            for r in emitted:
                if d not in r["implementors"]:
                    continue
                a(spec.get("impl_decl", "impl {trait} for {ty} {{}}")
                  .format(trait=r["base"], ty=ty))
                for m in r["methods"]:
                    a(spec.get("impl_method",
                               "    fn {name}(&mut self{extra}) -> {ret} {{}}")
                      .format(name=m["name"], extra=m["extra"], ret=m["ret"]))
                    args = "".join(
                        f", {p.split(':')[0].strip()}"
                        for p in m["extra"].split(",") if p.strip())
                    a(forms.get("forward", "").format(
                        module=mod, target=m["forwards"][d], args=args))
                    a("    }")
                a("}")
                a("")
        return "\n".join(L).rstrip() + "\n", report

    @staticmethod
    def dispatch_receiver_name(type_name: str, module: str) -> str:
        """A Rust type name for the receiver, derived from the MODULE name.

        From the module rather than from the C# type, because the module name is
        already the one the emitter chose for this translation unit and two
        modules cannot share it. Deriving it from the C# name instead would let
        two types in different namespaces produce one Rust type (E0428).
        """
        return "".join(p.capitalize() for p in module.split("_"))

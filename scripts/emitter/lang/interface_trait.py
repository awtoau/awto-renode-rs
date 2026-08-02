"""A C# interface as a Rust trait -- COMPLETE, or not at all.

LANGUAGE LAYER -- see `scripts/check_layering.py`.

Generic C#. Everything this module knows about the input it asks the corpus
database: which types are interfaces, what members they declare, what they
inherit. The templates come from `interface_traits` in the language rules.

WHY COMPLETE OR NOTHING
-----------------------
A trait named after a C# interface but missing members is not that interface.
It compiles, it looks finished, and every downstream decision made against its
shape is made against a shape that changes the next time a type mapping lands.
So a trait is emitted only when EVERY declared member and EVERY inherited
interface can be expressed; otherwise it is withheld and each member's blocker
is reported by name and reason.

That makes the withheld set a measurement rather than an opinion:
`scripts/interface_census.py` reads the same analysis this emitter uses, so the
published table cannot disagree with what the converter does.

WHAT BLOCKS A MEMBER
--------------------
Each reason is a distinct class of work, and they must not be blurred:

  `type_not_in_corpus`      the named C# type was never ingested -- its shape
                            is unknown, so no mapping can be right. Widening
                            the ingest fixes it; a converter change cannot.
  `type_without_definition` the type IS in the corpus but no Rust definition is
                            emitted for it yet. The mapping exists (D1); the
                            target does not, so emitting would not compile.
  `generic_method`          the member carries its own type parameters. D1
                            holds interface-typed fields as `dyn`, and a
                            generic method makes a trait non-object-safe, so
                            `dyn` would stop compiling. `where Self: Sized`
                            keeps object safety by making the method
                            uncallable through `dyn`, which is a member that
                            silently is not there -- the failure this module
                            exists to prevent.
  `overload`                two members share a name. Rust traits have one
                            method per name, and no rule yet assigns the
                            disambiguating names call sites would have to use;
                            inventing them here would break every caller.
  `unmapped_type`           in the corpus or the BCL, with no mapping rule.

A C# EVENT
----------
`event` is a subscribe/unsubscribe pair over a multicast delegate. The language
rules already narrow a multicast delegate to ONE subscriber (see
`stdlib.delegates.note`), and this follows that narrowing: an event becomes one
subscribe method, and the file says so in its header. `-=` has no form here,
because a boxed closure has no identity to remove by.
"""

from __future__ import annotations

from emitter.core import snake
from emitter.lang.types import split_args as _split_args

# Accessor prefixes C# generates for a property. Recognised so a property is
# emitted ONCE, from its accessors, rather than twice under two spellings.
GET, SET = "get_", "set_"


def _type_params(key: str) -> list[str]:
    """Type parameter names from a declaration key, e.g. `N.Foo<T, U>`."""
    if "<" not in key or not key.rstrip().endswith(">"):
        return []
    inner = key[key.index("<") + 1:key.rindex(">")]
    return [p.strip() for p in _split_args(inner) if p.strip()]


def _bare(key: str) -> str:
    """A declaration key without its namespace or type arguments."""
    head = key.split("<")[0]
    return head.split(".")[-1]


class InterfaceTrait:
    """Mixin: C# interfaces as Rust traits."""

    # ---------------------------------------------------------------- corpus

    def interface_rows(self) -> list[tuple[int, str, str]]:
        """Every interface in the corpus, as (id, name, key), key order.

        Ordered by key, not name: one corpus holds several declarations sharing
        a short name (a generic one and its non-generic sibling), and iteration
        order must not depend on which row the database returns first.
        """
        return self.con.execute(
            "SELECT id, name, key FROM type WHERE kind='interface' "
            "ORDER BY key").fetchall()

    def _kind_of(self, cs: str) -> tuple[str | None, str | None]:
        """(kind, key) of a declared C# type, resolved by FULLY QUALIFIED key.

        Never by short name. A corpus holds several distinct types sharing one,
        and matching on it made a library type resolve to an unrelated
        declaration that happened to share the last segment -- reported as "we
        hold this type but emit no definition" when the truth was "this is a
        library type with no mapping". Two different pieces of work, and the
        wrong one named.

        The `LIKE` arm is generic arity, not a short name: a declaration is
        keyed with its parameters and a use site names its arguments.
        """
        cache = getattr(self, "_iface_kind_cache", None)
        if cache is None:
            cache = self._iface_kind_cache = {}
        if cs in cache:
            return cache[cs]
        row = self.con.execute(
            "SELECT kind, key FROM type WHERE key=? OR key LIKE ? "
            "ORDER BY LENGTH(key) LIMIT 1", (cs, cs + "<%")).fetchone()
        cache[cs] = (row[0], row[1]) if row else (None, None)
        return cache[cs]

    # ------------------------------------------------------------- resolving

    def _trait_resolver(self, params: set[str], defined: set[str],
                        blockers: list[dict]):
        """A leaf resolver for `rust_type`, recording WHY a leaf did not map.

        `rust_type` owns the decomposition of arrays, nullables and generic
        families; this only answers for a leaf it has no rule for, so there is
        one type-mapping engine rather than two that can disagree.
        """
        spec = self.language.get("interface_traits", {})

        def resolve(name: str, args: tuple[str, ...] = ()) -> str | None:
            short = _bare(name)
            if short in params and not args:
                return short                      # the declaration's own parameter
            kind, key = self._kind_of(name)
            if kind is None:
                # A BCL type and an un-ingested one are different work: one
                # needs a mapping rule, the other needs a wider ingest. Told
                # apart by the namespace roots named in the rules.
                roots = tuple(spec.get("bcl_namespaces", ()))
                blockers.append({"type": name,
                                 "reason": "bcl_unmapped"
                                 if name.startswith(roots) else
                                 "type_not_in_corpus"})
                return None
            if kind == "interface":
                if _bare(key) not in defined:
                    blockers.append({"type": name,
                                     "reason": "interface_withheld",
                                     "detail": _bare(key)})
                    return None
                form = spec.get("object_ref")
                if not form:
                    blockers.append({"type": name, "reason": "unmapped_type"})
                    return None
                inner = _bare(key)
                if args:
                    inner += "<" + ", ".join(args) + ">"
                return form.format(name=inner)
            blockers.append({"type": name, "reason": "type_without_definition",
                             "detail": kind})
            return None

        return resolve

    def _map(self, cs: str, resolve) -> str | None:
        """One C# type through `rust_type`, with the resolver installed."""
        prev = getattr(self, "_type_resolver", None)
        self._type_resolver = resolve
        try:
            return self.rust_type(cs)
        finally:
            self._type_resolver = prev

    # -------------------------------------------------------------- analysis

    def interface_analysis(self, tid: int, name: str, key: str,
                           defined: set[str],
                           colliding: set[str] = frozenset()) -> dict:
        """Every member of one interface, mapped or blocked, with reasons.

        `defined` is the set of interface names that will exist in Rust; a
        member referring to one outside it is blocked, because a signature
        naming a trait the file does not contain does not compile.

        Never empty: an interface with no members still reports its bases.
        """
        spec = self.language.get("interface_traits", {})
        params = _type_params(key)
        pset = set(params)
        members = self.con.execute(
            "SELECT mb.id, mb.name, mb.kind, mb.key, mb.declared_type, "
            "       m.return_type "
            "FROM member mb LEFT JOIN method m ON m.member_id = mb.id "
            "WHERE mb.type_id = ? ORDER BY mb.name, mb.key", (tid,)).fetchall()

        # A property is declared TWICE in the corpus -- once as the property and
        # once per accessor method. The accessors carry the parameter list, so
        # they are the emitted form and the property row is dropped; a property
        # whose accessors are absent is reported rather than skipped.
        method_names = {n for _i, n, k, *_ in members if k == "method"}
        entries: list[dict] = []
        names_seen: dict[str, int] = {}
        for mid, mname, kind, mkey, dtype, rtype in members:
            if kind == "property":
                if GET + mname in method_names or SET + mname in method_names:
                    continue
                entries.append({"member": mname, "kind": "property",
                                "csharp": f"{dtype} {mname}",
                                "blockers": [{"type": mname,
                                              "reason": "property_without_accessor"}],
                                "rust": None})
                continue
            entries.append(self._member_entry(
                mid, mname, kind, mkey, dtype, rtype, pset, defined, spec))
        for e in entries:
            if e.get("fn"):
                names_seen[e["fn"]] = names_seen.get(e["fn"], 0) + 1
        for e in entries:
            if e.get("fn") and names_seen[e["fn"]] > 1:
                e["rust"] = None
                e["blockers"] = e["blockers"] + [
                    {"type": e["member"], "reason": "overload"}]

        bases: list[dict] = []
        resolve = None
        for (bname,) in self.con.execute(
                "SELECT interface_name FROM type_implements WHERE type_id=? "
                "ORDER BY interface_name", (tid,)):
            blockers: list[dict] = []
            resolve = self._trait_resolver(pset, defined, blockers)
            rust = self._super_trait(bname, pset, defined, blockers, resolve)
            bases.append({"csharp": bname, "rust": rust, "blockers": blockers})

        blocked = [e for e in entries if e["rust"] is None]
        # C# overloads a type NAME on generic arity; Rust does not. Two
        # declarations sharing a name would emit one trait twice (E0428), so
        # both are withheld: renaming one needs a name-manager rule that call
        # sites use too, which is not this construct's decision to make.
        own: list[dict] = ([{"type": name, "reason": "name_collision"}]
                           if name in colliding else [])
        return {
            "name": name,
            "key": key,
            "type_params": params,
            "members_declared": len(members),
            # Counted per MEMBER, and unaffected by a blocker on the
            # declaration: a name collision withholds the trait without making
            # its members inexpressible, and merging the two would report a
            # naming problem as a mapping problem.
            "members_emitted": len(entries) - len(blocked),
            "members_blocked": len(blocked),
            "blockers": own,
            "bases": bases,
            "members": entries,
            "complete": (not own and not blocked
                         and all(b["rust"] for b in bases)),
        }

    def _member_entry(self, mid, mname, kind, mkey, dtype, rtype,
                      pset, defined, spec) -> dict:
        """One member: the Rust line it becomes, or the reasons it does not."""
        blockers: list[dict] = []
        resolve = self._trait_resolver(pset, defined, blockers)
        cs_sig = mkey or mname
        entry: dict = {"member": mname, "kind": kind, "csharp": cs_sig,
                       "rust": None, "blockers": blockers, "warn": []}
        # Drain anything an earlier member queued, so a marker cannot be
        # attributed to the wrong signature.
        self.take_type_warnings()

        # `Foo<T>(...)` in the member key: the METHOD declares type parameters
        # of its own, which is not the same thing as being declared on a generic
        # type. Detected from the key rather than from the parameter types, so
        # a parameter merely NAMED T cannot be mistaken for one.
        head = (mkey or "").split("(")[0]
        if head.endswith(">") and "<" in head.split(".")[-1]:
            blockers.append({"type": mname, "reason": "generic_method"})
            return entry

        if kind == "event":
            form = spec.get("event")
            handler = self._map(dtype or "", resolve)
            if not form or handler is None:
                # Never silent: the resolver records a reason for every leaf it
                # cannot map, and this covers the case where the failure was
                # not a leaf at all -- a missing template.
                if not blockers:
                    blockers.append({"type": dtype or mname,
                                     "reason": "unmapped_type"})
                return entry
            entry["fn"] = spec.get("event_name", "subscribe_{name}").format(
                name=snake(mname))
            entry["rust"] = form.format(name=entry["fn"], handler=handler)
            entry["deviation"] = "event_subscribe_only"
            # The narrowing is a WARNING, not a gap: the method emits and one
            # subscriber does work. What is missing is `-=` and the second
            # subscriber, so the CLAIM is what has to change, not the emission.
            wid = spec.get("event_warning")
            entry["warn"] = ([wid] if wid else []) + self.take_type_warnings()
            return entry

        ret_cs = rtype if rtype is not None else dtype
        ret = ("()" if (ret_cs or "void") == "void"
               else self._map(ret_cs or "", resolve))
        extra = ""
        for pname, ptype, is_out, is_ref in self.con.execute(
                "SELECT name, type, is_out, is_ref FROM parameter "
                "WHERE method_id=? ORDER BY ordinal", (mid,)):
            prt = self._map(ptype or "", resolve)
            if prt is None:
                continue                       # the resolver recorded the reason
            if is_out or is_ref:
                prt = spec.get("by_ref", "&mut {inner}").format(inner=prt)
            extra += spec.get("param", ", {name}: {type}").format(
                name=snake(pname), type=prt)
        if ret is None or blockers:
            if not blockers:
                blockers.append({"type": ret_cs or mname,
                                 "reason": "unmapped_type"})
            return entry

        # A C# property becomes a getter and a setter, named apart. Both halves
        # are real members: collapsing them onto one name drops one of them.
        if mname.startswith(GET):
            entry["fn"] = snake(mname[len(GET):])
        elif mname.startswith(SET):
            entry["fn"] = spec.get("setter_name", "set_{name}").format(
                name=snake(mname[len(SET):]))
        else:
            entry["fn"] = snake(mname)
        entry["rust"] = spec.get("method",
                                 "    fn {name}(&mut self{extra}) -> {ret};") \
            .format(name=entry["fn"], extra=extra, ret=ret)
        # A parameter or return type whose mapping is not an equivalence marks
        # the signature it appears in. Only reached when the member EMITS: a
        # blocked one returned above and is reported as a gap instead.
        entry["warn"] = self.take_type_warnings()
        return entry

    def _super_trait(self, bname, pset, defined, blockers, resolve) -> str | None:
        """A base interface as a Rust supertrait bound, or None with a reason."""
        head = bname.split("<")[0]
        kind, key = self._kind_of(head)
        if kind != "interface":
            blockers.append({"type": bname, "reason": "type_not_in_corpus"})
            return None
        if _bare(key) not in defined:
            blockers.append({"type": bname, "reason": "interface_withheld",
                             "detail": _bare(key)})
            return None
        out = _bare(key)
        if "<" in bname:
            args = []
            for a in _split_args(bname[bname.index("<") + 1:bname.rindex(">")]):
                m = a.strip()
                # A base's type argument is a TYPE, not a value slot: the
                # object-graph wrapper belongs on a field, not on `Trait<T>`.
                mapped = (m if m in pset else self._plain(m, blockers))
                if mapped is None:
                    return None
                args.append(mapped)
            out += "<" + ", ".join(args) + ">"
        return out

    def _plain(self, cs: str, blockers: list[dict]) -> str | None:
        """A supertrait's type argument, mapped WITHOUT the object-graph wrapper.

        `Trait<u64>` is a bound; wrapping the argument would make it
        `Trait<Rc<RefCell<...>>>`, which is a different trait and would compile
        while meaning something else. So only a by-value mapping is accepted
        here, and anything else is reported rather than approximated.
        """
        prev = getattr(self, "_type_resolver", None)
        self._type_resolver = lambda name, args=(): None
        try:
            direct = self.rust_type(cs)
        finally:
            self._type_resolver = prev
        if direct is None:
            blockers.append({"type": cs,
                             "reason": "type_argument_without_value_form"})
        return direct

    # -------------------------------------------------------------- emission

    def interface_report(self) -> list[dict]:
        """Analyse every interface in the corpus, to a fixpoint on `defined`.

        An interface is emittable only if the interfaces it names are, so the
        set shrinks until it stops changing. Starting from "all of them" and
        removing is what lets a mutually-referring pair survive together
        instead of both being dropped for referring to each other.
        """
        rows = self.interface_rows()
        counts: dict[str, int] = {}
        for _t, name, _k in rows:
            counts[name] = counts.get(name, 0) + 1
        colliding = {n for n, c in counts.items() if c > 1}
        defined = {name for _t, name, _k in rows} - colliding
        report: list[dict] = []
        for _ in range(len(rows) + 1):
            report = [self.interface_analysis(tid, name, key, defined, colliding)
                      for tid, name, key in rows]
            still = {r["name"] for r in report if r["complete"]}
            if still == defined:
                break
            defined = still
        return report

    def emit_interface_traits(self) -> tuple[str, list[dict]]:
        """The whole trait module, plus the analysis it was built from.

        Every interface that can be expressed COMPLETELY is emitted; every one
        that cannot is named in the header with the count and the reasons, so
        the file states what it does not contain as plainly as what it does.
        """
        spec = self.language.get("interface_traits", {})
        # `interface_report` runs the member analysis to a fixpoint, so a member
        # is entered several times and each round queues its type warnings
        # afresh. Drained here so what reaches the emitted members is this
        # round's, not every round's.
        report = self.interface_report()
        self.take_type_warnings()
        L: list[str] = []
        a = L.append
        a("//! C# interfaces as Rust traits, GENERATED from the corpus.")
        a("//!")
        a("//! Do not edit: `scripts/check_generated.py` fails the commit if this")
        a("//! file differs from converter output. To change it, change the rules")
        a("//! in `rulesdb/rules/` or the C# it is derived from.")
        a("//!")
        a("//! A trait here is COMPLETE: every member the C# interface declares,")
        a("//! and every interface it inherits. One that cannot be complete is")
        a("//! withheld whole and listed below -- a trait missing members would")
        a("//! carry a name it does not live up to.")
        withheld = [r for r in report if not r["complete"]]
        emitted = [r for r in report if r["complete"]]
        if withheld:
            a("//!")
            a("//! WITHHELD, with the count of members that cannot be expressed:")
            for r in withheld:
                reasons = sorted({b["reason"] for e in r["members"]
                                  for b in e["blockers"]}
                                 | {b["reason"] for base in r["bases"]
                                    for b in base["blockers"]}
                                 | {b["reason"] for b in r["blockers"]})
                # Keyed, not named: two declarations can share a short name,
                # and that is itself one of the reasons a trait is withheld.
                bad_bases = sum(1 for b in r["bases"] if not b["rust"])
                a(f"//!   - {r['key']}: {r['members_blocked']} of "
                  f"{len(r['members'])} member(s) and {bad_bases} of "
                  f"{len(r['bases'])} inherited interface(s) blocked "
                  f"-- {', '.join(reasons) or 'none'}")
            a("//!")
            a("//! Per-member reasons: docs/status/interfaces.md, derived by")
            a("//! scripts/interface_census.py from this same analysis.")
        if any(e.get("deviation") == "event_subscribe_only"
               for r in emitted for e in r["members"]):
            a("//!")
            a("//! DEVIATION: a C# `event` is emitted as ONE subscribe method.")
            a("//! `-=` has no form -- a boxed closure has no identity to remove")
            a("//! by -- and the multicast narrowing is the one already recorded")
            a("//! in stdlib.delegates.")
        # Spliced at the end: the marked members are emitted below, so a summary
        # written here would list none of them.
        warn_at = len(L)
        a("")
        for r in emitted:
            bounds = [b["rust"] for b in r["bases"] if b["rust"]]
            gen = ("<" + ", ".join(r["type_params"]) + ">"
                   if r["type_params"] else "")
            decl = spec.get("decl", "pub trait {name}{params}{bounds} {{").format(
                name=r["name"], params=gen,
                bounds=(": " + " + ".join(bounds)) if bounds else "")
            a(f"/// C# `{r['key']}`, member for member.")
            a(decl)
            for e in r["members"]:
                if e["rust"]:
                    for wid in e.get("warn", []):
                        for line in self.warn_line(wid, 1):
                            a(line)
                    a(e["rust"])
            a("}")
            a("")
        summary = self.warning_summary(L[warn_at:])
        if summary:
            L[warn_at:warn_at] = [
                "//!",
                "//! WARNINGS -- these DID emit, and their semantics DIFFER from",
                "//! the source. Marked at every site, not only summarised here:",
                # `!` and not `-`: a `//!   - ` line is counted as a GAP by
                # three separate tools, and a warning is the opposite of a gap.
                *[f"//!   ! {s}" for s in summary]]
        return "\n".join(L).rstrip() + "\n", report

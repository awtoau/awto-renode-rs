"""Severity tiers, and the marker a WARNING leaves in the emitted output.

LANGUAGE LAYER -- generic mechanism, no corpus knowledge. See check_layering.py.

Why this exists
---------------
There was ONE marker class. A `/* GAP */` means the converter could not express
something, and the member is WITHHELD -- so a gap is loud, countable, and can
never be mistaken for a translation. There was no way at all to say the other
thing:

    this DID emit, and its semantics differ from the source.

Three mappings were in exactly that position, each one described accurately in
its rule file and invisible everywhere else: a sort that discards its key
selector and does not sort, a lazy sequence materialised eagerly, and a
multicast subscribe/unsubscribe pair collapsed to a single subscribe. Prose in a
JSON file cannot be counted, cannot be grepped in the output, and cannot fail a
build, so all three read as faithful mappings to anyone reading the Rust.

The mechanism already existed for exactly one of them and was never generalised:
the `lock` mapping emits a marker comment at every site it touches. This is that
mechanism, made general -- a severity on the mapping, a marker in the output, and
a number that can be ratcheted.

Tiers
-----
  faithful   equivalence is claimed. No marker; the ordinary case.
  warning    it emitted, and the semantics DIFFER. Marker at the site.
  bug        the SOURCE is defective and this reproduces the defect. Marker at
             the site, under its own tag. See below.
  gap        it did not emit. The member is withheld and the reason is in the
             file header. Handled elsewhere; named here so the ladder is one
             ladder rather than two unrelated ones.

The bug tier, and why it is not the warning tier
------------------------------------------------
A warning says `our mapping is narrower than the source`. That is a statement
about the converter, it is countable, and the count is meant to fall as the
converter improves.

A bug says `the source is narrower than the thing it models`. That is a
statement about the INPUT. It is not ours to fix -- fidelity is the default
precisely because the oracle certifies equivalence with the source, so a
corrected output is a FAILED output. Sharing a tag would put a number that must
not fall into a ratchet built to make numbers fall.

The tier lives here because `the source has a defect` is a fact about
translating anything. Every INSTANCE names a construct of one corpus, so
instances are read from the PROJECT layer and nothing in this file knows one.

Everything about a marker is DATA
---------------------------------
The tag, the identifier, the text and the templates all come from the rule
documents. Nothing here knows the name of any individual deviation or defect,
so adding one is an edit to the data, and a census can enumerate them by
reading the same table the emitter did rather than by grepping for a string
somebody remembered.

A marker is a COMMENT. It must never change what the output does -- the moment a
marker can break a build, the pressure is to stop emitting markers.
"""

from __future__ import annotations


class Severity:
    """Mixin: render and record deviation markers."""

    def severity_spec(self) -> dict:
        return self.language.get("severity", {})

    def warning_spec(self, wid: str) -> dict | None:
        return self.severity_spec().get("warnings", {}).get(wid)

    def _tier(self, name: str) -> dict:
        return self.severity_spec().get("tiers", {}).get(name, {})

    def _render(self, wid: str, form: str) -> str | None:
        spec = self.warning_spec(wid)
        if spec is None:
            # Never silent. A marker asked for by an identifier the data does
            # not define would otherwise emit nothing, which reads exactly like
            # a mapping with no deviation to declare.
            raise KeyError(
                f"severity.warnings has no entry `{wid}` -- an emitter asked "
                f"for a marker the rule data does not define, and an absent "
                f"marker is indistinguishable from a faithful mapping")
        tier = self._tier("warning")
        template = tier.get(form)
        if not template:
            return None
        return template.format(tag=spec.get("tag", tier.get("default_tag", "WARN")),
                               id=wid, text=spec.get("text", ""))

    def warn_line(self, wid: str, indent: int = 0) -> list[str]:
        """The marker as its own comment line(s), above what it is about."""
        text = self._render(wid, "line")
        return [] if text is None else ["    " * indent + text]

    def warn_inline(self, wid: str) -> str:
        """The marker as a block comment, for expression position."""
        return self._render(wid, "inline") or ""

    def warning_tag(self, wid: str) -> str:
        """`TAG(id)` -- the greppable head of every marker for this deviation."""
        spec = self.warning_spec(wid) or {}
        return (f"{spec.get('tag', self._tier('warning').get('default_tag', 'WARN'))}"
                f"({wid})")

    def count_warnings(self, text) -> dict[str, int]:
        """Marked sites per identifier, COUNTED FROM THE EMITTED TEXT.

        Counted from the output rather than from calls to `warn_line`, and the
        difference is not pedantry: a marker rendered into a method that is
        later WITHHELD was rendered and never landed. Counting the calls said
        one site; the file contained none. A count that can disagree with the
        file is the kind of number this project already has enough of.

        It also gives the emitter and any census one definition of `a marked
        site` instead of two that drift.
        """
        if not isinstance(text, str):
            text = "\n".join(text)
        out: dict[str, int] = {}
        for wid in self.severity_spec().get("warnings", {}):
            n = text.count(self.warning_tag(wid))
            if n:
                out[wid] = n
        return out

    def note_type_warning(self, wid: str) -> None:
        """Queue a warning raised while mapping a TYPE.

        The type mapper is called from deep inside whoever is emitting a
        declaration and returns only a string, so it cannot place a marker
        itself. It queues, and the declaration emitter drains.
        """
        self._pending_warn = getattr(self, "_pending_warn", [])
        self._pending_warn.append(wid)

    def take_type_warnings(self) -> list[str]:
        """Drain what the type mapper queued, oldest first, without repeats."""
        pending = getattr(self, "_pending_warn", [])
        self._pending_warn = []
        out: list[str] = []
        for w in pending:
            if w not in out:
                out.append(w)
        return out

    def warning_summary(self, text) -> list[str]:
        """One line per distinct warning IN `text`, with its count, sorted."""
        counts = self.count_warnings(text)
        return [f"{self.warning_tag(wid)} x{counts[wid]}: "
                f"{(self.warning_spec(wid) or {}).get('text', '')}"
                for wid in sorted(counts)]

    # ---- the bug tier -------------------------------------------------
    #
    # Instances come from the PROJECT layer, because every one of them names a
    # construct of one corpus. Nothing below knows any of their names: a stanza
    # declares the site it belongs to and this matches on it, so adding a
    # defect is an edit to data.

    def bug_stanzas(self) -> list[dict]:
        """Every declared source defect, in a stable order.

        Sorted by id and not by file order: two runs must agree byte for byte,
        and `-j1` must agree with `-j31`.
        """
        got = getattr(self, "project", {}).get("bug_rules", [])
        return sorted((s for s in got if isinstance(s, dict)),
                      key=lambda s: s.get("id", ""))

    def bugs_at(self, owner: str | None, site_name: str | None) -> list[dict]:
        """Stanzas whose declared site is (`owner`, `site_name`).

        `owner` is the source type being emitted and `site_name` the named slot
        within it. Both must match: a stanza with neither would mark every
        output, which is how a marker stops meaning anything.

        The two site keys are `type` and `name` and nothing more specific,
        because this file may not know what kind of thing a corpus's named
        slots are.
        """
        if not owner or not site_name:
            return []
        out = []
        for s in self.bug_stanzas():
            site = s.get("site", {})
            if site.get("type") == owner and site.get("name") == site_name:
                out.append(s)
        return out

    def bug_mode(self, stanza: dict) -> str:
        """`fidelity` or `conformance` for one stanza.

        The stanza's own `mode` is the default and is always `fidelity` -- the
        oracle certifies equivalence with the source, so reproducing the defect
        is what a correct translation does. A caller switches one BY ID, never
        by editing the data, so the committed output cannot drift into
        conformance by someone forgetting to put a file back.
        """
        if stanza.get("id") in getattr(self, "conformance", set()):
            return "conformance"
        return stanza.get("mode", "fidelity")

    def _bug_render(self, stanza: dict, form: str) -> str | None:
        tier = self._tier("bug")
        template = tier.get(form)
        if not template:
            return None
        return template.format(
            tag=stanza.get("tag", tier.get("default_tag", "SRCBUG")),
            id=stanza.get("id", ""), text=stanza.get("text", ""))

    def bug_tag(self, stanza: dict) -> str:
        """`TAG(id)` -- the greppable head of every marker for this defect."""
        tier = self._tier("bug")
        return (f"{stanza.get('tag', tier.get('default_tag', 'SRCBUG'))}"
                f"({stanza.get('id', '')})")

    def bug_lines(self, owner: str | None, site_name: str | None,
                  indent: int = 0) -> list[str]:
        """Markers for every defect declared at this site, one per line.

        A stanza switched to conformance says so in its own marker rather than
        going quiet: the output then differs from the source ON PURPOSE, and
        that is the more dangerous of the two states to leave unlabelled.
        """
        out: list[str] = []
        for s in self.bugs_at(owner, site_name):
            text = self._bug_render(s, "line")
            if text is None:
                continue
            if self.bug_mode(s) == "conformance":
                text += "  [CONFORMANCE: this output DIVERGES from the source]"
            out.append("    " * indent + text)
        return out

    def count_bugs(self, text) -> dict[str, int]:
        """Marked sites per defect id, COUNTED FROM THE EMITTED TEXT.

        From the output and not from calls, for the same reason
        `count_warnings` is: a marker rendered into something later withheld
        was rendered and never landed.
        """
        if not isinstance(text, str):
            text = "\n".join(text)
        out: dict[str, int] = {}
        for s in self.bug_stanzas():
            n = text.count(self.bug_tag(s))
            if n:
                out[s.get("id", "")] = n
        return out

    def bug_summary(self, text) -> list[str]:
        """One line per distinct defect IN `text`, with its count, sorted."""
        by_id = {s.get("id", ""): s for s in self.bug_stanzas()}
        counts = self.count_bugs(text)
        return [f"{self.bug_tag(by_id[bid])} x{counts[bid]}: "
                f"{by_id[bid].get('text', '')}"
                for bid in sorted(counts) if bid in by_id]

    def conformance_fields(self, owner: str | None, site_name: str | None,
                           fields: list[dict]) -> list[dict]:
        """Apply every switched stanza's `refine_fields` action to `fields`.

        `fields` is a list of `{pos, width, mode}`. A stanza replaces the
        entries whose `(pos, width)` it names with the list it supplies, which
        is general enough to both NARROW a slot's access mode and SPLIT one
        slot into several. Anything else -- a defect whose correct behaviour is
        an event rather than a layout -- declares `action: unavailable` and
        this returns the input untouched, so `no expressible conformance` is a
        recorded state rather than a silent no-op.

        Nothing happens at all unless the stanza has been switched by id, so
        the committed output is unaffected by the presence of this code.
        """
        out = list(fields)
        for s in self.bugs_at(owner, site_name):
            if self.bug_mode(s) != "conformance":
                continue
            conf = s.get("conformance", {})
            if conf.get("action") != "refine_fields":
                continue
            for rep in conf.get("replace", []):
                nxt: list[dict] = []
                for f in out:
                    if f.get("pos") == rep.get("pos") and f.get("width") == rep.get("width"):
                        nxt.extend(dict(w) for w in rep.get("with", []))
                    else:
                        nxt.append(f)
                out = nxt
        return sorted(out, key=lambda f: f.get("pos", 0))

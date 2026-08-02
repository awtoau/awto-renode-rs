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
  gap        it did not emit. The member is withheld and the reason is in the
             file header. Handled elsewhere; named here so the ladder is one
             ladder rather than two unrelated ones.

A marker is a COMMENT. It must never change what the output does -- the moment a
marker can break a build, the pressure is to stop emitting markers.

Everything about a warning is DATA
----------------------------------
The tag, the identifier, the text and the templates all come from the rule
documents. Nothing here knows the name of any individual deviation, so adding
one is an edit to the data, and a census can enumerate them by reading the same
table the emitter did rather than by grepping for a string somebody remembered.
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

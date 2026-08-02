"""A rule's EMIT-SHAPE POSTCONDITION: a static check on the text it produced.

LANGUAGE LAYER -- generic mechanism, no corpus knowledge. See check_layering.py.

Why this exists
---------------
A rule until now said two things: what it MATCHES, and what it must NOT match
(`negative`). Both are statements about the INPUT. Nothing anywhere said what
the output was supposed to look like, so an emitter that produced plausible
nonsense produced it silently -- the defect class this project was founded on.
The historical example is a combinator in a translated file that the source
does not contain: behaviourally inert, so a 33,000-access trace could not see
it, and shaped like every other line, so review did not either.

Prior art: Oxidizer (PLDI 2025) writes each mapping rule as an inference rule
whose conclusion carries `code |> <expected target shape>` -- a static check
that the emitted text has the required form, applied at emit time, rejecting on
failure without needing an oracle. Their ablation puts the whole
rules-plus-checks architecture at 73% I/O-equivalence against 0% for a model
with repair and no rules.

The contract
------------
A postcondition is checkable FROM THE EMITTED TEXT ALONE. That is the whole
constraint, and it is what makes it runnable at emit time on every site rather
than on a sample. It may say nothing about the corpus, the input node, or any
state the emitter happens to hold -- if a predicate needs those, it is a
different mechanism and belongs elsewhere.

Predicates
----------
  emits_call        str or [str]. Each named function must appear as a CALL --
                    `name(` with a non-identifier character before it. Catches
                    a template that was retargeted at a different output
                    function than the rule claims to be about.

  combinators       int. Exactly this many chained calls at DEPTH ZERO -- the
                    `.foo(` links of the fluent chain the fragment is. Nested
                    calls inside arguments do not count, because they belong to
                    a different rule that emitted them. This is the predicate
                    that catches an emitter appending a link nobody asked for.

  arity             int. Argument count of the outermost call, split at depth
                    zero. Catches the opposite failure: a template that lost a
                    slot, so a bound input silently fell off the end.

  must_not_emit     [str]. Substrings that must not appear in the OUTPUT.
                    Distinct from `negative.emit_must_not_contain`, which is
                    checked against the TEMPLATE: a forbidden shape can arrive
                    through a substituted slot, and only the output shows that.

A violation is never a fact about the input
-------------------------------------------
It means the rule and the emitter disagree about what the rule produces, which
is a defect in one of them. So it RAISES rather than recording a gap: a gap
says "the converter knows it cannot do this", and that is not what happened.
"""

from __future__ import annotations

import re

CALL = re.compile(r"(?<![A-Za-z0-9_]) *([A-Za-z_][A-Za-z0-9_]*) *\(")

# The predicate keys this module understands. A postcondition naming anything
# else is a typo that would otherwise check nothing at all, which is the same
# silent no-op the whole file exists to remove.
KEYS = {"emits_call", "combinators", "arity", "must_not_emit", "why"}


class PostconditionViolation(Exception):
    """The emitted text does not have the shape its rule promised."""


def _top_level_calls(text: str) -> list[str]:
    """Names of the `.name(` links at bracket depth zero, in order.

    Depth-aware rather than a plain scan: an argument may itself be a call, and
    that call was emitted by whatever rule owns it. Counting it here would make
    one rule answerable for another's output.
    """
    out: list[str] = []
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "." and depth == 0:
            m = re.match(r"\.([A-Za-z_][A-Za-z0-9_]*) *\(", text[i:])
            if m:
                out.append(m.group(1))
        i += 1
    return out


def _outer_args(text: str) -> int | None:
    """Argument count of the first call, splitting commas at its own depth.

    None when the text is not a call at all -- the caller reports that as its
    own failure rather than reading it as zero arguments.
    """
    m = CALL.search(text)
    if not m:
        return None
    i = m.end()               # just past the opening bracket
    depth = 1
    args = 1
    seen = False
    while i < len(text) and depth:
        ch = text[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 1:
            args += 1
        if depth and not ch.isspace():
            seen = True
        i += 1
    return args if seen else 0


def check(name: str, post: dict, text: str) -> list[str]:
    """Every way `text` fails `post`. Empty list means the shape holds."""
    bad: list[str] = []
    unknown = sorted(set(post) - KEYS)
    if unknown:
        bad.append(f"{name}: postcondition names unknown predicate(s) "
                   f"{', '.join(unknown)} -- a key nothing reads checks nothing")

    want = post.get("emits_call")
    if want is not None:
        called = {m.group(1) for m in CALL.finditer(text)}
        for fn in ([want] if isinstance(want, str) else want):
            if fn not in called:
                bad.append(f"{name}: must emit a call to `{fn}`, and "
                           f"`{text}` calls {sorted(called) or 'nothing'}")

    n = post.get("combinators")
    if n is not None:
        links = _top_level_calls(text)
        if len(links) != n:
            bad.append(f"{name}: must emit exactly {n} combinator(s), and "
                       f"`{text}` has {len(links)}: {links}")

    a = post.get("arity")
    if a is not None:
        got = _outer_args(text)
        if got is None:
            bad.append(f"{name}: must emit a call of {a} argument(s), and "
                       f"`{text}` is not a call")
        elif got != a:
            bad.append(f"{name}: must emit a call of {a} argument(s), and "
                       f"`{text}` has {got}")

    for frag in post.get("must_not_emit", []):
        if frag in text:
            bad.append(f"{name}: must not emit `{frag}`, and it is in `{text}`")
    return bad


class Postcondition:
    """Mixin: enforce a rule's emit-shape postcondition at the moment it emits."""

    def assert_postcondition(self, rule: dict, text: str) -> str:
        """Return `text`, or raise if it does not have the promised shape."""
        post = rule.get("postcondition")
        if not post:
            return text
        bad = check(rule.get("name", "<unnamed>"), post, text)
        if bad:
            raise PostconditionViolation(
                "emit-shape postcondition FAILED -- the rule and the emitter "
                "disagree about what this rule produces:\n  "
                + "\n  ".join(bad)
                + (f"\n  why the shape is required: {post['why']}"
                   if post.get("why") else ""))
        self.postconditions_held = getattr(self, "postconditions_held", 0) + 1
        return text

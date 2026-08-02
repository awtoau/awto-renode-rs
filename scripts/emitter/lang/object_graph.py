"""C# reference-typed fields -> `Gc<T>`. Issue #57, phase 1.

LANGUAGE LAYER. Nothing here knows what is being translated: the question
"is this field a reference to another object" is answered from the declared
type and the corpus type table, and the answer is the same for any C# codebase.

The decision this removes
-------------------------

C# has one kind of object reference. Rust makes the translator choose one per
field -- `T`, `Box<T>`, `Rc<T>`, `Weak<T>`, an index -- and the choice is not
local: it depends on who else holds the object and whether the graph comes back
round. Measured on this corpus: 552 instance fields in the cut with 52
object-reference edges and 7 cycles; 15,216 fields tree-wide with 1,278 edges
and 63+ cycles. At 1,278 edges an owner/back-edge direction per field is not a
mechanical translation, and a wrong direction is a leak or a dangling handle --
neither of which a differential oracle can see.

So there is no choice: **every reference-typed field maps to `Gc<T>`**, and the
translated graph is exactly as cyclic as the source. The runtime is
`csharp-rt`'s `Gc`/`Heap`, an arena with typed indices and no `unsafe`.

What this rule does NOT claim
-----------------------------

It maps the FIELD. It does not emit the target type, and it does not emit the
`Trace` impl that the collector needs -- both belong to whole-type emission.
Until the target type exists there is nothing to point at, so this rule reports
a gap that names the mapping and the single thing blocking it, rather than
emitting a handle to a type that does not compile.

That is deliberate. A `Gc<SomethingNotEmittedYet>` would look finished and
would not build; a gap says what to do next.

Not every unmapped type is a reference: an enum or a struct is copied, a
delegate slot is a closure, a generic collection is the collection rule's
business. Each of those declines here and is left to the rule that owns it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

_SPEC: dict | None = None


def _repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def spec() -> dict:
    """The rule, from data. Loaded once.

    Read directly rather than through the driver's merged dictionaries: this is
    a language-layer document, and the driver merges only project-layer ones.
    A rule whose data is never loaded is a silent no-op, which is the failure
    mode this file is most at risk of.
    """
    global _SPEC
    if _SPEC is None:
        f = _repo_root() / "rulesdb" / "rules" / "object_graph.json"
        doc = json.loads(f.read_text())
        _SPEC = doc["object_graph"]
    return _SPEC


def element_type(declared: str) -> tuple[str, bool] | None:
    """Split a declared type into (short name, is_array), or None to decline.

    Declines on anything with generic arguments. `List<Foo>` is a collection of
    references, not a reference, and mapping it here would quietly claim to
    have solved the collection alongside the handle.
    """
    t = (declared or "").strip()
    if not t:
        return None
    is_array = t.endswith("[]")
    if is_array:
        t = t[:-2].strip()
    if "<" in t or ">" in t or t.endswith("[]"):
        return None          # generic, or an array of arrays: not this rule
    short = t.split(".")[-1].strip("?")
    if not short or not short[0].isalpha():
        return None
    return short, is_array


def is_reference_type(em, short: str) -> bool:
    """A class in the corpus, so a field of that type holds a reference.

    Classes only. An enum or a struct is a value and is copied on assignment,
    so it is not part of the object graph -- classifying one as a reference was
    a measured mistake in an earlier pass and inflated both the shared count and
    the edge list.

    Interfaces are references too, but they need a Rust type to stand for the
    implementation, which is a different rule; they are already reported
    separately by the driver and never reach here.
    """
    row = em.con.execute(
        "SELECT 1 FROM type WHERE name=? AND kind='class' LIMIT 1",
        (short,)).fetchone()
    return row is not None


def target_rust_type(em, short: str) -> str | None:
    """The emitted Rust type for a corpus type, or None if there is not one yet.

    Asks the driver, which owns the emitted-module layout. Absent that hook the
    answer is None and this rule reports a gap -- never a guessed name.
    """
    resolve = getattr(em, "emitted_type_name", None)
    return resolve(short) if callable(resolve) else None


def reference_field(em, field: str, declared: str) -> tuple[str | None, str | None]:
    """Map one field. Returns (rust type, gap); at most one is not None.

    (None, None) means "not mine" -- the caller falls through to whatever rule
    owns the shape. Returning a gap instead of nothing is the invariant from
    the work protocol: a path that emits nothing must say why.
    """
    s = spec()
    parsed = element_type(declared)
    if parsed is None:
        return None, None
    short, is_array = parsed
    if not is_reference_type(em, short):
        return None, None

    target = target_rust_type(em, short)
    form = s["map"]["array"] if is_array else s["map"]["scalar"]
    if target is None:
        # The mapping is decided; what is missing is the thing pointed at.
        return None, s["blocked_gap"].format(
            field=field,
            rust=form.format(target=short),
            target=short,
            handle=s["runtime"]["handle"])
    return form.format(target=target), None

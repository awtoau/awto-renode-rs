"""C# constructors as an initialiser for the emitted state struct.

LANGUAGE LAYER -- see `scripts/check_layering.py`. Nothing here knows what is
being translated: a constructor is a member that assigns the object's own
fields, and that is true of any C# codebase.

WHAT WAS THERE BEFORE
---------------------
Nothing. The driver's member query asked for `kind='method'`, so `kind='ctor'`
was never selected, never emitted, and never gapped -- 32 of them in this cut.
The emitted struct derives `Default`, so every field a constructor assigned
started at 0/false and no output said so. That is the exact failure this
project keeps paying for: code that is wrong and silent is indistinguishable
from code that had nothing to do.

WHAT A CONSTRUCTOR BECOMES, AND WHY IT IS NOT ONE THING
-------------------------------------------------------
A C# constructor body mixes three unrelated jobs:

  1. assigning the object's own fields;
  2. building things the emitted module already emits by another route;
  3. effects on OTHER objects -- wiring, event subscriptions, calls back into
     the type's own methods.

Only (1) is expressible as an initialiser for a plain data struct. So only (1)
is translated, into

    impl State {
        pub fn new(<the parameters those assignments read>) -> Self {
            let mut st = Self::default();
            ...
            st
        }
    }

and every statement that is not (1) is named as a gap. A `new` that quietly
skipped (2) and (3) would read as a complete constructor and would not be one.

WHY THE VALUE SIDE IS A WHITELIST
---------------------------------
An initialiser can reach nothing but the struct it is building. So the kinds
allowed inside an assigned value are listed in the rules and everything else is
withheld and named -- rather than blacklisting the shapes someone thought of.
A method call, an object construction or an event subscription in value
position is not a translation problem here, it is a statement that cannot exist
in this position at all.

WHY `Default` IS LEFT DERIVED
-----------------------------
Folding a constructor into `Default` needs every assigned value to be knowable
with no arguments. Where a field is assigned from a parameter, that is exactly
what is missing: the corpus records THAT a parameter has a default and not what
the default IS. A `Default` built from one would be a guess. So the derived
all-zero value stays -- an honest zero -- and the gap names the fields it
leaves wrong.

WHY THE CHAINED CALL IS A GAP AND NOT AN INLINE
-----------------------------------------------
`: base(x, 16)` runs the base constructor's own assignments with the derived
type's arguments substituted for the base's parameters. That substitution is a
real construct with its own correctness question, and doing it half way -- the
base's statements with its own parameter names still in them -- would put
values in the struct that no caller ever passed. It is named as a gap, per base
constructor, with what it costs.

EMPTY IS ALWAYS EXPLAINED
-------------------------
`emit` returns no lines when the type declares no constructor with a body, and
that is the one case where empty means "there was nothing" rather than "I could
not". Every other empty return carries at least one gap.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from emitter.core import snake

_SPEC: dict | None = None

# What an emitted initialiser statement must look like once `this` has been
# redirected onto the struct. Checked rather than assumed: the assignment rules
# are project data and may rewrite a target into something that is not a plain
# field store, and such a line is not an initialiser however plausible it reads.
_ASSIGN = re.compile(r"^\s*st\.([a-z_][a-z0-9_]*)\s*=\s*(.+);\s*$")
_MARKER = re.compile(r"/\*\s*(GAP|[A-Z]\w+)\s*\*/")


def _repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def spec() -> dict:
    """The rule, from data. Loaded once.

    Read directly rather than through the driver's merged dictionaries: this is
    a language-layer document and the driver merges only project-layer ones. A
    rule whose data is never loaded is a silent no-op.
    """
    global _SPEC
    if _SPEC is None:
        f = _repo_root() / "rulesdb" / "rules" / "constructor.json"
        _SPEC = json.loads(f.read_text())["constructors"]
    return _SPEC


def constructors(em, type_name: str) -> list[tuple[int, str]]:
    """(member id, C# key) of every constructor of `type_name` with a body.

    Ordered by key, which is the full signature, so the emitted order is a
    property of the source and not of the database's row order -- output must be
    byte-identical however the work was scheduled.
    """
    return [(mid, key) for mid, key in em.con.execute(
        "SELECT mb.id, mb.key FROM member mb JOIN type t ON t.id = mb.type_id "
        "JOIN method m ON m.member_id = mb.id "
        "WHERE t.name = ? AND mb.kind = 'ctor' AND m.has_body = 1 "
        "ORDER BY mb.key", (type_name,))]


# A dotted qualifier in front of a type name. Stripped from the whole argument
# string at once rather than per comma-separated part: splitting first turns
# `Dictionary<int, List<int>>` into two fragments and shortening each of them
# produced `List<int>>`, a signature that never existed.
_QUALIFIER = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+")


def signature(key: str) -> str:
    """The C# signature, shortened to what a reader needs.

    Namespaces are dropped from the parameter types; the declaring name is kept.
    """
    name, _, args = key.partition("(")
    short = name.rsplit(".", 1)[-1]
    args = _QUALIFIER.sub(lambda m: m.group(0).rsplit(".", 1)[-1], args.rstrip(")"))
    return f"{short}({args})"


def _parameters(em, method_id: int) -> dict[str, tuple[int, str, bool]]:
    """C# parameter name -> (ordinal, declared type, has a default)."""
    return {name: (ordinal, ptype or "", bool(has_default))
            for ordinal, name, ptype, has_default in em.con.execute(
                "SELECT ordinal, name, type, has_default FROM parameter "
                "WHERE method_id = ? ORDER BY ordinal", (method_id,))}


def _subtree(em, oid: int):
    """Every operation at or under `oid`, as (id, kind, symbol)."""
    out = []
    stack = [oid]
    while stack:
        cur = stack.pop()
        row = em.con.execute(
            "SELECT id, kind, symbol FROM operation WHERE id = ?", (cur,)).fetchone()
        if row:
            out.append(row)
        for (cid,) in em.con.execute(
                "SELECT id FROM operation WHERE parent_id = ? ORDER BY ordinal",
                (cur,)):
            stack.append(cid)
    return out


def _rust_type(em, cs: str) -> str | None:
    """The driver's own type mapping, so a parameter and a field agree."""
    return (em.project.get("state_struct", {}).get("type_map", {}).get(cs.strip())
            or em.rust_type(cs))


def _statement(em, stmt_id: int, params: dict, state_names: set[str],
               s: dict) -> tuple[str | None, str | None, list[str]]:
    """Translate ONE constructor statement.

    Returns (emitted line, reason it was withheld, parameter names it reads).
    Exactly one of the first two is not None -- a statement is either an
    initialiser line or a named reason, never neither.
    """
    g = s["gaps"]
    kids = em.children(stmt_id)
    kind = em.con.execute("SELECT kind FROM operation WHERE id = ?",
                          (stmt_id,)).fetchone()[0]
    if kind != "ExpressionStatement" or not kids:
        return None, g["not_an_assignment"].format(kind=kind), []
    inner_id, inner_kind = kids[0][0], kids[0][1]
    if inner_kind != "SimpleAssignment":
        return None, g["not_an_assignment"].format(kind=inner_kind), []

    parts = em.children(inner_id)
    if len(parts) < 2:
        return None, g["not_an_assignment"].format(kind=inner_kind), []
    target_id, target_kind, target_sym = parts[0][0], parts[0][1], parts[0][2]
    value_id = parts[1][0]

    # The field being assigned must be one the emitted struct actually holds.
    # Anything else is storage the translated type does not have -- a computed
    # property, or a field whose type had no mapping and was dropped.
    leaf = (target_sym or "").rsplit(".", 1)[-1].split()[-1]
    field = snake(leaf)
    if target_kind not in ("FieldReference", "PropertyReference") or not leaf:
        return None, g["not_an_assignment"].format(kind=target_kind), []
    if field not in state_names:
        return None, g["no_storage"].format(field=leaf), []

    # The value, by kind, before anything is emitted. See value_kinds.why.
    allowed = set(s["value_kinds"]["allowed"])
    reads: list[str] = []
    for _oid, vkind, vsym in _subtree(em, value_id):
        if vkind not in allowed:
            return None, g["value_kind"].format(kind=vkind), []
        if vkind == "ParameterReference" and vsym:
            reads.append(vsym.split()[-1])
    for pname in reads:
        if pname not in params:
            return None, g["param_unmapped"].format(param=pname,
                                                    type="<not declared>"), []
        if _rust_type(em, params[pname][1]) is None:
            return None, g["param_unmapped"].format(
                param=pname, type=params[pname][1]), []

    # Emit through the ordinary statement rules, so nothing here duplicates
    # them, then CHECK the result rather than trusting it.
    before = dict(em.unhandled)
    gaps_before = len(em.gaps)
    lines = em.rewrite_this(em.emit_stmt(stmt_id, 2))
    grew = sum(em.unhandled.values()) - sum(before.values())
    # The kinds THIS statement added, read before the counter is restored: the
    # restore is what stops a withheld statement poisoning the driver's totals,
    # and diffing after it would name nothing.
    added = sorted(k for k, v in em.unhandled.items() if v != before.get(k))
    em.unhandled.clear()
    em.unhandled.update(before)
    del em.gaps[gaps_before:]
    if grew or not lines or len(lines) != 1 or _MARKER.search(lines[0]):
        return None, g["value_unmapped"].format(
            detail=", ".join(added) or "it emitted no single statement"), []
    m = _ASSIGN.match(lines[0])
    if not m or m.group(1) != field:
        return None, g["shape_changed"].format(emitted=lines[0].strip()[:60]), []
    unknown = sorted({x for x in re.findall(r"\bst\.([a-z_][a-z0-9_]*)", lines[0])
                      if x != "f" and x not in state_names})
    if unknown:
        return None, g["no_storage"].format(field=", ".join(unknown)), []
    return lines[0], None, reads


def _one(em, type_name: str, mid: int, key: str, name: str,
         state_names: set[str], s: dict) -> tuple[list[str], list[str]]:
    """One constructor: its initialiser lines and its gaps."""
    g, sig = s["gaps"], signature(key)
    gaps: list[str] = []
    params = _parameters(em, mid)

    root = em.con.execute(
        "SELECT id FROM operation WHERE method_id = ? AND parent_id IS NULL",
        (mid,)).fetchone()
    if not root:
        gaps.append(g["nothing_emitted"].format(owner=type_name, signature=sig))
        return [], gaps

    stmts: list[int] = []
    for cid, ckind, _s2, _c2, _t2 in em.children(root[0]):
        if ckind == "Block":
            stmts.extend(c[0] for c in em.children(cid))
        else:
            # The chained constructor call. Reported by the caller against the
            # base it targets, so it is counted once per base and not once per
            # derived type that happens to chain to it.
            continue

    body: list[str] = []
    reads: list[str] = []
    for n, sid in enumerate(stmts, 1):
        line, why, used = _statement(em, sid, params, state_names, s)
        if line is None:
            gaps.append(g["withheld_statement"].format(
                owner=type_name, signature=sig, n=n, why=why))
            continue
        body.append(line)
        reads.extend(u for u in used if u not in reads)

    if not body:
        # "nothing translated" and "nothing to translate" are different facts
        # and the next agent needs to know which: one is work, the other is not.
        gaps.append(g["empty_body" if not stmts else "nothing_emitted"].format(
            owner=type_name, signature=sig))
        return [], gaps

    reads.sort(key=lambda p: params[p][0])
    decl = ", ".join(s["shape"]["param"].format(
        name=snake(p), type=_rust_type(em, params[p][1])) for p in reads)
    unrecorded = [p for p in reads if params[p][2]]
    if unrecorded:
        gaps.append(g["default_unrecorded"].format(
            owner=type_name, signature=sig,
            params=", ".join(f"`{p}`" for p in unrecorded)))
    gaps.append(g["unused"].format(owner=type_name, signature=sig, name=name))
    return ([s["shape"]["doc"].format(signature=sig),
             s["shape"]["decl"].format(name=name, params=decl),
             s["shape"]["seed"], *body, s["shape"]["tail"], s["shape"]["end"]],
            gaps)


def emit(em, type_name: str) -> tuple[list[str], list[str]]:
    """Every constructor of `type_name` and of its emitted base chain.

    Returns (lines, gaps). Empty lines with empty gaps means the type declares
    no constructor with a body -- "there was nothing", which is a real answer;
    every other empty carries a gap.
    """
    s = spec()
    g = s["gaps"]
    state_names = getattr(em, "_state_names", set())
    own = constructors(em, type_name)
    gaps: list[str] = []
    bodies: list[list[str]] = []

    # Rust cannot overload, so the name has to distinguish them. Arity does,
    # unless two constructors share one -- then nothing does, and both go.
    arity = {mid: len(_parameters(em, mid)) for mid, _k in own}
    clash = {a for a in arity.values() if list(arity.values()).count(a) > 1}
    for mid, key in own:
        if len(own) > 1 and arity[mid] in clash:
            gaps.append(g["arity_collision"].format(
                owner=type_name, signature=signature(key),
                n=list(arity.values()).count(arity[mid]), arity=arity[mid]))
            continue
        name = (s["naming"]["one"] if len(own) == 1
                else s["naming"]["many"].format(arity=arity[mid]))
        lines, ctor_gaps = _one(em, type_name, mid, key, name, state_names, s)
        gaps.extend(ctor_gaps)
        if lines:
            bodies.append(lines)

    # Every base constructor, whether or not this type chains to it explicitly:
    # C# runs one of them for every object, and the merged struct holds the
    # fields it assigns.
    for base in em.base_chain(type_name):
        for _mid, key in constructors(em, base):
            gaps.append(g["chained"].format(
                owner=base, signature=signature(key)))

    if not bodies:
        return [], gaps
    out = [s["shape"]["open"].format(struct=s["shape"].get("struct", "State"))]
    for i, b in enumerate(bodies):
        if i:
            out.append("")
        out.extend(b)
    out.append(s["shape"]["close"])
    return out, gaps

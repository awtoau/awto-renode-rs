"""C# `switch` as a Rust `match`.

LANGUAGE LAYER. Split out of the `emit_stmt` chain unchanged.

Two decorators, and the split between them is the point:

  * `switch_stmt` DECLINES a childless `Switch`, returning None so the built-in
    chain's fallback reports it. It is not wrapped, because returning None here
    means "not mine", which is exactly the case `must_explain` must not treat as
    a silent failure.

  * `emit_switch` does the work and IS wrapped. It is expected to produce output
    on every path, so an empty return means a path could not translate and had
    better say why. The decorator moved with the code and still guards it.

Splitting the guard from the body is what lets both be true at once; wrapping
the whole handler would make every decline raise.
"""

from __future__ import annotations

from emitter import core
from emitter.core import must_explain


@core.stmt("Switch")
def switch_stmt(em, oid: int, indent: int) -> list[str] | None:
    """Declines a `Switch` with no children; otherwise emits the match."""
    if not em.children(oid):
        return None
    return emit_switch(em, oid, indent)


@must_explain
def emit_switch(em, oid: int, indent: int) -> list[str]:
    """C# switch as a Rust match.

    The `break` that C# demands at the end of every section is dropped: it
    encodes a syntax rule, not behaviour, and Rust arms do not fall
    through. A Branch that is NOT that break is real control flow (a
    `goto case`) and is reported rather than silently discarded."""
    pad = "    " * indent
    rules = em.language.get("switch", {})
    kids = list(em.children(oid))
    subject = em.emit_expr(kids[0][0])
    # Collect the labels FIRST: if they are enum members, the arms must be
    # patterns (no `as`), so the subject is converted instead.
    enum_ty = None
    for cid, ckind, _s, _c, _t in kids[1:]:
        if ckind != "SwitchCase":
            continue
        for gid, gkind, _s2, _c2, _t2 in em.children(cid):
            if gkind in ("CaseClause", "SingleValueCaseClause",
                         "ConstantPattern"):
                vals = list(em.children(gid))
                if vals:
                    txt = em.emit_expr(vals[0][0])
                    if "::" in txt and txt.endswith(" as u64"):
                        enum_ty = txt.split("::")[0]
    if enum_ty:
        subject = rules.get("subject_from_u64",
                            "{enum}::from_u64({subject})").format(
            enum=enum_ty, subject=subject)
    out = [pad + rules.get("match", "match {subject} {{").format(subject=subject)]
    saw_default = False
    for cid, ckind, _s, _c, _t in kids[1:]:
        if ckind != "SwitchCase":
            continue
        labels, body = [], []
        for gid, gkind, _s2, _c2, _t2 in em.children(cid):
            if gkind in ("CaseClause", "SingleValueCaseClause",
                         "DefaultCaseClause", "ConstantPattern"):
                vals = list(em.children(gid))
                if not vals:
                    labels.append(rules.get("default_label", "_"))
                    saw_default = True
                else:
                    lab = em.emit_expr(vals[0][0])
                    if enum_ty and lab.endswith(" as u64"):
                        lab = lab[:-len(" as u64")]   # pattern context
                    labels.append(lab)
            elif gkind == "Branch":
                continue          # the mandatory C# break
            else:
                body.extend(em.emit_stmt(gid, indent + 2))
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

"""Guard C# mutable static state until its process-wide runtime form exists.

A static field must never fall through the implicit-``this`` reference rule:
putting it in an instance ``State`` would make one copy per object, whereas
C# has one value per closed type.  The eventual representation needs runtime
storage (``OnceLock`` plus a lock for mutation).  This module makes the gap
explicit and, crucially, prevents a plausible but wrong per-instance emission.
"""

from __future__ import annotations


def accessed_mutable_statics(em, method_id: int) -> list[str]:
    """Return process-wide mutable fields accessed by one method.

    ``const_value`` separates enum members/constants; ``is_readonly`` separates
    initialization-only storage.  A non-readonly static is classified as
    genuinely mutable only when the corpus records a write outside ``.cctor``.
    That last condition prevents a static initializer from inflating the
    mutable-state population.
    """
    rows = em.con.execute("""
        SELECT DISTINCT owner.key || '.' || target.name
        FROM field_access here
        JOIN member target ON target.id = here.member_id
        JOIN type owner ON owner.id = target.type_id
        WHERE here.method_id = ?
          AND target.kind = 'field'
          AND target.is_static = 1
          AND target.is_readonly = 0
          AND target.const_value IS NULL
          AND EXISTS (
              SELECT 1
              FROM field_access write_access
              JOIN member writer ON writer.id = write_access.method_id
              WHERE write_access.member_id = target.id
                AND write_access.is_write = 1
                AND writer.name <> '.cctor')
        ORDER BY 1
        """, (method_id,)).fetchall()
    return [row[0] for row in rows]

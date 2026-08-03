#!/usr/bin/env python3
"""Run the emitter over many types at once, and get the SAME BYTES as at -j1.

Why this exists
---------------
Removing the corpus cut took the corpus from 21,620 lines to 448,375, and the
number of emitted modules from 24 to 569. The census scripts kept emitting them
one `Emitter` at a time, so `gap_census.py` went to ~6 min and
`compile_check.py` to ~15 min. `compile_check --ratchet` is in the pre-commit
hook, which is how a slow check turns into a process defect rather than an
inconvenience: the last several commits were made with the hook SKIPPED.

CLAUDE.md is explicit that conversion wall-clock is the iteration speed, and
this repo has already found three checks that reported success while verifying
nothing. A hook that is bypassed is the same outcome by a different route.

This module is the shared driver loop. It is NOT part of the emitter: it
creates `Emitter` instances and collects what they return, and knows nothing
about what they emit.

THE CONSTRAINT: byte-identical at -j1 and the parallel default
----------------------------------------------
`emit_many` returns results in the order of the tasks it was given, never in
completion order. That is the whole guarantee, and it is not an accident of
`Executor.map` -- it is the reason `map` is used here instead of
`as_completed`, which would be faster to first result and silently wrong.

Silently wrong, specifically, because the output would still be VALID. A gap
census aggregated in completion order produces the same TOTAL with a different
tie-break order in `Counter.most_common` and a different "one example per
category" -- a real diff, in a file that looks entirely reasonable. That is the
worst failure available here, and it is the one `scripts/check_determinism.py`
exists to refuse.

So, three rules for anything using this module:

  1. Consume the returned list in order. Do not re-sort it by anything but a
     total order derived from the task list itself.
  2. Aggregate INTO the caller, in that order. A `Counter` summed in a
     different order has different `most_common` ties; a `dict.setdefault`
     filled in a different order keeps a different first example.
  3. Do not let a worker write to anything shared. Workers return values.

Processes, not threads
----------------------
This interpreter is a free-threading build with the GIL off, so threads would
in principle parallelise. They are not used, for two reasons:

  * `Emitter` carries mutable per-instance state (`self.gaps`, `self.unhandled`,
    `self._flag_fields`, `self._loop_env`, ...) and has never been audited for
    thread safety. Auditing it means changing it, and the emitter is owned by
    other work.
  * A process pool is correct on a GIL-enabled interpreter too. A thread pool
    would silently stop parallelising on one, and "silently stops doing its
    job" is the exact failure class this repo keeps paying for.

Each worker builds its OWN `Emitter` with its OWN read-only SQLite connection,
so nothing mutable is shared at all. Concurrent readers of one SQLite file are
safe: read-only (`mode=ro`) connections take shared locks for the duration of a
statement and no writer exists.

Work-stealing, not static partitioning
--------------------------------------
The machine is heterogeneous -- 8 P-cores and 16 E-cores -- so a static split
would leave the P-cores idle waiting on the E-cores. Tasks go onto one shared
queue with `chunksize=1`, so a worker takes the next type the moment it is
free and a fast core simply takes more of them. CLAUDE.md requires this.

Tasks are additionally handed out LONGEST-FIRST (`--no-lpt` to disable): the
corpus is wildly uneven -- one type emits 1,192 gaps and most emit none -- so
with tasks in name order the pool finishes in the time of whatever big type
happens to be last. Ordering by descending cost is the classic LPT scheduling
heuristic. It changes the ORDER WORK IS ISSUED, never the order results are
returned, so it cannot affect the output; `--no-lpt` exists so that can be
proved rather than asserted.
"""

from __future__ import annotations

import contextlib
import io
import logging
import multiprocessing
import os
import sqlite3
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # for `emitter`

#: Use the CPUs actually available to this process. On the development machine
#: one of the 32 logical CPUs is offline, so this correctly returns 31 instead
#: of creating a worker that can never run.
def default_jobs() -> int:
    return os.cpu_count() or 1


class Emitted(NamedTuple):
    """One type's result. Exactly one of `text` / `err_type` is set."""
    name: str
    method: str
    text: str | None
    err_type: str | None
    err_msg: str | None
    #: Wall seconds this type took. Reported on stderr only -- see `emit_many`. It
    #: is what makes the tail visible: with 569 uneven tasks the pool cannot
    #: finish sooner than its single longest type, so "why is it not 31x" is a
    #: question with an answer rather than a shrug.
    secs: float = 0.0
    #: Worker CPU seconds, distinct from wall time spent waiting on SQLite or
    #: scheduling. The old report called summed wall time "CPU", which could
    #: claim saturation without measuring any CPU use.
    cpu_secs: float = 0.0


# Set once per worker process by the initialiser, so the db path is not
# re-pickled with every one of 569 tasks.
_DB_URI: str | None = None


def process_context() -> multiprocessing.context.BaseContext:
    """Use a pool start method that works inside the repository sandbox.

    ``forkserver`` needs to bind a private Unix socket. The Codex/bwrap sandbox
    rejects that bind, so a nominal 32-worker run can fail before starting any
    worker (or appear to work only while an older fork server happens to
    survive). These CLI programs start the pool before creating any threads,
    making direct ``fork`` the simple Linux path. Non-POSIX hosts use spawn.
    """
    return multiprocessing.get_context("fork" if os.name == "posix" else "spawn")


def _init_worker(db_uri: str) -> None:
    global _DB_URI
    _DB_URI = db_uri
    # Import here so the cost is paid once per worker rather than per task, and
    # so a worker that cannot import fails at startup rather than 569 times.
    import emit  # noqa: F401


def _quiet_log() -> logging.Logger:
    """The same silent logger the serial drivers passed in.

    Named identically in every worker on purpose: `logging.getLogger` returns
    the one instance per process, and a NullHandler is idempotent.
    """
    log = logging.getLogger("quiet")
    if not log.handlers:
        log.addHandler(logging.NullHandler())
    return log


def _emit_one(task: tuple[str, str, str]) -> Emitted:
    """Emit one type in a worker. Returns; never raises, never writes."""
    name, method, tag = task
    from emit import Emitter
    t0 = time.monotonic()
    c0 = time.process_time()
    try:
        em = Emitter(sqlite3.connect(_DB_URI, uri=True), _quiet_log())
        # The serial drivers swallowed emitter chatter on stderr; keep doing
        # that, or 31 workers interleave it into an unreadable mess.
        with contextlib.redirect_stderr(io.StringIO()):
            out = em.emit_file(name, method, tag)
    except Exception as exc:                                   # noqa: BLE001
        return Emitted(name, method, None, type(exc).__name__, str(exc),
                       time.monotonic() - t0, time.process_time() - c0)
    return Emitted(name, method, out, None, None, time.monotonic() - t0,
                   time.process_time() - c0)


def _probe_one(name: str) -> tuple[str, list[str]]:
    """Which child types this type emits INSIDE itself, rather than beside it.

    A fresh `Emitter` per type, deliberately. The serial version reused one
    probe emitter for all 569, so each probe ran against whatever state the
    previous 568 left behind -- `sub_blocks` saves and restores the two fields
    it touches, but nothing enforced that. One emitter per type makes each
    probe independent of every other, which is the property the parallel
    version needs and the serial version only happened to have.
    """
    from emit import Emitter
    from emitter.plugins.sub_blocks import sub_blocks
    em = Emitter(sqlite3.connect(_DB_URI, uri=True), _quiet_log())
    with contextlib.redirect_stderr(io.StringIO()):
        found, _gaps = sub_blocks(em, name)
    return name, sorted({s["child"] for s in found})


def probe_nested(db: Path, names: Sequence[str], jobs: int) -> set[str]:
    """Types that exist only inside a parent module, so must not be emitted alone.

    A set, so the collection order is irrelevant by construction -- but the
    pool is still driven with `map` in name order, because "irrelevant by
    construction" is what the invented `.with_reserved(9, 23)` also looked like.
    """
    names = list(names)
    if not names:
        return set()
    db_uri = f"file:{db}?mode=ro"
    if jobs <= 1:
        _init_worker(db_uri)
        return {c for n in names for c in _probe_one(n)[1]}
    ctx = process_context()
    with ProcessPoolExecutor(max_workers=jobs, mp_context=ctx,
                             initializer=_init_worker,
                             initargs=(db_uri,)) as pool:
        return {c for _n, kids in pool.map(_probe_one, names, chunksize=4)
                for c in kids}


def emit_costs(con: sqlite3.Connection) -> dict[str, int]:
    """Rough per-type emit cost: how many operations its methods contain.

    Used only to decide the ORDER work is handed out. A wrong estimate costs
    wall-clock and nothing else, which is why a cheap proxy is enough.
    """
    return {name: n for name, n in con.execute("""
        SELECT t.name, COUNT(o.id) FROM type t
        JOIN member mb ON mb.type_id = t.id
        JOIN method m  ON m.member_id = mb.id
        LEFT JOIN operation o ON o.method_id = mb.id
        GROUP BY t.name""")}


def emit_many(db: Path, tasks: Sequence[tuple[str, str, str]], jobs: int,
              log: logging.Logger | None = None,
              lpt: bool = True) -> list[Emitted]:
    """Emit every `(type, method, tag)` in `tasks`. Result order == task order.

    `jobs <= 1` runs in this process with no pool at all. That is deliberate:
    it makes -j1 the plain serial path, so the determinism proof compares
    parallel output against real serial output rather than against a pool of
    one worker that shares the parallel path's bugs.
    """
    tasks = list(tasks)
    if not tasks:
        return []
    db_uri = f"file:{db}?mode=ro"

    if jobs <= 1:
        _init_worker(db_uri)
        return [_emit_one(t) for t in tasks]

    order = range(len(tasks))
    if lpt:
        con = sqlite3.connect(db_uri, uri=True)
        try:
            costs = emit_costs(con)
        finally:
            con.close()
        # Descending cost; ties broken by the ORIGINAL index so the issue order
        # is itself deterministic. It does not have to be -- results are
        # reordered below regardless -- but a scheduler that shuffles run to run
        # makes a timing regression impossible to attribute.
        order = sorted(order, key=lambda i: (-costs.get(tasks[i][0], 0), i))

    ctx = process_context()
    results: list[Emitted | None] = [None] * len(tasks)
    with ProcessPoolExecutor(max_workers=jobs, mp_context=ctx,
                             initializer=_init_worker,
                             initargs=(db_uri,)) as pool:
        # chunksize=1: one shared queue, each worker takes the next task when
        # it goes idle. Static chunking would bind slow E-core workers to a
        # fixed slice and idle the P-cores at the tail.
        issued = [tasks[i] for i in order]
        for i, res in zip(order, pool.map(_emit_one, issued, chunksize=1)):
            results[i] = res

    missing = [i for i, r in enumerate(results) if r is None]
    if missing:
        # Cannot happen via `map`, which yields exactly one result per input or
        # raises. Asserted anyway: a hole here would be a silently short census,
        # and a smaller number reads exactly like progress.
        raise RuntimeError(
            f"emit_many lost {len(missing)} of {len(tasks)} result(s) -- "
            "the pool returned fewer results than tasks")
    if log:
        crashed = sum(1 for r in results if r.err_type)
        log.info("emitted %d type(s) at -j%d, %d crash(es)",
                 len(results), jobs, crashed)
    return [r for r in results if r is not None]


def report_tail(results: Sequence[Emitted], log: logging.Logger,
                top: int = 8) -> None:
    """Say where the wall-clock went. STDERR/log only -- never stdout.

    The pool cannot finish before its single longest type, so a run that is
    5.8x rather than 31x faster is not a mystery to be shrugged at: it is one
    type on the critical path, and this names it.
    """
    if not results:
        return
    wall_sum = sum(r.secs for r in results)
    cpu_sum = sum(r.cpu_secs for r in results)
    worst = sorted(results, key=lambda r: (-r.secs, r.name))[:top]
    log.info("emit worker CPU %.0fs, summed task wall %.0fs over %d type(s); "
             "longest single type %.0fs "
             "(the floor no worker count can go below)",
             cpu_sum, wall_sum, len(results), worst[0].secs)
    for r in worst:
        log.info("    %-44s %6.1fs", r.name, r.secs)


def add_jobs_arg(ap) -> None:
    """`-j` with the same meaning everywhere. Used by the census scripts."""
    ap.add_argument("-j", "--jobs", type=int, default=default_jobs(),
                    help="emit workers (default: all cores; 1 = serial, "
                         "no pool)")
    ap.add_argument("--no-lpt", action="store_true",
                    help="issue tasks in task order instead of longest-first; "
                         "output must be identical either way")

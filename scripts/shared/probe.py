"""A named, logged path for audit probes that scan a whole table.

NORM31-PROD-REPORT.md §6d.3 is the reason this exists. The step-3 cooling
reading found the denormalized table's ``seq_scan`` up **+15** over fourteen
hours with zero index scans and zero row modifications, and the arithmetic said what
they were — 193,260 rows read ÷ 12,884 rows = exactly 15 whole-table scans,
the shape ``count(*)`` makes and not the shape the reconciler makes. That is a
sound *explanation* and it is not an *attribution*: no artifact named which
fifteen probes those were, because the probes were ad-hoc SQL typed into a
console, and ad-hoc SQL leaves counters moved and no trace of who moved them.

So §6d.3 asks for the counters to become evidence rather than argument: once
every audit probe issues its scan from a path that says so, a ``seq_scan``
delta with no matching ``audit_probe`` event is a *finding* — an unaccounted
reader — instead of a footnote reasoning about divisibility.

**Scope, deliberately small.** This logs and it counts. It is not a query
builder, not a probe registry, and not a wrapper anything is required to use;
its whole job is that a grep for ``audit_probe`` over a window returns the
list of scans an audit is responsible for. Two functions is the entire
surface, and if it ever needs a third that is a sign the attribution question
has changed shape and should be re-answered rather than extended.

``scripts/shared`` is not an entry-point directory: nothing here has a
``main()``, and ``tests/test_script_logging.py``'s guard globs ``scripts/*.py``
non-recursively for that reason. A caller still has to have called
``configure_script_logging()`` for these events to reach stdout.

Usage::

    from scripts.shared.probe import audit_probe, probe_count

    n = probe_count(db, "parcel_scenes", purpose="step-4 sweep, parity totals")
    audit_probe("pg_stat_user_tables", purpose="cooling-period counters")
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

logger = logging.getLogger("audit_probe")

# ``probe_count`` interpolates its table name, which no bind parameter can
# carry. The names an audit probes are literals in the calling script, never
# user input, but a validated identifier costs one regex and removes the
# question entirely rather than leaving it to a reviewer's judgement.
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def audit_probe(table: str, *, purpose: str, **fields: object) -> None:
    """Record that an audit is about to scan ``table``, and why.

    Emitted *before* the scan, so a probe that then fails still leaves the
    counter delta attributed. ``purpose`` is free text and is the field a
    reader actually uses — "which audit did this" is the question, and a
    caller name would answer a narrower one.
    """
    logger.info(
        "audit_probe",
        extra={"table": table, "purpose": purpose, **fields},
    )


def probe_count(db: Session, table: str, *, purpose: str, where: str | None = None) -> int:
    """``count(*)`` over a table, from a path that names itself first.

    ``where`` is appended verbatim and is for literal predicates written in
    the calling script; anything carrying a value belongs in a query of its
    own with bind parameters, not here.
    """
    if not _IDENTIFIER.match(table):
        raise ValueError(f"not a bare table identifier: {table!r}")
    audit_probe(table, purpose=purpose, where=where)
    sql = f"SELECT count(*) FROM {table}"  # noqa: S608  # identifier validated above
    if where:
        sql += f" WHERE {where}"
    return int(db.execute(sa_text(sql)).scalar() or 0)

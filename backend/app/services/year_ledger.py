"""The M4 per-year outcome ledger.

A ``timeline_request_tasks`` row says a source finished. It does not say what
happened to each year that source tried, so a task reaching ``complete`` with
twenty Landsat years missing looks exactly like one that got everything. Four
production occurrences, four hand-written heal scripts. This module is where
the per-year answer is written down.

Two rules shape it:

* **Every attempted group is recorded, not only the failures.** "Never tried"
  and "tried and came back empty" have to be different answers, and ``ok``
  rows make "has this ever succeeded" a plain aggregate.
* **It references no snapshot row.** The served row for a group is looked up
  by ``(parcel_id, source, group_key)`` at read time — rule 1 of
  docs/adr/0001-imagery-normalization.md.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import Uuid, bindparam
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Vocabulary ────────────────────────────────────────────────────────────────

OUTCOME_OK = "ok"
OUTCOME_FAILED = "failed"
OUTCOME_ABSENT = "absent"
OUTCOME_SUPPRESSED = "suppressed"
OUTCOME_INDETERMINATE = "indeterminate"

OUTCOMES = (
    OUTCOME_OK,
    OUTCOME_FAILED,
    OUTCOME_ABSENT,
    OUTCOME_SUPPRESSED,
    OUTCOME_INDETERMINATE,
)

# The reason vocabulary lives here, once, rather than as strings scattered
# through the loops — a typo in a heal script's WHERE clause is otherwise
# indistinguishable from "no rows match".
#
# failed      — the fetch was attempted and did not complete.
# absent      — the fetch completed and found nothing usable.
# suppressed  — a candidate existed and was deliberately not served.
# indeterminate — the code cannot tell failed from absent at this site. Its
#                 reason is free text naming that site, and every such site is
#                 a listed follow-up, not a category to design toward.
REASONS: dict[str, frozenset[str]] = {
    OUTCOME_OK: frozenset(),
    OUTCOME_FAILED: frozenset(
        {
            "sign_429",
            "sign_5xx",
            "stac_403",
            "stac_5xx",
            "read_timeout",
            "connect_error",
            "validation_failed",
            "other",
        }
    ),
    OUTCOME_ABSENT: frozenset(
        {
            "no_scenes",
            "all_cloud_filtered",
            "no_covering_item",
            "api_no_data",
        }
    ),
    OUTCOME_SUPPRESSED: frozenset(
        {
            "naip_no_point_coverage",
            # The imagery persist loop drops a selected group whose primary
            # item carries no COG asset (tasks/timeline.py). It was a silent
            # `continue` before the ledger.
            "no_cog_url",
            # The three topo item-level skips. Two of them are latent —
            # search_usgs_topo already filters to GeoTIFF-carrying products
            # and select_topo_items already drops unparseable years — so a
            # row with either reason means an upstream shape defeated a
            # filter, which is itself the finding (INVESTIGATION section 3e).
            "topo_no_source_id",
            "topo_no_geotiff_url",
            "topo_unparseable_date",
        }
    ),
    OUTCOME_INDETERMINATE: frozenset(),
}

# `failed` also takes `http_<status>` for an upstream that answered with a
# status rather than a transport error.  It is a family rather than an
# enumeration because the set of statuses an upstream can return is not ours
# to fix: what matters is that the status is *in* the reason, so a dead
# endpoint can never again be aggregated with genuine absence the way
# `1990/dec/sf1`'s 404 was.
_HTTP_REASON_RE = re.compile(r"^http_[1-5]\d\d$")

DETAIL_MAX_CHARS = 500


@dataclass(frozen=True)
class GroupNote:
    """One period's outcome, decided somewhere with no database session.

    Carried back from the pure-service layer (the STAC validation walk) to
    the task layer, which owns the session and writes it down.
    """

    outcome: str
    reason: str | None = None
    detail: str | None = None


class LedgerVocabularyError(ValueError):
    """An outcome or reason outside the vocabulary above."""


def _validate(outcome: str, reason: str | None) -> None:
    if outcome not in OUTCOMES:
        raise LedgerVocabularyError(f"Unknown ledger outcome: {outcome!r}")
    if outcome == OUTCOME_INDETERMINATE:
        # Free text by design: it names the site that could not decide.
        if not reason:
            raise LedgerVocabularyError("indeterminate requires a reason naming the site")
        return
    allowed = REASONS[outcome]
    if not allowed:
        if reason is not None:
            raise LedgerVocabularyError(f"{outcome!r} takes no reason, got {reason!r}")
        return
    if reason in allowed:
        return
    if outcome == OUTCOME_FAILED and reason and _HTTP_REASON_RE.match(reason):
        return
    raise LedgerVocabularyError(f"Unknown reason for {outcome!r}: {reason!r}")


# ── Writing ───────────────────────────────────────────────────────────────────

_UPSERT = sa_text(
    """
    INSERT INTO timeline_task_years
        (id, task_id, source, group_key, outcome, reason, detail)
    VALUES
        (:id, :task_id, :source, :group_key, :outcome, :reason, :detail)
    ON CONFLICT (task_id, group_key) DO UPDATE
        SET source  = EXCLUDED.source,
            outcome = EXCLUDED.outcome,
            reason  = EXCLUDED.reason,
            detail  = EXCLUDED.detail
    """
).bindparams(bindparam("task_id", type_=Uuid()))


def record_year_outcome(
    db: Session,
    task_id: uuid.UUID,
    source: str,
    group_key: str,
    outcome: str,
    reason: str | None = None,
    detail: str | None = None,
    *,
    commit: bool = True,
) -> None:
    """Record how one attempted group turned out.

    Upserts on ``(task_id, group_key)``: a later attempt in the same run
    overwrites an earlier one, so a validation walk that starts with a broken
    scene and ends on a working fallback leaves one ``ok`` row, not two.

    ``commit=False`` exists so an ``ok`` row rides the same transaction as the
    snapshot it describes. Both ``upsert_imagery_snapshot`` and
    ``upsert_census_snapshot`` commit for themselves; calling this with
    ``commit=False`` immediately before one of them makes the pair atomic
    without touching either upsert. A ledger row committed *before* its
    snapshot would be a lie if the process died between them; committed
    together, it cannot be.
    """
    _validate(outcome, reason)
    db.execute(
        _UPSERT,
        {
            "id": str(uuid.uuid4()),
            "task_id": task_id,
            "source": source,
            "group_key": group_key,
            "outcome": outcome,
            "reason": reason,
            "detail": detail[:DETAIL_MAX_CHARS] if detail else None,
        },
    )
    if commit:
        db.commit()


def clear_task_year_outcomes(db: Session, timeline_request_id: uuid.UUID, source: str) -> None:
    """Drop the year rows of one (request, source) task.

    Called from ``create_request_tasks``' ON CONFLICT reset: a Celery
    redelivery resets the task row to queued, and a reset task carrying stale
    ``ok`` rows from the attempt that died is worse than a task carrying none.
    """
    db.execute(
        sa_text(
            """
            DELETE FROM timeline_task_years
            WHERE task_id IN (
                SELECT id FROM timeline_request_tasks
                WHERE timeline_request_id = :request_id AND source = :source
            )
            """
        ).bindparams(bindparam("request_id", type_=Uuid())),
        {"request_id": timeline_request_id, "source": source},
    )


def get_task_id(db: Session, timeline_request_id: uuid.UUID, source: str) -> uuid.UUID | None:
    """Resolve the task row the ledger rows hang off, or None if it is gone."""
    row = db.execute(
        sa_text(
            "SELECT id FROM timeline_request_tasks"
            " WHERE timeline_request_id = :request_id AND source = :source"
        ).bindparams(bindparam("request_id", type_=Uuid())),
        {"request_id": timeline_request_id, "source": source},
    ).scalar()
    if row is None:
        return None
    if isinstance(row, uuid.UUID):
        return row
    try:
        return uuid.UUID(str(row))
    except (AttributeError, TypeError, ValueError):
        # A task id that is not a UUID cannot exist in the schema. Rather
        # than take a fetch down over bookkeeping, skip the ledger and say so.
        logger.warning(
            "Task id is not a UUID; skipping the year ledger",
            extra={"request_id": str(timeline_request_id), "source": source},
        )
        return None


# ── Accumulating during the async phase ───────────────────────────────────────


class YearOutcomeLog:
    """Collects non-``ok`` outcomes while the fetch runs, flushes them once.

    The per-year decisions happen outside any DB session — mid-search,
    mid-validation — and opening a session per year would put a write between
    every upstream call. So they accumulate here, keyed the same way the table
    is, and land in the session the persist step already holds.

    ``ok`` rows do *not* come through here: they are written inline next to
    their snapshot so the two commit together (see ``record_year_outcome``).
    """

    def __init__(self, source: str) -> None:
        self.source = source
        self._entries: dict[tuple[str, str], tuple[str, str | None, str | None]] = {}

    def record(
        self,
        group_key: str,
        outcome: str,
        reason: str | None = None,
        detail: str | None = None,
        *,
        source: str | None = None,
    ) -> None:
        """Stage one group's outcome. A later call for the same key wins."""
        _validate(outcome, reason)
        self._entries[(source or self.source, group_key)] = (outcome, reason, detail)

    def __contains__(self, group_key: object) -> bool:
        return any(key == group_key for _, key in self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def entries(self) -> list[tuple[str, str, str, str | None, str | None]]:
        return [
            (source, group_key, outcome, reason, detail)
            for (source, group_key), (outcome, reason, detail) in self._entries.items()
        ]

    def flush(self, db: Session, task_id: uuid.UUID, *, commit: bool = True) -> int:
        """Write every staged outcome. Returns the number of rows written."""
        for source, group_key, outcome, reason, detail in self.entries():
            record_year_outcome(
                db, task_id, source, group_key, outcome, reason, detail, commit=False
            )
        written = len(self._entries)
        if commit:
            db.commit()
        return written

"""Reading the M4 ledger: latest outcome per group, and what to retry.

``year_ledger.py`` writes the ledger. This reads it, and it is the one place
that answers the two questions every heal path used to answer for itself:

* **What is the latest outcome for this (parcel, source, group)?** One query,
  shared by ``scripts/ledger_gaps.py`` (the report), ``maybe_refetch_for_backfill``
  (the self-running path) and ``scripts/requeue_parcels.py --from-ledger``
  (the operator path), so a heal cannot select on a different definition of
  "latest" than the report the operator read before running it.
* **Is that outcome worth another attempt?** A table keyed on
  ``(outcome, reason)``, in code rather than in an argument, because it is a
  property of the vocabulary: a new reason cannot be added without
  classifying it, and the classification is testable without a database.
  What stays per-invocation is the *change* that makes a "retry after a fix"
  class eligible — the operator asserting "I deployed the thing that makes
  this different" (INVESTIGATION §3.4).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.models.parcels import TimelineRequest
from app.services.imagery import attempted_group_keys

logger = logging.getLogger(__name__)


# ── Ledger source ↔ task source ───────────────────────────────────────────────

# The ledger's ``source`` is finer-grained than the task's: one ``census``
# task writes ``census_decennial`` and ``census_acs5`` rows, so a selection
# that says "retry census_decennial 2000" has to ask for a ``census`` task.
_LEDGER_TO_TASK_SOURCE = {
    "census_decennial": "census",
    "census_acs5": "census",
}


def task_source_for(ledger_source: str) -> str:
    """The ``timeline_requests.sources`` entry that would re-run this."""
    return _LEDGER_TO_TASK_SOURCE.get(ledger_source, ledger_source)


# ── Latest outcome per (parcel, source, group_key) ────────────────────────────

# "Latest" is by the timeline request's created_at, tie-broken by the ledger
# row's own created_at.
#
# Not by task id: task ids are uuid4 (``default=uuid.uuid4`` in the ORM,
# ``gen_random_uuid()`` as the server default), so they are random rather
# than monotonic and carry no ordering whatsoever — sorting by one would pick
# an arbitrary run's answer, and would do it differently on every insert.
# The request's created_at is the only column in the join that means "when
# this attempt happened".
#
# ``attempts`` counts every run that recorded an opinion on the triple. It is
# trustworthy only for runs that created their own request: an in-place
# re-run against an existing request upserts on (task_id, group_key) and
# collapses two attempts into one row without moving created_at. That pattern
# had exactly one instance in the tree, ``heal_tract_vintage_gaps.py``, and
# M3 deletes it — every path now goes through a new request.
_LATEST_SQL = """
WITH ranked AS (
    SELECT r.parcel_id            AS parcel_id,
           y.source               AS source,
           y.group_key            AS group_key,
           y.outcome              AS outcome,
           y.reason               AS reason,
           y.detail               AS detail,
           r.created_at           AS run_at,
           ROW_NUMBER() OVER (
               PARTITION BY r.parcel_id, y.source, y.group_key
               ORDER BY r.created_at DESC, y.created_at DESC
           ) AS rn,
           COUNT(*) OVER (
               PARTITION BY r.parcel_id, y.source, y.group_key
           ) AS attempts
    FROM timeline_task_years y
    JOIN timeline_request_tasks t ON t.id = y.task_id
    JOIN timeline_requests r      ON r.id = t.timeline_request_id
)
SELECT parcel_id, source, group_key, outcome, reason, detail, run_at, attempts
FROM ranked
WHERE rn = 1
ORDER BY parcel_id, source, group_key
"""


@dataclass(frozen=True)
class LedgerGroup:
    """One (parcel, source, group) triple's latest recorded outcome."""

    parcel_id: uuid.UUID
    source: str
    group_key: str
    outcome: str
    reason: str | None
    detail: str | None
    run_at: datetime | None
    attempts: int

    @property
    def task_source(self) -> str:
        return task_source_for(self.source)


def latest_outcomes(
    db: Session,
    *,
    parcel_id: uuid.UUID | None = None,
    sources: set[str] | None = None,
) -> list[LedgerGroup]:
    """Latest outcome for every group, optionally narrowed.

    ``sources`` filters on the *ledger* source (``census_decennial``), not on
    the task source (``census``); use ``task_source_for`` to bridge.

    Filtering happens in Python rather than in the window query on purpose:
    the window has to see every run of a triple to rank them, so narrowing it
    inside the CTE would change which row wins, not just which rows are
    returned.
    """
    rows = db.execute(sa_text(_LATEST_SQL)).mappings().all()
    result: list[LedgerGroup] = []
    for raw in rows:
        source = str(raw["source"])
        if sources is not None and source not in sources:
            continue
        row_parcel = uuid.UUID(str(raw["parcel_id"]))
        if parcel_id is not None and row_parcel != parcel_id:
            continue
        result.append(
            LedgerGroup(
                parcel_id=row_parcel,
                source=source,
                group_key=str(raw["group_key"]),
                outcome=str(raw["outcome"]),
                reason=raw["reason"],
                detail=raw["detail"],
                run_at=raw["run_at"],
                attempts=int(raw["attempts"]),
            )
        )
    return result


# ── Retry policy ──────────────────────────────────────────────────────────────

RETRY = "retry"
NEVER = "never"
RETRY_ONCE = "retry_once"
NEEDS_CLOUD_FLAG = "needs_cloud_flag"
NEEDS_ABSENT_API_FLAG = "needs_absent_api_flag"

# Keyed on (outcome, reason). A ``None`` reason is the outcome-wide fallback,
# consulted only when no exact pair matches. An outcome with neither an exact
# pair nor a fallback is a **policy gap**: never retried, and logged, because
# a reason added to year_ledger.REASONS without a decision here must announce
# itself rather than be silently swept into "no".
RETRY_POLICY: dict[tuple[str, str | None], str] = {
    # The fetch was attempted and did not complete. Nothing about the world
    # has to change for a retry to be worth making — this is the whole reason
    # the outcome exists, and 33 of Crawford County 6563dedf's groups are it.
    ("failed", None): RETRY,
    # A candidate existed and was deliberately not served. Retrying
    # re-suppresses; the answer is reconciliation, not a refetch
    # (reconcile_source_snapshots' suppressed-delete).
    ("suppressed", None): NEVER,
    # The search covered the period and the catalogue is empty. New scenes
    # for 1987 do not arrive. Only a collection-extent change or a new source
    # makes this stale, and both are code events, not time events.
    ("absent", "no_scenes"): NEVER,
    # Items existed, none contained the point. Geometry does not change.
    ("absent", "no_covering_item"): NEVER,
    # Same request, same answer, until the 40% eo:cloud_cover filter moves.
    ("absent", "all_cloud_filtered"): NEEDS_CLOUD_FLAG,
    # The API answered and had nothing for the geography we asked about.
    # Retrying the identical request is guaranteed-identical work — it is
    # eligible exactly when the request changed, which is what the decennial
    # 2000 six-character tract trim did. Making absence retryable is a
    # decision, so it takes an explicit flag rather than a default.
    ("absent", "api_no_data"): NEEDS_ABSENT_API_FLAG,
    # The code could not tell absence from truncation at that site. Today
    # both instances are response caps, and re-running under the same cap
    # reproduces the same uncertainty — so one retry to rule out a transient,
    # then it is a code fix (raise the cap, paginate) and not a retry.
    ("indeterminate", None): RETRY_ONCE,
    ("ok", None): NEVER,
}


def retry_policy(outcome: str, reason: str | None) -> str:
    """Classify one outcome. Unknown pairs are a logged policy gap."""
    exact = RETRY_POLICY.get((outcome, reason))
    if exact is not None:
        return exact
    fallback = RETRY_POLICY.get((outcome, None))
    if fallback is not None:
        return fallback
    logger.warning(
        "Retry policy gap — outcome classified as never by default",
        extra={"outcome": outcome, "reason": reason},
    )
    return NEVER


def is_stale(group: LedgerGroup) -> bool:
    """Whether current code would ever attempt this group again.

    A group outside ``attempted_group_keys(group.source)`` cannot be turned
    into ``ok`` by any run of current code — the census 1990 endpoint that
    ``e6afa9b`` stopped asking about is the instance this exists for (Y3).
    Distinct from the retry policy: an outcome can be policy-retryable and
    still stale, and the stale group is what ``ledger_gaps.py`` reports
    separately rather than silently dropping.
    """
    return group.group_key not in attempted_group_keys(group.source)


def is_retryable(
    group: LedgerGroup,
    *,
    include_cloud_filtered: bool = False,
    include_absent_api: bool = False,
) -> bool:
    """Whether this group is worth another attempt under the given flags."""
    if is_stale(group):
        return False
    policy = retry_policy(group.outcome, group.reason)
    if policy == RETRY:
        return True
    if policy == RETRY_ONCE:
        return group.attempts <= 1
    if policy == NEEDS_CLOUD_FLAG:
        return include_cloud_filtered
    if policy == NEEDS_ABSENT_API_FLAG:
        return include_absent_api
    return False


def retryable_groups(
    db: Session,
    *,
    parcel_id: uuid.UUID | None = None,
    sources: set[str] | None = None,
    include_cloud_filtered: bool = False,
    include_absent_api: bool = False,
) -> list[LedgerGroup]:
    """``latest_outcomes`` narrowed to what the policy says to retry."""
    return [
        group
        for group in latest_outcomes(db, parcel_id=parcel_id, sources=sources)
        if is_retryable(
            group,
            include_cloud_filtered=include_cloud_filtered,
            include_absent_api=include_absent_api,
        )
    ]


def group_by_task_source(groups: list[LedgerGroup]) -> dict[str, list[LedgerGroup]]:
    """Fold selected groups onto the task sources that would re-run them."""
    by_source: dict[str, list[LedgerGroup]] = {}
    for group in groups:
        by_source.setdefault(group.task_source, []).append(group)
    return by_source


# ── Per-source dispatch history ───────────────────────────────────────────────


def last_attempt_by_source(db: Session, parcel_id: uuid.UUID) -> dict[str, datetime]:
    """When each source was last *dispatched* for this parcel.

    "Dispatched", not "attempted": the cooldown stays anchored on request
    creation, as it always was. What changes is that it is now per source —
    a census-only backfill fired at T no longer blocks a landsat backfill
    until T+6h, which is what a single per-parcel timestamp did.

    Folded in Python rather than asked as ``:source = ANY(sources)`` because
    the array is ``TEXT[]`` on PostgreSQL and a JSON array on the SQLite test
    database, and a parcel holds a handful of requests, not thousands. The
    columns come through the ORM so ``created_at`` arrives as a datetime on
    both, which a raw text SELECT does not guarantee on SQLite.
    """
    rows = db.execute(
        select(TimelineRequest.created_at, TimelineRequest.sources)
        .where(TimelineRequest.parcel_id == parcel_id)
        .order_by(TimelineRequest.created_at.desc())
    ).all()

    latest: dict[str, datetime] = {}
    for created_at, sources in rows:
        if created_at is None:
            continue
        for source in sources or ():
            latest.setdefault(str(source), created_at)
    return latest

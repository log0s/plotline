"""Imagery and timeline request service layer.

Handles database operations for served imagery and timeline requests.
Business logic (STAC querying) lives in services/stac.py and tasks/timeline.py.

Note: ``scenes`` and ``parcel_scenes`` queries use raw SQL to avoid GeoAlchemy2
generating PostGIS functions (AsEWKB, GeomFromEWKT) that are incompatible with
SQLite test databases.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Uuid, bindparam, select
from sqlalchemy import text as sa_text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import TextClause

from app.config import get_settings
from app.models.parcels import Parcel, TimelineRequest, TimelineRequestTask
from app.redact import redact
from app.services.admission import (
    WAIT_POLL_SECONDS,
    AdmissionRefused,
    ensure_admission,
    wait_for_admission_slot,
)

logger = logging.getLogger(__name__)


# ADR 0001 step 4 removed the step-3 measurement hook that used to live here.
# Its job was to name the one remaining caller of the retired denormalized
# table while a cooling period ran; step 4's code cutover leaves that table
# with no caller at all, so the hook has nothing left to name and its presence
# would only suggest there is still something to measure in the application.
# The counter half of the measurement — `scripts/snapshot_reads.py` over
# `pg_stat_user_tables` — outlives it, because "zero accesses by anything"
# is the claim the cooling span still has to support.


# A task with a completed_at. 'partial' joins the list at the task level for
# the same reason it joined at the request level in 0012: it is terminal and
# serving, not an error, and a task that never gets a completed_at reads as
# stranded to every sweep.
_TERMINAL_TASK_STATUSES = ("complete", "partial", "failed", "skipped")


# ── Per-source outcome counts ─────────────────────────────────────────────────


@dataclass(frozen=True)
class TaskCounts:
    """What a source actually asked for and what came back.

    Property-only today. ``rows_returned`` is the number of events the
    adapters handed the address matcher and ``rows_matched`` the number it
    kept, so ``rows_returned - rows_matched`` is exactly the matcher's
    rejection count — the split that used to exist only in the
    ``"Property events filtered"`` log line (STATUS.md Z4).

    ``coverage`` is ``None`` when a caller is reporting counts without
    re-stating a coverage verdict; ``update_request_task`` leaves the column
    alone in that case rather than blanking a verdict written earlier.
    """

    queries_run: int | None = None
    queries_failed: int | None = None
    rows_returned: int | None = None
    rows_matched: int | None = None
    coverage: str | None = None


# ── Served-scene data class (PostGIS-free, SQLite-compatible) ─────────────────


@dataclass
class ServedSceneRow:
    """One period a parcel serves, flattened for the response layer.

    Until the ADR 0001 step-3 cutover this was one row of the denormalized
    table step 4 retired, and was named for it. It is now a ``parcel_scenes``
    row joined to its ``scenes`` row, with ``additional_cog_urls``
    reconstructed from ``mosaic_scene_ids``. **The field set is unchanged**,
    deliberately: the
    listing endpoint, the preview renderer and the Titiler callback all build
    their responses out of it, and step 3 moved where the facts come from,
    not what they are (``tests/fixtures/step3_served_shape.json`` is the
    frozen shape, captured from the old path before it was deleted).

    ``id`` is the one field whose *value* changed: it is
    ``parcel_scenes.id``, where it used to be the old table's primary key.

    Avoids importing the GeoAlchemy2 ORM model for reads, keeping the service
    layer compatible with both PostgreSQL (production) and SQLite (tests).

    ``created_at`` has always been ``None`` here — the old read selected the
    column and never assigned it — and stays ``None`` rather than being
    quietly redefined as ``parcel_scenes.selected_at``, which answers a
    different question.
    """

    id: uuid.UUID
    parcel_id: uuid.UUID
    source: str
    capture_date: date
    stac_item_id: str
    stac_collection: str
    cog_url: str
    thumbnail_url: str | None
    resolution_m: float | None
    cloud_cover_pct: float | None
    additional_cog_urls: list[str] | None = None
    bbox: tuple[float, float, float, float] | None = None
    created_at: datetime | None = None


# ── Timeline request helpers ───────────────────────────────────────────────────


_INFLIGHT_STATUSES = ("queued", "processing")

# 'partial' is terminal and serving — a timeline with a gap in it, not an
# error — so it is reusable exactly where 'complete' is.
_REUSABLE_STATUSES = (*_INFLIGHT_STATUSES, "complete", "partial")

# Longer than the task's 35-minute hard time limit — an in-flight request
# that hasn't been touched for this long was lost (worker killed before
# acking, broker outage at dispatch, ...) and may be taken over.
_STALE_INFLIGHT = timedelta(minutes=45)

# The declared scope of a run that is meant to cover everything. The worker
# still intersects this with what the parcel is eligible for; see
# TimelineRequest.FULL_SCOPE.
FULL_SCOPE: tuple[str, ...] = TimelineRequest.FULL_SCOPE


def normalize_sources(sources: Iterable[str] | None) -> list[str]:
    """Canonicalise a declared scope: deduplicated, sorted, validated.

    ``None`` means full scope. Sorting and deduplicating here — at the one
    write site — is what makes ``cardinality(sources) = 6`` a sound test for
    "full scope"; the CHECK constraint can rule out unknown sources but not
    a repeated one.
    """
    if sources is None:
        return list(FULL_SCOPE)
    unique = sorted(set(sources))
    unknown = [s for s in unique if s not in FULL_SCOPE]
    if unknown:
        raise ValueError(f"Unknown timeline source(s): {', '.join(unknown)}")
    if not unique:
        raise ValueError("A timeline request must declare at least one source")
    return unique


def full_scope_clause(db: Session) -> TextClause:
    """SQL for "this request declared every source".

    Two spellings because ``sources`` is ``TEXT[]`` on PostgreSQL and a JSON
    array on SQLite (the test database has no array type). Both count
    elements exactly; neither needs the array's contents, because
    ``normalize_sources`` has already ruled out duplicates and unknowns.

    The column is table-qualified so the clause can be reused in a query that
    joins ``timeline_requests`` to a subquery over it — which is what
    ``requeue_empty_property.py``'s latest-request join is. It therefore
    assumes the table is not aliased; nothing in the tree aliases it.
    """
    counter = "json_array_length" if db.get_bind().dialect.name == "sqlite" else "cardinality"
    return sa_text(f"{counter}(timeline_requests.sources) = {len(FULL_SCOPE)}")


def _find_reusable_request(db: Session, parcel_id: uuid.UUID) -> TimelineRequest | None:
    """The parcel's current request: the latest **full-scope** one.

    Scoped requests are deliberately invisible here. A census-only backfill
    that became the parcel's current request would be inspected by
    ``maybe_refetch_for_backfill`` as if it were a full run — it has no
    ``usgs_topo`` task row, so the topo trigger would fire and the next page
    view would dispatch the whole pipeline again, forever (INVESTIGATION
    §2.2a, trigger 6). Filtering on declared scope is what closes that, and
    it is why the scope is declared rather than derived.
    """
    return (
        db.execute(
            select(TimelineRequest)
            .where(TimelineRequest.parcel_id == parcel_id)
            .where(TimelineRequest.status.in_(_REUSABLE_STATUSES))
            .where(full_scope_clause(db))
            .order_by(TimelineRequest.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def _find_inflight_request(db: Session, parcel_id: uuid.UUID) -> TimelineRequest | None:
    """The parcel's in-flight request, whatever scope it declared.

    Separate from ``_find_reusable_request`` because
    ``uq_timeline_requests_parcel_inflight`` does not care about scope: a
    scoped backfill occupies the parcel's one in-flight slot just as a full
    run does, and the loser of that race has to be able to see it. Filtering
    this by scope would turn a lost race into a re-raised IntegrityError.
    """
    return (
        db.execute(
            select(TimelineRequest)
            .where(TimelineRequest.parcel_id == parcel_id)
            .where(TimelineRequest.status.in_(_INFLIGHT_STATUSES))
            .order_by(TimelineRequest.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def _as_utc(value: datetime) -> datetime:
    """Attach UTC to a naive timestamp (SQLite hands back naive datetimes)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _is_stale_inflight(request: TimelineRequest) -> bool:
    if request.status not in _INFLIGHT_STATUSES:
        return False
    updated = request.updated_at
    if updated is None:
        return False
    return datetime.now(tz=UTC) - _as_utc(updated) > _STALE_INFLIGHT


def _create_queued_request(
    db: Session,
    parcel_id: uuid.UUID,
    *,
    sources: Iterable[str] | None = None,
    origin: str = "user",
) -> tuple[TimelineRequest, bool]:
    """Insert a queued request; on losing the one-in-flight-per-parcel race,
    return the winning request instead. Returns (request, created).

    ``sources`` is the declared scope — ``None`` means every source, which is
    what every user-originated run declares. ``origin`` says who asked and is
    what the admission reserve reads.

    Raises ``AdmissionRefused`` when the kill switch is on or the in-flight
    queue is at its cap — every new pipeline run passes through here.
    """
    declared = normalize_sources(sources)
    settings = get_settings()
    ensure_admission(db, settings, what="timeline_request", origin=origin)
    request = TimelineRequest(
        parcel_id=parcel_id,
        status="queued",
        sources=declared,
        origin=origin,
        deployed_sha=settings.git_sha,
    )
    db.add(request)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        racing = _find_inflight_request(db, parcel_id)
        if racing is not None:
            logger.info(
                "Lost request-creation race; reusing in-flight request",
                extra={"parcel_id": str(parcel_id), "request_id": str(racing.id)},
            )
            return racing, False
        raise
    db.refresh(request)
    logger.info(
        "Created new timeline request",
        extra={
            "parcel_id": str(parcel_id),
            "request_id": str(request.id),
            "origin": origin,
            "sources": declared,
        },
    )
    return request, True


def create_queued_request_waiting(
    db: Session,
    parcel_id: uuid.UUID,
    *,
    deadline: float,
    sources: Iterable[str] | None = None,
    origin: str = "heal",
    poll_seconds: float = WAIT_POLL_SECONDS,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[TimelineRequest, bool]:
    """``_create_queued_request`` for batch callers: wait out a full queue.

    Same return contract, same ``IntegrityError`` behaviour. The difference
    is that ``queue_full`` becomes a wait rather than a raise, until
    ``deadline`` (a ``clock()`` value) passes — at which point the original
    ``AdmissionRefused`` is raised so the caller can report the parcel as
    unreached. ``kill_switch`` is never waited out and raises immediately.

    A sweep that raises here abandons every parcel behind the refusal, which
    is how the 2026-08-25 S2-year sweep reached 30 of 184 parcels
    (``docs/audits/2026-08-s2-year/HEAL-SCORECARD.md`` §2).

    ``origin`` defaults to ``heal`` rather than ``user``: every caller of this
    function is a script, and the wait loop below is the whole reason a heal
    can be made to yield the reserve without abandoning its tail.
    """
    while True:
        try:
            return _create_queued_request(db, parcel_id, sources=sources, origin=origin)
        except AdmissionRefused as exc:
            if exc.reason != "queue_full":
                raise
            opened = wait_for_admission_slot(
                db,
                get_settings(),
                deadline=deadline,
                origin=origin,
                poll_seconds=poll_seconds,
                sleeper=sleeper,
                clock=clock,
            )
            if not opened:
                raise


def get_or_create_timeline_request(
    db: Session,
    parcel_id: uuid.UUID,
) -> tuple[TimelineRequest, bool]:
    """Return (request, is_new).

    Reuses an in-flight (queued/processing) request so concurrent visits
    don't spawn duplicate pipelines, and a 'complete' one so a second visit
    is instant. An in-flight request untouched for longer than the task's
    hard time limit is considered lost: it's marked failed and replaced.
    """
    existing = _find_reusable_request(db, parcel_id)

    if existing is not None and _is_stale_inflight(existing):
        logger.warning(
            "Taking over stale in-flight timeline request",
            extra={"parcel_id": str(parcel_id), "request_id": str(existing.id)},
        )
        update_timeline_request_status(
            db, existing, "failed", error_message="Worker never completed the request"
        )
        existing = None

    if existing is not None:
        logger.debug(
            "Returning existing timeline request",
            extra={
                "parcel_id": str(parcel_id),
                "request_id": str(existing.id),
                "status": existing.status,
            },
        )
        return existing, False

    return _create_queued_request(db, parcel_id)


def dispatch_timeline_task(db: Session, request: TimelineRequest) -> bool:
    """Queue the Celery job for a request; mark it failed if the broker is down.

    Without this, a broker outage at dispatch time leaves a request stuck at
    'queued' forever while the client polls it. Returns True when queued.
    """
    from kombu.exceptions import OperationalError as KombuOperationalError
    from redis.exceptions import RedisError

    from app.tasks.timeline import fetch_imagery_timeline

    try:
        fetch_imagery_timeline.delay(str(request.id))
    except (KombuOperationalError, RedisError, OSError) as exc:
        logger.error(
            "Failed to dispatch timeline task",
            extra={"request_id": str(request.id), "error": str(exc)},
        )
        update_timeline_request_status(
            db, request, "failed", error_message="Could not queue the timeline job"
        )
        return False

    logger.info("Timeline task dispatched", extra={"request_id": str(request.id)})
    return True


def get_timeline_request(
    db: Session,
    request_id: uuid.UUID,
) -> TimelineRequest | None:
    """Fetch a timeline request by ID, including its per-source tasks."""
    return (
        db.execute(select(TimelineRequest).where(TimelineRequest.id == request_id))
        .scalars()
        .first()
    )


def create_request_tasks(
    db: Session,
    timeline_request_id: uuid.UUID,
    sources: list[str],
) -> list[TimelineRequestTask]:
    """Create (or reset) per-source task rows for a timeline request.

    Idempotent: with acks_late a killed worker's task is redelivered and the
    orchestrator runs again — a blind insert would duplicate the rows.
    ON CONFLICT resets the existing row to queued instead.

    The reset takes the task's per-year ledger rows with it. Those rows
    describe the attempt that died; carrying them into the replacement run
    would leave ``ok`` rows claiming snapshots the retry has not written yet,
    which is worse than starting the run with no rows at all.
    """
    from app.services.year_ledger import clear_task_year_outcomes

    # Typed bindparams so the UUIDs are rendered the same way the ORM
    # renders them when querying these rows back (matters on SQLite).
    sql = sa_text(
        """
        INSERT INTO timeline_request_tasks (id, timeline_request_id, source, status)
        VALUES (:id, :timeline_request_id, :source, 'queued')
        ON CONFLICT (timeline_request_id, source) DO UPDATE
            SET status = 'queued',
                items_found = 0,
                started_at = NULL,
                completed_at = NULL,
                error_message = NULL
        """
    ).bindparams(
        bindparam("id", type_=Uuid()),
        bindparam("timeline_request_id", type_=Uuid()),
    )
    for source in sources:
        clear_task_year_outcomes(db, timeline_request_id, source)
        db.execute(
            sql,
            {
                "id": uuid.uuid4(),
                "timeline_request_id": timeline_request_id,
                "source": source,
            },
        )
    db.commit()
    tasks = (
        db.execute(
            select(TimelineRequestTask).where(
                TimelineRequestTask.timeline_request_id == timeline_request_id
            )
        )
        .scalars()
        .all()
    )
    return list(tasks)


def update_request_task(
    db: Session,
    task: TimelineRequestTask,
    status: str,
    items_found: int | None = None,
    error_message: str | None = None,
    counts: TaskCounts | None = None,
    clear_items_found: bool = False,
) -> None:
    """Update a task's status fields.

    ``items_found`` keeps its "None means don't touch it" contract, so a
    caller that genuinely means NULL — a not-covered task, which counted
    nothing because it asked nothing — says so with ``clear_items_found``
    rather than by passing a value that would read as an answer.
    """
    task.status = status
    if clear_items_found:
        task.items_found = None
    elif items_found is not None:
        task.items_found = items_found
    if counts is not None:
        task.queries_run = counts.queries_run
        task.queries_failed = counts.queries_failed
        task.rows_returned = counts.rows_returned
        task.rows_matched = counts.rows_matched
        if counts.coverage is not None:
            task.coverage = counts.coverage
    if status == "processing":
        task.started_at = datetime.now(tz=UTC)
    elif status in _TERMINAL_TASK_STATUSES:
        task.completed_at = datetime.now(tz=UTC)
    if error_message:
        # Task rows are served to clients by GET /timeline-requests/{id} and
        # are usually str(exc) — scrub at the sink, not at each raise site.
        task.error_message = redact(error_message)
    db.commit()


def update_timeline_request_status(
    db: Session,
    request: TimelineRequest,
    status: str,
    error_message: str | None = None,
) -> None:
    """Update the parent timeline request status."""
    request.status = status
    if status in _TERMINAL_REQUEST_STATUSES:
        request.completed_at = datetime.now(tz=UTC)
    if error_message:
        request.error_message = redact(error_message)
    db.commit()


def aggregate_request_status(tasks: Iterable[tuple[str, str]]) -> tuple[str, list[str]]:
    """Fold ``(source, task_status)`` pairs into the request's own status.

    Returns the status and the sources that ended degraded — failed, or
    ``partial``. On a ``failed`` result the two are the same list.

    * ``complete`` — no task failed.
    * ``partial``  — at least one task failed and at least one did not. This
      is the state Crawford County parcel ``6563dedf`` was in while its
      request read ``complete``: the NAIP and Sentinel-2 tasks both failed,
      33 years were lost, zero aerial imagery was served, and nothing
      self-running could see any of it. ``partial`` is terminal and serving —
      a timeline with a hole in it, not an error, and readers must not render
      it as one.
    * ``failed``   — every task failed.

    A request with no task rows stays ``complete``: the old behaviour, and
    the only honest reading of "nothing was attempted and nothing broke".
    ``skipped`` is not a failure — a county with no property adapter has
    always kept its request complete, and a scoped request's absent sources
    have no row here at all. A ``not_covered`` property task is skipped for
    the same reason: the county was never the authority for that address.

    A ``partial`` task (0014, property only) counts as a failed one *for the
    partial computation*: it has a known hole, so the request has a known
    hole and must not read ``complete``. It does not count as failed for the
    all-failed computation — a task that served some of its queries did serve
    data, and calling the whole request ``failed`` would be the mirror image
    of the defect this function exists to fix.
    """
    pairs = list(tasks)
    if not pairs:
        return "complete", []
    failed = [source for source, status in pairs if status == "failed"]
    degraded = [source for source, status in pairs if status in ("failed", "partial")]
    if len(failed) == len(pairs):
        return "failed", failed
    if degraded:
        return "partial", degraded
    return "complete", []


def maybe_refetch_for_backfill(
    db: Session,
    parcel: Parcel,
    existing_req: TimelineRequest,
) -> TimelineRequest | None:
    """Return a fresh TimelineRequest if the existing one is missing data
    we can now provide; otherwise None.

    Two kinds of trigger, and they produce different requests.

    **The task-row triggers, full scope, unchanged.**

      * Census tract FIPS is now available but no census task ran, or the
        previous census task failed (e.g. a Census API outage).
      * The parcel's county now has a property adapter, but the previous
        run's property task was missing, skipped, partial, or failed (e.g. a
        county portal outage).
      * No usgs_topo task row exists (source added after initial fetch).

    None of the three is subsumed by the ledger, and each for its own
    reason. A *missing* census or topo task row means the source never ran,
    so it has no ledger rows to be retryable — absence is not an outcome. A
    census task that failed before its first year wrote nothing either.
    Property has no ledger source at all: its axis is the feed, not a period
    (INVESTIGATION §6.1), so it writes no ``timeline_task_years`` rows in any
    circumstance. They keep dispatching a full-scope request, which is also
    what keeps the topo trigger a one-shot latch — a topo-*scoped* run would
    leave the parcel's current full-scope request still lacking a topo task
    row, and the trigger would fire again every cooldown, forever.

    **The ledger trigger, scoped.** Groups whose latest outcome the retry
    policy says to retry, folded onto the sources that would re-run them.
    This is the path that can see a ``failed`` year under a ``complete``
    task — Crawford County ``6563dedf``'s 33 ``read_timeout`` groups, which
    no self-running code could reach before. It never selects the
    flag-gated classes (``absent/api_no_data``, ``absent/all_cloud_filtered``):
    making absence retryable is an operator's assertion that the request
    changed, not a default.

    Caller is responsible for dispatching the Celery task on the returned
    request.
    """
    if existing_req.status not in ("complete", "partial"):
        return None

    needs_refetch = False

    if parcel.census_tract_id:
        census_task = (
            db.execute(
                select(TimelineRequestTask)
                .where(TimelineRequestTask.timeline_request_id == existing_req.id)
                .where(TimelineRequestTask.source == "census")
            )
            .scalars()
            .first()
        )
        if not census_task or census_task.status == "failed":
            needs_refetch = True
            logger.info(
                "Census task missing or failed — refetch needed",
                extra={"parcel_id": str(parcel.id)},
            )

    if parcel.county:
        from app.services.county_adapters import get_adapter_for_county

        if get_adapter_for_county(parcel.county):
            prop_task = (
                db.execute(
                    select(TimelineRequestTask)
                    .where(TimelineRequestTask.timeline_request_id == existing_req.id)
                    .where(TimelineRequestTask.source == "property")
                )
                .scalars()
                .first()
            )
            # 'partial' joins the list because it is exactly the state this
            # trigger exists for: some county queries failed, so the history
            # on file is known-thin and a later visit can honestly try again.
            #
            # 'not_covered' is excluded for the opposite reason. It is not a
            # transient gap a retry can close: the county is not the permit
            # authority for that address, and re-asking would dispatch a
            # full-scope request on every single visit, forever. Only a code
            # change — a new adapter, or a change to the coverage rule — can
            # move it, and that arrives as a deploy, not as a refetch.
            covered = prop_task is None or prop_task.coverage != "not_covered"
            if covered and (not prop_task or prop_task.status in ("skipped", "partial", "failed")):
                needs_refetch = True
                logger.info(
                    "Property task missing/skipped/partial/failed — refetch needed",
                    extra={"parcel_id": str(parcel.id), "county": parcel.county},
                )

    topo_task = (
        db.execute(
            select(TimelineRequestTask)
            .where(TimelineRequestTask.timeline_request_id == existing_req.id)
            .where(TimelineRequestTask.source == "usgs_topo")
        )
        .scalars()
        .first()
    )
    if not topo_task:
        needs_refetch = True
        logger.info(
            "USGS topo task missing — refetch needed",
            extra={"parcel_id": str(parcel.id)},
        )

    if needs_refetch:
        wanted: set[str] | None = None  # None means full scope
    else:
        wanted = _ledger_backfill_sources(db, parcel.id)
        if not wanted:
            return None

    eligible = _outside_cooldown(db, parcel.id, wanted)
    if eligible is _COOLING:
        return None

    try:
        new_req, created = _create_queued_request(
            db, parcel.id, sources=eligible, origin="backfill"
        )
    except AdmissionRefused as exc:
        # A backfill is optional work on a parcel that already renders;
        # refusing it must not surface as an error on that parcel's page.
        logger.info(
            "Backfill suppressed — admission refused",
            extra={"parcel_id": str(parcel.id), "reason": exc.reason},
        )
        return None
    if not created:
        # Another request is already in flight — it will do the backfill.
        return None
    logger.info(
        "Created new timeline request for backfill",
        extra={
            "parcel_id": str(parcel.id),
            "request_id": str(new_req.id),
            "sources": new_req.sources,
        },
    )
    return new_req


def _ledger_backfill_sources(db: Session, parcel_id: uuid.UUID) -> set[str]:
    """Task sources with at least one group the retry policy says to retry."""
    from app.services import ledger as ledger_service

    groups = ledger_service.retryable_groups(db, parcel_id=parcel_id)
    if not groups:
        return set()
    by_source = ledger_service.group_by_task_source(groups)
    logger.info(
        "Ledger backfill candidates",
        extra={
            "parcel_id": str(parcel_id),
            "sources": sorted(by_source),
            "groups": sum(len(g) for g in by_source.values()),
        },
    )
    return set(by_source)


# Sentinel for "every candidate source is still cooling down". Distinct from
# an empty set, which would mean full scope to _create_queued_request.
_COOLING: list[str] = []


def _outside_cooldown(
    db: Session, parcel_id: uuid.UUID, wanted: set[str] | None
) -> list[str] | None:
    """Narrow ``wanted`` to the sources whose cooldown has expired.

    ``None`` in and ``None`` out means full scope. Returns ``_COOLING`` when
    everything asked for is still inside the window.

    The cooldown is still dispatch-anchored — it measures time since a
    request that *included* the source was created — but it is now per
    source rather than per parcel. A single per-parcel timestamp meant a
    census-only backfill fired at T blocked a landsat backfill until T+6h,
    and a fleet sweep reset the clock on every parcel at once
    (INVESTIGATION §7.3).
    """
    from app.services import ledger as ledger_service

    cooldown = timedelta(hours=get_settings().backfill_cooldown_hours)
    last_by_source = ledger_service.last_attempt_by_source(db, parcel_id)
    candidates = sorted(wanted) if wanted is not None else list(FULL_SCOPE)

    now = datetime.now(UTC)
    ready: list[str] = []
    cooling: dict[str, float] = {}
    for source in candidates:
        last = last_by_source.get(source)
        if last is None:
            ready.append(source)
            continue
        age = now - _as_utc(last)
        if age >= cooldown:
            ready.append(source)
        else:
            cooling[source] = round(age.total_seconds() / 3600, 2)

    if not ready:
        logger.info(
            "Backfill suppressed — every candidate source is inside the cooldown",
            extra={
                "parcel_id": str(parcel_id),
                "cooling": cooling,
                "cooldown_hours": cooldown.total_seconds() / 3600,
            },
        )
        return _COOLING

    # A full-scope trigger stays full scope even when some of its sources are
    # cooling: the topo latch and requeue_empty_property's latest-request
    # join both need the replacement request to be full-scope, and narrowing
    # it here to dodge a cooldown would cost that for a few minutes of work.
    if wanted is None:
        return None
    return ready


# ── Stranded-work janitor ─────────────────────────────────────────────────────

_TERMINAL_REQUEST_STATUSES = ("complete", "partial", "failed")
_STRANDED_ERROR = "Stranded: worker died mid-task (janitor)"


def _age_minutes(since: datetime) -> float:
    return round((datetime.now(tz=UTC) - _as_utc(since)).total_seconds() / 60, 1)


def _fail_open_tasks(db: Session, request: TimelineRequest) -> int:
    """Mark a request's non-terminal task rows failed. Caller commits."""
    tasks = (
        db.execute(
            select(TimelineRequestTask)
            .where(TimelineRequestTask.timeline_request_id == request.id)
            .where(TimelineRequestTask.status.in_(_INFLIGHT_STATUSES))
        )
        .scalars()
        .all()
    )
    for task in tasks:
        task.status = "failed"
        task.completed_at = datetime.now(tz=UTC)
        task.error_message = _STRANDED_ERROR
    return len(tasks)


def sweep_stranded_work(db: Session) -> tuple[int, int]:
    """Fail requests and task rows a dead worker left in flight.

    An OOM kill is a SIGKILL: the task's SoftTimeLimitExceeded handler never
    runs, so nothing marks the rows terminal and they sit in queued/processing
    forever. Two shapes exist, and the second is the one the 2026-08 ops audit
    found in production:

      1. The request itself is still in flight. Anything untouched for longer
         than the task's hard time limit plus margin (``_STALE_INFLIGHT``, 45
         minutes against a 35-minute limit) was lost.
      2. The request is already terminal — the *next* caller's stale-takeover
         failed it, or the soft-limit handler failed the request but not its
         rows — while a task row underneath it is still queued/processing.
         Those rows never expire on their own, and while they sit non-terminal
         backfill cannot see the source as failed.

    Runs on worker startup, so a worker that died mid-task heals its own mess
    on the next boot. Rows are locked with SKIP LOCKED, so two workers booting
    at once split the work instead of colliding, and neither waits.

    Returns (requests_failed, orphan_tasks_failed).
    """
    inflight = (
        db.execute(
            select(TimelineRequest)
            .where(TimelineRequest.status.in_(_INFLIGHT_STATUSES))
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )

    requests_failed = 0
    for request in inflight:
        # Age is read in Python, not SQL: the test database is SQLite, which
        # stores these timestamps as text and cannot compare them to a bound
        # aware datetime the way PostgreSQL does.
        if not _is_stale_inflight(request):
            continue
        tasks_failed = _fail_open_tasks(db, request)
        request.status = "failed"
        request.completed_at = datetime.now(tz=UTC)
        request.error_message = _STRANDED_ERROR
        requests_failed += 1
        logger.warning(
            "Janitor failed a stranded timeline request",
            extra={
                "request_id": str(request.id),
                "parcel_id": str(request.parcel_id),
                "age_minutes": _age_minutes(request.updated_at),
                "tasks_failed": tasks_failed,
            },
        )

    orphans = (
        db.execute(
            select(TimelineRequestTask, TimelineRequest)
            .join(
                TimelineRequest,
                TimelineRequest.id == TimelineRequestTask.timeline_request_id,
            )
            .where(TimelineRequestTask.status.in_(_INFLIGHT_STATUSES))
            .where(TimelineRequest.status.in_(_TERMINAL_REQUEST_STATUSES))
        )
        .tuples()
        .all()
    )

    orphan_tasks_failed = 0
    for task, request in orphans:
        # Same guard as above: a request that finished seconds ago may still
        # have a row mid-write.
        if datetime.now(tz=UTC) - _as_utc(request.updated_at) <= _STALE_INFLIGHT:
            continue
        task.status = "failed"
        task.completed_at = datetime.now(tz=UTC)
        task.error_message = _STRANDED_ERROR
        orphan_tasks_failed += 1
        logger.warning(
            "Janitor failed a stranded task row",
            extra={
                "request_id": str(request.id),
                "parcel_id": str(request.parcel_id),
                "source": task.source,
                "request_status": request.status,
                "age_minutes": _age_minutes(request.updated_at),
            },
        )

    # Commit either way — with nothing to write it just releases the row
    # locks the SELECT above took.
    db.commit()
    if requests_failed or orphan_tasks_failed:
        logger.warning(
            "Janitor swept stranded work",
            extra={
                "requests_failed": requests_failed,
                "orphan_tasks_failed": orphan_tasks_failed,
            },
        )
    else:
        logger.info("Janitor found no stranded work")

    return requests_failed, orphan_tasks_failed


# ── Imagery snapshot helpers ──────────────────────────────────────────────────


def _capture_date(value: object) -> date | None:
    """Parse a capture_date column, which SQLite hands back as text."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


# How each selector groups its picks. Reconciliation must bucket rows the
# same way the selector did — see reconcile_source_snapshots.
SELECTION_SCOPES: dict[str, Callable[[date], tuple[int, ...]]] = {
    "year": lambda d: (d.year,),
    # Unused since 2026-08-25: Sentinel-2 was the only caller and now
    # groups by year. Kept because the shape is right for any future
    # sub-annual source, and because deleting it would make the reason
    # S2 moved harder to find, not easier.
    "quarter": lambda d: (d.year, (d.month - 1) // 3 + 1),
    "decade": lambda d: ((d.year // 10) * 10,),
}


# ── group_key: the one text encoding of a selection period ────────────────────

# One encoding, one place. The ledger (timeline_task_years.group_key), the
# reconciler, and every selector that buckets by period all speak these
# strings, so a heal script asking "did landsat 1993 ever succeed" and the
# code that decided it are comparing the same token. The imagery
# normalization ADR (docs/adr/0001, rule 2) makes parcel_scenes.group_key the
# fourth speaker of it.
#
# Ordering note: every encoding is prefixed by a four-digit year, so
# lexicographic order over these keys equals chronological order. Callers
# that used to sort integer years rely on that; a source predating year 1000
# would break it.
_GROUP_KEY_ENCODERS: dict[str, Callable[[tuple[int, ...]], str]] = {
    "year": lambda parts: f"{parts[0]:04d}",
    "quarter": lambda parts: f"{parts[0]:04d}Q{parts[1]}",
    "decade": lambda parts: f"{parts[0]:04d}s",
}

# A source whose attempted set is not enumerable from configuration records
# its whole-search outcome here rather than inventing a period range. Today
# that is usgs_topo, which issues one untimed TNM query and learns which
# decades exist only from the response (INVESTIGATION section 3e).
WHOLE_SOURCE_GROUP_KEY = "*"


# ── Attempted set per source: what current code could still ask about ─────────

# A group outside this set cannot be turned into "ok" by any run of current
# code, so treating it as retryable forever is a policy gap (Y3,
# docs/audits/2026-08-m3/STATUS.md): e6afa9b removed 1990 from
# census.DECENNIAL_YEARS, so the pre-trim 1990 absent/api_no_data rows became
# permanently — and wrongly — "retryable". Selection filters on this; a group
# outside it moves to ledger_gaps.py's ``stale`` bucket instead of vanishing.
#
# Imagery sources whose loop covers "start year through today" read their
# floor from IMAGERY_SOURCE_START_YEAR, the same table tasks/timeline.py's
# ``_SOURCES`` builds start_year/start_date from, so a changed floor cannot
# drift the two apart. Census's calendar is an explicit list per dataset,
# imported from app.services.census rather than copied. usgs_topo has no
# per-decade attempted set (INVESTIGATION section 3e) — one untimed search
# either ran or didn't, so its only attempted group is the whole-source key.
IMAGERY_SOURCE_START_YEAR: dict[str, int] = {
    "naip": 2010,
    "landsat": 1984,
    "sentinel2": 2015,
}


def attempted_group_keys(source: str) -> set[str]:
    """Every group_key current code could record an outcome for, this source.

    Raises ``ValueError`` for a ledger source this function does not know —
    silently returning an empty set would make every group of a new source
    look stale on day one.
    """
    if source == "census_decennial":
        from app.services.census import DECENNIAL_YEARS

        return {encode_group_key("year", y) for y in DECENNIAL_YEARS}
    if source == "census_acs5":
        from app.services.census import ACS5_YEARS

        return {encode_group_key("year", y) for y in ACS5_YEARS}
    if source in IMAGERY_SOURCE_START_YEAR:
        start = IMAGERY_SOURCE_START_YEAR[source]
        return {encode_group_key("year", y) for y in range(start, date.today().year + 1)}
    if source == "usgs_topo":
        return {WHOLE_SOURCE_GROUP_KEY}
    raise ValueError(f"Unknown ledger source: {source!r}")


def encode_group_key(scope: str, value: date | int) -> str:
    """Encode a capture date (or bare year) as this scope's group key.

    ``year`` -> ``"1993"``; ``quarter`` -> ``"1993Q3"``; ``decade`` ->
    ``"1960s"``. An ``int`` is read as a calendar year, which is what the
    topo path and the census year lists have in hand — they never build a
    date just to bucket it.
    """
    as_date = date(value, 1, 1) if isinstance(value, int) else value
    return _GROUP_KEY_ENCODERS[scope](SELECTION_SCOPES[scope](as_date))


def decode_group_key(scope: str, key: str) -> tuple[date, date]:
    """Return the inclusive (start, end) dates the key covers.

    The inverse of :func:`encode_group_key`, and the reason the ledger's key
    is a targeting instruction rather than a label: a heal that finds
    ``landsat`` / ``1993`` / ``failed`` can turn it straight into the STAC
    datetime range that failed. Raises ValueError on a key this scope cannot
    have produced.
    """
    if scope == "year":
        year = _parse_key_year(key, key)
        return date(year, 1, 1), date(year, 12, 31)
    if scope == "quarter":
        head, sep, tail = key.partition("Q")
        if not sep or not tail.isdigit() or not 1 <= int(tail) <= 4:
            raise ValueError(f"Not a quarter group key: {key!r}")
        year, quarter = _parse_key_year(head, key), int(tail)
        start = date(year, 3 * (quarter - 1) + 1, 1)
        end_month = 3 * quarter
        last_day = 31 if end_month in (3, 12) else 30
        return start, date(year, end_month, last_day)
    if scope == "decade":
        if not key.endswith("s"):
            raise ValueError(f"Not a decade group key: {key!r}")
        decade = _parse_key_year(key[:-1], key)
        return date(decade, 1, 1), date(decade + 9, 12, 31)
    raise ValueError(f"Unknown selection scope: {scope!r}")


def _parse_key_year(text: str, key: str) -> int:
    if len(text) != 4 or not text.isdigit():
        raise ValueError(f"Group key carries no four-digit year: {key!r}")
    return int(text)


# ── The selection write path: one selection, one shape ────────────────────────

# Steps 2 and 4 of docs/adr/0001-imagery-normalization.md. Step 2 made this a
# dual-write, writing `scenes` and `parcel_scenes` alongside the denormalized
# table; step 3 moved the serving reads onto them; step 4 deleted the old
# write, so what is below is now the only place a selection is stored.

#: What a `scenes` row written by the pipeline says about itself: the facts
#: came from the STAC item at selection time, so `footprint` is populated from
#: birth and the row was never a copy of a denormalized row. Migration 0017.
SCENE_PROVENANCE_SELECTION = "selection"

# Platform prefixes that name a satellite unambiguously. Anything else is
# NULL — a platform column that guesses is worse than one that is empty.
# LT04 and S2C are here because both appear in real item ids; the ADR's list
# predates Sentinel-2C's launch. Step 1's backfill imported this rather than
# spelling the prefixes itself, so the backfilled and pipeline-written rows
# could not disagree; the backfill is gone and the rule it shared is here.
_LANDSAT_PLATFORMS = frozenset({"LT04", "LT05", "LE07", "LC08", "LC09"})
_SENTINEL_PLATFORMS = frozenset({"S2A", "S2B", "S2C"})


def platform_for(item_id: str) -> str | None:
    """The satellite the item id names, or None when it does not name one."""
    if item_id[:4] in _LANDSAT_PLATFORMS:
        return item_id[:4]
    if item_id[:3] in _SENTINEL_PLATFORMS:
        return item_id[:3]
    return None


# NORM-11. Planetary Computer's `properties.gsd` carries float-representation
# noise: the 505-row production enrichment found seven distinct spellings of
# 0.6 m — 0.5999999999999901 through 0.6000000000000097 — across eight rows
# (ENRICH-PROD-REPORT-2.md F2, confirmed against PC's own item JSON). Stored
# verbatim, `WHERE resolution_m = 0.6` silently misses those rows, a GROUP BY
# invents buckets, and MapView's resolution chip renders the noise.
#
# The rule: round to two decimals, once, at write time, in this one function.
# Two decimals is chosen against the values that actually occur — NAIP 0.3 /
# 0.5 / 0.6 / 1.0, Landsat 30, Sentinel-2 10 — whose closest pair is 0.1 m
# apart, so rounding can never merge two real resolutions, and it absorbs
# noise four orders of magnitude larger than the ~1e-14 observed.
#
# What it costs, stated because it is a real loss: the upstream double is not
# recoverable from the column. `resolution_m` answers "how fine is this
# image", whose honest answer is a nominal resolution; anyone needing the
# exact `gsd` is one STAC fetch from it, and it was never true that the column
# held it — for NAIP it held the constant 1.0 (NORM-9).
_RESOLUTION_DECIMALS = 2


def normalize_resolution_m(value: object) -> float | None:
    """A STAC ``gsd`` as a nominal resolution, or None if it is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), _RESOLUTION_DECIMALS)


@dataclass(frozen=True)
class SelectedScene:
    """One item this run selected, with every fact the write path needs.

    Built once per item. It carried both write shapes through step 2's
    dual-write — one object, so the two tables could not disagree about a row
    they were written from together — and that is why ``resolution_m`` is
    resolved here rather than derived twice. Step 4 left one shape; the class
    stays as the single place an item's facts are read out of a STAC item.

    ``mosaic`` holds the *additional* NAIP tiles only. The primary is this
    object and is never a member of its own mosaic, matching
    ``parcel_scenes.mosaic_scene_ids``.
    """

    source: str
    collection: str
    item_id: str
    capture_date: date
    cog_url: str
    thumbnail_url: str | None = None
    resolution_m: float | None = None
    cloud_cover_pct: float | None = None
    bbox_wkt: str | None = None
    footprint_wkt: str | None = None
    platform: str | None = None
    mosaic: tuple[SelectedScene, ...] = ()

    @classmethod
    def from_stac_item(
        cls,
        item: dict[str, object],
        *,
        source: str,
        collection: str,
        cog_url: str,
        default_resolution_m: float | None = None,
        mosaic: Sequence[SelectedScene] = (),
    ) -> SelectedScene:
        """Read one STAC item into the facts both tables store.

        ``cog_url`` is passed in rather than re-extracted: the caller has
        already had to decide what to do with an item carrying no COG asset,
        and deriving it twice invites the two answers to differ.

        ``default_resolution_m`` is the per-source constant, and is used
        **only** when the item carries no ``gsd``. NORM-9 is that NAIP's
        constant 1.0 was written even when the item said 0.3, so the item wins
        wherever it speaks; Landsat and Sentinel-2 items that carry no
        item-level ``gsd`` keep the constant they have always had.
        """
        from app.services import stac as stac_service

        raw_props = item.get("properties")
        props: Mapping[str, object] = raw_props if isinstance(raw_props, dict) else {}
        item_id = str(item.get("id"))

        footprint_wkt, complaint = stac_service.extract_footprint_wkt(item)
        if complaint is not None:
            # Not a refusal: a scene with a NULL footprint is the state every
            # backfilled row is already in, and the item's identity is not in
            # question. Logged so the population stays countable.
            # NORM-31: a complaint can also arrive with a footprint, when the
            # repair discarded part of a multipart result. The message names
            # which happened rather than claiming a NULL either way.
            logger.warning(
                "Selected item has no storable footprint"
                if footprint_wkt is None
                else "Selected item's footprint was repaired",
                extra={
                    "source": source,
                    "collection": collection,
                    "stac_item_id": item_id,
                    "reason": complaint,
                },
            )

        cloud_cover = props.get("eo:cloud_cover")
        return cls(
            source=source,
            collection=collection,
            item_id=item_id,
            capture_date=stac_service.extract_capture_date(item),
            cog_url=cog_url,
            thumbnail_url=stac_service.extract_thumbnail_url(item),
            resolution_m=normalize_resolution_m(props.get("gsd")) or default_resolution_m,
            cloud_cover_pct=float(cloud_cover) if isinstance(cloud_cover, (int, float)) else None,
            bbox_wkt=stac_service.extract_bbox_wkt(item),
            footprint_wkt=footprint_wkt,
            platform=platform_for(item_id),
            mosaic=tuple(mosaic),
        )


def _ensure_scene(db: Session, selection: SelectedScene, fetched_at: datetime) -> str:
    """Return this item's ``scenes.id``, inserting the row if it is absent.

    Insert-only, per the ADR step-2 decision: a catalogued item keeps every
    fact it was first written with. Re-encountering an item is not evidence
    that its stored facts are stale — the pipeline sees the same item across
    every parcel that serves it — and refreshing item facts is a separate
    mechanism that does not exist yet. ``ON CONFLICT DO NOTHING`` rather than a
    check-then-insert so a concurrent worker inserting the same item is an
    ordinary outcome rather than an IntegrityError that aborts the
    reconciler's transaction.
    """
    postgres = _is_postgres(db)
    footprint_expr = "ST_GeomFromEWKT(:footprint)" if postgres else ":footprint"
    bbox_expr = "ST_GeomFromEWKT(:bbox)" if postgres else ":bbox"
    scene_id = str(uuid.uuid4())
    returned = db.execute(
        sa_text(
            "INSERT INTO scenes"
            " (id, source, collection, item_id, capture_date, footprint, bbox,"
            "  cog_url, thumbnail_url, resolution_m, cloud_cover_pct, platform,"
            "  provenance, fetched_at)"
            " VALUES (:id, :source, :collection, :item_id, :capture_date,"
            f" {footprint_expr}, {bbox_expr},"
            " :cog_url, :thumbnail_url, :resolution_m, :cloud_cover_pct,"
            " :platform, :provenance, :fetched_at)"
            " ON CONFLICT (collection, item_id) DO NOTHING"
            " RETURNING id"
        ),
        {
            "id": scene_id,
            "source": selection.source,
            "collection": selection.collection,
            "item_id": selection.item_id,
            "capture_date": selection.capture_date.isoformat(),
            "footprint": selection.footprint_wkt,
            "bbox": selection.bbox_wkt,
            "cog_url": selection.cog_url,
            "thumbnail_url": selection.thumbnail_url,
            "resolution_m": selection.resolution_m,
            "cloud_cover_pct": selection.cloud_cover_pct,
            "platform": selection.platform,
            "provenance": SCENE_PROVENANCE_SELECTION,
            "fetched_at": fetched_at.isoformat(),
        },
    ).scalar()
    if returned is not None:
        return str(returned)

    existing = db.execute(
        sa_text("SELECT id FROM scenes WHERE collection = :collection AND item_id = :item_id"),
        {"collection": selection.collection, "item_id": selection.item_id},
    ).scalar()
    return str(existing)


def decode_mosaic_scene_ids(value: object) -> list[str]:
    """A stored ``mosaic_scene_ids`` as a list of id strings.

    PostgreSQL hands back ``uuid[]`` as a list; the SQLite variant stores the
    same list as JSON text and hands back the text. Public because
    ``scripts/remove_uncovered_snapshots.py`` reads the column too, and two
    hand-rolled decoders for one column is how the two databases start
    disagreeing about what a mosaic is.
    """
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in decoded] if isinstance(decoded, list) else []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return []


def _upsert_parcel_scene(
    db: Session,
    *,
    parcel_id: uuid.UUID,
    source: str,
    group_key: str,
    scene_id: str,
    mosaic_scene_ids: list[str],
    selected_at: datetime,
    selected_by: str | None,
) -> None:
    """Insert or update the one row for (parcel, source, group_key).

    UNIQUE (parcel_id, source, group_key) makes replacement an update: the row
    keeps its primary key and gains the new scene rather than being deleted
    and re-inserted.

    An unchanged selection is left alone entirely. ``selected_at`` then means
    "when this parcel first came to serve this scene for this period", which is
    an answer; bumping it on every sweep would make the column mean "when the
    last sweep ran", which every task's ``completed_at`` already says.
    """
    postgres = _is_postgres(db)
    mosaic_expr = "CAST(:mosaic AS uuid[])" if postgres else ":mosaic"
    if postgres:
        mosaic_param: object = mosaic_scene_ids or None
    else:
        mosaic_param = json.dumps(mosaic_scene_ids) if mosaic_scene_ids else None

    existing = db.execute(
        sa_text(
            "SELECT id, scene_id, mosaic_scene_ids FROM parcel_scenes"
            " WHERE parcel_id = :parcel_id AND source = :source AND group_key = :group_key"
        ),
        {"parcel_id": str(parcel_id), "source": source, "group_key": group_key},
    ).first()

    if existing is None:
        db.execute(
            sa_text(
                "INSERT INTO parcel_scenes"
                " (id, parcel_id, source, group_key, scene_id, mosaic_scene_ids,"
                "  selected_at, selected_by)"
                " VALUES (:id, :parcel_id, :source, :group_key, :scene_id,"
                f" {mosaic_expr}, :selected_at, :selected_by)"
            ),
            {
                "id": str(uuid.uuid4()),
                "parcel_id": str(parcel_id),
                "source": source,
                "group_key": group_key,
                "scene_id": scene_id,
                "mosaic": mosaic_param,
                "selected_at": selected_at.isoformat(),
                "selected_by": selected_by,
            },
        )
        return

    unchanged = str(existing.scene_id) == scene_id and decode_mosaic_scene_ids(
        existing.mosaic_scene_ids
    ) == list(mosaic_scene_ids)
    if unchanged:
        return

    db.execute(
        sa_text(
            "UPDATE parcel_scenes SET scene_id = :scene_id,"
            f" mosaic_scene_ids = {mosaic_expr},"
            " selected_at = :selected_at, selected_by = :selected_by"
            " WHERE id = :id"
        ),
        {
            "id": str(existing.id),
            "scene_id": scene_id,
            "mosaic": mosaic_param,
            "selected_at": selected_at.isoformat(),
            "selected_by": selected_by,
        },
    )


def _write_selection_shapes(
    db: Session,
    parcel_id: uuid.UUID,
    source: str,
    selections: Sequence[SelectedScene],
    scope: str,
) -> None:
    """Write the normalized shape of everything this run selected."""
    now = datetime.now(UTC)
    # The image that made the selection, so a row's provenance is a deploy
    # rather than a date. Backfilled rows stay NULL; that distinction is the
    # audit trail working (ADR amendment, "Selection provenance is not
    # recoverable"). A local image reports "dev" and says so honestly.
    selected_by = get_settings().git_sha
    for selection in selections:
        scene_id = _ensure_scene(db, selection, now)
        mosaic_ids = [_ensure_scene(db, tile, now) for tile in selection.mosaic]
        _upsert_parcel_scene(
            db,
            parcel_id=parcel_id,
            source=source,
            group_key=encode_group_key(scope, selection.capture_date),
            scene_id=scene_id,
            mosaic_scene_ids=mosaic_ids,
            selected_at=now,
            selected_by=selected_by,
        )


def _delete_parcel_scene_for_item(
    db: Session,
    parcel_id: uuid.UUID,
    source: str,
    group_key: str,
    collection: str,
    item_id: str,
) -> None:
    """Mirror a suppressed-delete into ``parcel_scenes``.

    Only when the row for that group actually serves the deleted item: a
    different scene the group has since moved to is a selection this run said
    nothing about, and the two tables agreeing about which groups exist is the
    property that must hold, not "delete whatever is there".
    """
    db.execute(
        sa_text(
            "DELETE FROM parcel_scenes"
            " WHERE parcel_id = :parcel_id AND source = :source"
            "   AND group_key = :group_key"
            "   AND scene_id IN (SELECT id FROM scenes"
            "                    WHERE collection = :collection AND item_id = :item_id)"
        ),
        {
            "parcel_id": str(parcel_id),
            "source": source,
            "group_key": group_key,
            "collection": collection,
            "item_id": item_id,
        },
    )


def reconcile_source_snapshots(
    db: Session,
    parcel_id: uuid.UUID,
    source: str,
    selected: Iterable[SelectedScene],
    *,
    scope: str = "year",
    suppressed: Mapping[str, set[str]] | None = None,
) -> int:
    """Reconcile what this parcel serves for ``source`` with what this run chose.

    Two things happen here, and only one of them is a delete:

    * A group **this run selected** is replaced in place by the upsert in
      ``_write_selection_shapes`` — ``UNIQUE (parcel_id, source, group_key)``
      means the row keeps its primary key and gains the new scene. That is the
      case the old denormalized table needed an explicit delete for, because
      its unique key was ``(parcel_id, stac_item_id)``: a re-run that picked a
      *different* item for a group — which is exactly what Landsat band
      re-validation does when the original scene breaks — inserted alongside
      the old row instead of replacing it, and the timeline showed the same
      period twice. The normalized shape cannot express that, so step 4's
      cutover turned those deletes into updates and this function no longer
      issues them. **The one delete left is the suppressed case below.**
    * A group **absent** from this run's selection is left alone, with the one
      ``suppressed`` exception.

    ``scope`` must name the unit the source's selector groups by, because
    deletion is confined to the groups this run actually selected:

        year     select_naip_items, select_landsat_items,
                 select_sentinel_items
        decade   select_topo_items

    Get this wrong in one direction and superseded rows survive (a topo
    map replaced by another map from the same decade but a different year
    is invisible to year-scoping); get it wrong in the other and rows the
    selector never reconsidered are deleted.

    A group missing from the selection is ambiguous: it can mean the
    source no longer offers it, but more often it means that chunk's
    search failed and was skipped, and deleting on that basis would turn
    a transient upstream error into permanent data loss. So absent groups
    are always left alone.

    ``suppressed`` is the one exception, and the only thing in the system
    that may say a served row is wrong. It maps a group key to the item ids
    **this run** positively identified as not servable — the tiles the NAIP
    point-coverage gate rejected, or a selected item carrying no COG asset.
    A row in one of those groups whose item id is named is deleted even
    though the group is absent from the selection.

    Three properties make that safe, and none of them is decoration:

    * **This run only.** The mapping comes from the run's own outcomes, not
      from a ledger query. A suppression corrected since would otherwise
      license a delete years later.
    * **Item ids, not periods.** A *different* item that happens to fall in
      the same year is left alone, which makes the rule a statement about an
      item rather than about a period.
    * **``suppressed`` only.** An ``absent/*`` outcome is not authority — all
      four absent reasons mean "the fetch completed and found nothing usable
      *this time*", and ``naip absent/no_scenes`` alone is 1,848 latest
      ledger rows fleet-wide. A rule that deleted on absence would delete on
      the largest population in the ledger. ``failed`` knows strictly less
      than ``absent``, and ``indeterminate`` names a site that could not
      decide.

    Parcel ``e513188c`` is the live case: it serves a NAIP 2023 card built
    from tile ``nj_m_4007309_sw_18_030_…``, and the gate records that year
    ``suppressed``/``naip_no_point_coverage`` naming that same tile. The
    gate could refuse to *write* such a row; it had no way to *remove* one.

    Mosaics are safe because the comparison is against the full set of
    selected item ids: NAIP's several tiles for one year are all in
    ``selected``, so all of them are kept.

    Returns the number of **superseded** served rows: the ones replaced in
    place plus the ones the suppressed rule deleted. That is the same
    population the pre-step-4 return value counted, which was a delete count
    only because replacement was spelled as a delete then.

    **Where the selection is written (ADR steps 2 and 4).** Every element of
    ``selected`` gets the normalized shape written here: a ``scenes`` row per
    item (insert-only, mosaic tiles included) and the ``parcel_scenes`` row
    for its group.

    ``selected`` used to also accept a bare ``(item_id, capture_date)`` tuple,
    for a caller that knew a group had been superseded but held no item facts.
    **Step 4 removed that form because it stopped being implementable**, not
    to tidy the signature: superseding a group is now spelled as an upsert of
    the row, and an upsert needs the new scene. A tuple caller would have
    matched a superseded row, had nothing to replace it with, and returned
    having changed nothing — a silent no-op wearing the signature of a
    reconcile. The old shape hid this because superseding was a DELETE, which
    needs no facts about the replacement. No production caller ever passed it;
    both call sites in ``app/tasks/timeline.py`` pass ``SelectedScene``.

    **This function's commit is the persist loop's only commit** (ADR step 4,
    STATUS.md NORM-14). Step 2 left ``upsert_imagery_snapshot`` committing per
    row earlier in ``_search_and_persist_source``, so a crash between the loop
    and this call left rows in one shape and not the other. Step 4 deleted
    that write and with it that commit, so the ``scenes`` inserts, the
    ``parcel_scenes`` upserts, the suppressed deletes **and the ledger's
    staged ``ok`` rows** — which the per-row commit used to carry — all land in
    one transaction. Call it after the persist loop, never before: nothing the
    loop staged is durable until this commits.
    """
    keep: set[str] = set()
    groups: set[str] = set()
    selections: list[SelectedScene] = list(selected)
    for entry in selections:
        # Only the primary joins ``keep``. A mosaic's additional tiles are not
        # served periods of their own — they are ``scenes`` rows the group's
        # ``mosaic_scene_ids`` references — so treating one as a kept
        # selection would claim a second row in one group, which is G3's shape
        # and which UNIQUE (parcel_id, source, group_key) now refuses outright.
        keep.add(entry.item_id)
        groups.add(encode_group_key(scope, entry.capture_date))

    suppressed = suppressed or {}
    if not keep and not suppressed:
        return 0

    # The existing-rows pull, against the shape that now stores the answer.
    # ``group_key`` is read rather than re-derived from a capture date: the
    # column holds the string ``encode_group_key`` produced when the row was
    # written, so the diff compares stored keys to this run's keys instead of
    # re-deriving one side of the comparison (the old shape had no group_key
    # column and had no choice).
    rows = db.execute(
        sa_text(
            "SELECT ps.id AS id, ps.group_key AS group_key,"
            " s.collection AS collection, s.item_id AS item_id"
            " FROM parcel_scenes ps JOIN scenes s ON s.id = ps.scene_id"
            " WHERE ps.parcel_id = :parcel_id AND ps.source = :source"
        ),
        {"parcel_id": str(parcel_id), "source": source},
    ).all()

    # Rows this run supersedes by *replacing* them: the group is one this run
    # selected, and it currently serves an item this run did not pick. No
    # delete is issued for these — ``_write_selection_shapes`` upserts the
    # group and the row keeps its id. Counted, because "how many served
    # periods did this run change" is what the return value has always meant.
    replaced: list[object] = []
    # (group_key, collection, item_id) per suppressed delete. A superseded row
    # whose group this run *selected* is never in here; only the absent-group
    # suppressed exception deletes.
    suppressed_rows: list[tuple[str, str, str]] = []
    for row in rows:
        if row.item_id in keep:
            continue
        group_key = str(row.group_key)
        if group_key in groups:
            replaced.append(row.id)
        elif row.item_id in suppressed.get(group_key, ()):
            suppressed_rows.append((group_key, str(row.collection), str(row.item_id)))
            logger.warning(
                "Deleting a served scene this run suppressed",
                extra={
                    "parcel_id": str(parcel_id),
                    "source": source,
                    "group": group_key,
                    "stac_item_id": row.item_id,
                },
            )

    if not suppressed_rows and not selections:
        return 0

    for group_key, collection, item_id in suppressed_rows:
        _delete_parcel_scene_for_item(db, parcel_id, source, group_key, collection, item_id)

    _write_selection_shapes(db, parcel_id, source, selections, scope)

    db.commit()

    superseded = len(replaced) + len(suppressed_rows)
    if not superseded:
        return 0

    logger.info(
        "Replaced superseded served scenes",
        extra={
            "parcel_id": str(parcel_id),
            "source": source,
            "replaced": len(replaced),
            "suppressed_deleted": len(suppressed_rows),
            "scope": scope,
            "groups": sorted(groups),
        },
    )
    return superseded


def _is_postgres(db: Session) -> bool:
    """Return True if the bound engine is PostgreSQL (SQLite lacks PostGIS)."""
    try:
        return db.get_bind().dialect.name == "postgresql"
    except Exception:
        return False


def _bbox_select_sql(column: str) -> str:
    """SQL fragment for the four bbox component columns.

    On PostgreSQL, uses PostGIS ``ST_XMin``/``ST_YMin``/``ST_XMax``/``ST_YMax``.
    On SQLite (test DB, no PostGIS), returns NULL columns so the query still
    executes and the Python-side bbox tuple is None.

    ``column`` is the geometry expression to decompose: ``s.bbox``, for the
    joined ``scenes`` read that is the only caller since the step-3 cutover.
    """
    return (
        f"ST_XMin({column}) AS bbox_w, ST_YMin({column}) AS bbox_s, "
        f"ST_XMax({column}) AS bbox_e, ST_YMax({column}) AS bbox_n"
    )


def _bbox_select_sql_sqlite() -> str:
    return "NULL AS bbox_w, NULL AS bbox_s, NULL AS bbox_e, NULL AS bbox_n"


def _row_bbox(row: RowMapping) -> tuple[float, float, float, float] | None:
    """Return (w, s, e, n) from a row's bbox_w/s/e/n columns, or None if absent."""
    w = row.get("bbox_w")
    s = row.get("bbox_s")
    e = row.get("bbox_e")
    n = row.get("bbox_n")
    if w is None or s is None or e is None or n is None:
        return None
    return (float(w), float(s), float(e), float(n))


# ── The served-scene read path (ADR 0001 step 3) ──────────────────────────────
#
# These read the normalized shape: ``parcel_scenes`` says which scene a parcel
# serves for a period, ``scenes`` holds the item's facts once. The reads they
# replaced pulled every fact out of a row that copied it once per parcel; they
# were deleted by step 3's cutover, after ``scripts/compare_read_paths.py``
# proved the two paths agreed field for field.
#
# **Still raw SQL, and for the same reason the old reads were.** ``scenes``
# carries two ``Geometry`` columns, so ``select(Scene)`` makes GeoAlchemy2 emit
# ``ST_AsEWKB(bbox)`` — a function the SQLite test database does not have, and
# a payload the serving path would then have to decode only to throw away.
# ``ST_XMin``/``ST_YMin``/``ST_XMax``/``ST_YMax`` hand back the four floats the
# response actually carries, and ``_bbox_select_sql_sqlite`` hands back NULLs so
# the same query runs on the test database. The dodge is inherited deliberately,
# not by copy-paste.

_SERVED_SCENE_COLUMNS = (
    "ps.id AS id, ps.parcel_id AS parcel_id, ps.source AS source,"
    " ps.mosaic_scene_ids AS mosaic_scene_ids,"
    " s.capture_date AS capture_date, s.item_id AS stac_item_id,"
    " s.collection AS stac_collection, s.cog_url AS cog_url,"
    " s.thumbnail_url AS thumbnail_url, s.resolution_m AS resolution_m,"
    " s.cloud_cover_pct AS cloud_cover_pct"
)


def _mosaic_cog_urls(db: Session, rows: Sequence[RowMapping]) -> dict[str, list[str]]:
    """``{parcel_scenes.id: [cog_url, ...]}`` for the rows that carry a mosaic.

    One query for the whole page, then ordered in Python. Resolving the array
    in SQL would need ``unnest ... WITH ORDINALITY`` to keep its order, which
    SQLite has no answer to — and this is the ordering the old shape's
    ``additional_cog_urls`` array carried, so it is worth having in one place
    that a test can point at on either database.

    A reference that resolves to no ``scenes`` row is logged and dropped from
    that row's list. Production has never held one (0 dangling references
    across 613, `STEP2-PROD-REPORT.md` §5.1), and the alternative — refusing
    the whole listing — turns one missing mosaic tile into a dead timeline,
    where the primary COG still renders and the gap is the same one an
    unsignable component already leaves (`api/v1/imagery.py`).
    """
    wanted: dict[str, list[str]] = {}
    needed: set[str] = set()
    for row in rows:
        ids = decode_mosaic_scene_ids(row["mosaic_scene_ids"])
        if not ids:
            continue
        wanted[str(row["id"])] = ids
        needed.update(ids)
    if not needed:
        return {}

    ordered = sorted(needed)
    placeholders = ",".join(f":m{i}" for i in range(len(ordered)))
    params = {f"m{i}": sid for i, sid in enumerate(ordered)}
    url_by_id = {
        str(sid): url
        for sid, url in db.execute(
            sa_text(f"SELECT id, cog_url FROM scenes WHERE id IN ({placeholders})"),
            params,
        ).all()
    }

    out: dict[str, list[str]] = {}
    for served_id, ids in wanted.items():
        urls = []
        for sid in ids:
            url = url_by_id.get(sid)
            if url is None:
                logger.error(
                    "Mosaic reference resolves to no scene",
                    extra={"parcel_scene_id": served_id, "scene_id": sid},
                )
                continue
            urls.append(url)
        if urls:
            out[served_id] = urls
    return out


def _served_scene_rows(db: Session, where_sql: str, params: dict[str, object]) -> list[RowMapping]:
    bbox_select = _bbox_select_sql("s.bbox") if _is_postgres(db) else _bbox_select_sql_sqlite()
    sql = sa_text(
        f"""
        SELECT {_SERVED_SCENE_COLUMNS},
               {bbox_select}
        FROM parcel_scenes ps
        JOIN scenes s ON s.id = ps.scene_id
        WHERE {where_sql}
        ORDER BY s.capture_date ASC, ps.source ASC
        """
    )
    return list(db.execute(sql, params).mappings().all())


def _to_served_row(row: RowMapping, mosaic: dict[str, list[str]]) -> ServedSceneRow:
    return ServedSceneRow(
        id=uuid.UUID(str(row["id"])),
        parcel_id=uuid.UUID(str(row["parcel_id"])),
        source=row["source"],
        capture_date=date.fromisoformat(str(row["capture_date"])),
        stac_item_id=row["stac_item_id"],
        stac_collection=row["stac_collection"],
        cog_url=row["cog_url"],
        additional_cog_urls=mosaic.get(str(row["id"])),
        thumbnail_url=row["thumbnail_url"],
        cloud_cover_pct=row["cloud_cover_pct"],
        resolution_m=row["resolution_m"],
        bbox=_row_bbox(row),
    )


def get_served_scenes(
    db: Session,
    parcel_id: uuid.UUID,
    source: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[ServedSceneRow]:
    """What this parcel serves, sorted by capture_date ascending.

    The normalized replacement for the pre-cutover listing read: same row
    shape, same filters, read from ``parcel_scenes`` joined to ``scenes``.
    ``additional_cog_urls`` is reconstructed from ``mosaic_scene_ids`` in array
    order.

    **The sort adds a tie-break the old query did not have.** Both queries say
    ``capture_date ASC``, which leaves rows sharing a date in whatever order
    the plan produced — and two sources really can land on one date, so the
    listing's order among them was never stable, on either shape. Ordering by
    ``source`` after the date makes it stable. Within a source a tie is
    impossible: ``group_key`` is derived from ``capture_date``, so one date is
    one group is one row.
    """
    where = ["ps.parcel_id = :parcel_id"]
    params: dict[str, object] = {"parcel_id": str(parcel_id)}
    if source:
        where.append("ps.source = :source")
        params["source"] = source
    if start_date:
        where.append("s.capture_date >= :start_date")
        params["start_date"] = start_date.isoformat()
    if end_date:
        where.append("s.capture_date <= :end_date")
        params["end_date"] = end_date.isoformat()

    rows = _served_scene_rows(db, " AND ".join(where), params)
    mosaic = _mosaic_cog_urls(db, rows)
    return [_to_served_row(row, mosaic) for row in rows]


def get_served_scene_by_id(db: Session, served_id: uuid.UUID) -> ServedSceneRow | None:
    """One served scene by its ``parcel_scenes`` id, or None.

    The normalized replacement for ``get_snapshot_by_id``. The id the API
    hands out and the id it resolves are both this table's primary key, so
    the two move together.
    """
    rows = _served_scene_rows(db, "ps.id = :id", {"id": str(served_id)})
    if not rows:
        return None
    mosaic = _mosaic_cog_urls(db, rows)
    return _to_served_row(rows[0], mosaic)


def count_served_scenes(db: Session, parcel_id: uuid.UUID, source: str) -> int:
    """How many periods this parcel serves for one source.

    The normalized replacement for the pre-cutover count, and the same
    semantics: **rows, not scenes.** A NAIP mosaic is one served period
    however many tiles it composites, exactly as it was one denormalized row
    with a populated ``additional_cog_urls`` array.
    """
    row = db.execute(
        sa_text(
            "SELECT COUNT(*) FROM parcel_scenes WHERE parcel_id = :parcel_id AND source = :source"
        ),
        {"parcel_id": str(parcel_id), "source": source},
    ).scalar()
    return int(row or 0)


def served_scene_bounds(db: Session, parcel_id_strs: Sequence[str]) -> dict[str, tuple[str, str]]:
    """``{parcel_id: (earliest_served_id, latest_served_id)}`` for the featured cards.

    The normalized replacement for ``featured._snapshot_ids_for_parcels``, and
    a move out of the route handler while it is being rewritten anyway
    (CLAUDE.md: business logic lives in services). One query for any number of
    parcels, ordered so the bucketing below is a single pass.

    Ties are broken by whatever order the database returns, exactly as the old
    query left them: two rows sharing a capture_date are both defensible
    answers to "earliest", and inventing a tie-break here would be a
    behaviour change smuggled into a cutover.
    """
    if not parcel_id_strs:
        return {}
    placeholders = ",".join(f":p{i}" for i in range(len(parcel_id_strs)))
    params = {f"p{i}": pid for i, pid in enumerate(parcel_id_strs)}
    rows = db.execute(
        sa_text(
            f"""
            SELECT ps.parcel_id, ps.id, s.capture_date
            FROM parcel_scenes ps
            JOIN scenes s ON s.id = ps.scene_id
            WHERE ps.parcel_id IN ({placeholders})
            ORDER BY ps.parcel_id, s.capture_date ASC
            """
        ),
        params,
    ).all()
    out: dict[str, tuple[str, str]] = {}
    for pid, sid, _capture_date in rows:
        pid_str = str(pid)
        sid_str = str(sid)
        if pid_str not in out:
            out[pid_str] = (sid_str, sid_str)
        else:
            out[pid_str] = (out[pid_str][0], sid_str)
    return out


def parcels_serving_source(db: Session, source: str) -> list[uuid.UUID]:
    """Every parcel that serves at least one period of ``source``.

    The normalized replacement for ``revalidate_landsat.landsat_parcels``'
    ``GROUP BY parcel_id`` over the pre-cutover table.
    """
    rows = db.execute(
        sa_text("SELECT DISTINCT parcel_id FROM parcel_scenes WHERE source = :source"),
        {"source": source},
    ).scalars()
    return [uuid.UUID(str(pid)) for pid in rows]

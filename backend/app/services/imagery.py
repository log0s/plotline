"""Imagery and timeline request service layer.

Handles database operations for imagery snapshots and timeline requests.
Business logic (STAC querying) lives in services/stac.py and tasks/timeline.py.

Note: ImagerySnapshot queries use raw SQL to avoid GeoAlchemy2 generating
PostGIS functions (AsEWKB, GeomFromEWKT) that are incompatible with SQLite
test databases.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
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


# ── Snapshot data class (PostGIS-free, SQLite-compatible) ─────────────────────


@dataclass
class ImagerySnapshotRow:
    """Lightweight representation of an imagery_snapshots row.

    Avoids importing the GeoAlchemy2 ORM model for reads, keeping the service
    layer compatible with both PostgreSQL (production) and SQLite (tests).
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
            if not prop_task or prop_task.status in ("skipped", "partial", "failed"):
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


def count_imagery_snapshots(
    db: Session,
    parcel_id: uuid.UUID,
    source: str,
) -> int:
    """Return the total number of imagery snapshots for a parcel + source."""
    row = db.execute(
        sa_text(
            "SELECT COUNT(*) FROM imagery_snapshots"
            " WHERE parcel_id = :parcel_id AND source = :source"
        ),
        {"parcel_id": str(parcel_id), "source": source},
    ).scalar()
    return int(row or 0)


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


def reconcile_source_snapshots(
    db: Session,
    parcel_id: uuid.UUID,
    source: str,
    selected: Iterable[tuple[str, date]],
    *,
    scope: str = "year",
    suppressed: Mapping[str, set[str]] | None = None,
) -> int:
    """Delete snapshots that this run's selection replaced.

    The upsert can't do this itself: its conflict target is
    (parcel_id, stac_item_id), so a re-run that picks a *different* scene
    for a group — which is exactly what Landsat band re-validation does
    when the original scene breaks — inserts alongside the old row instead
    of replacing it, and the timeline shows the same period twice.

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

    Returns the number of rows deleted. Call after persisting the new
    selection, never before — an interruption then leaves duplicates,
    which is recoverable, rather than an empty timeline, which isn't.
    """
    keep: set[str] = set()
    groups: set[str] = set()
    for stac_item_id, capture_date in selected:
        keep.add(stac_item_id)
        groups.add(encode_group_key(scope, capture_date))

    suppressed = suppressed or {}
    if not keep and not suppressed:
        return 0

    rows = db.execute(
        sa_text(
            "SELECT id, stac_item_id, capture_date FROM imagery_snapshots"
            " WHERE parcel_id = :parcel_id AND source = :source"
        ),
        {"parcel_id": str(parcel_id), "source": source},
    ).all()

    stale: list[object] = []
    suppressed_deleted = 0
    for row in rows:
        if row.stac_item_id in keep:
            continue
        captured = _capture_date(row.capture_date)
        if captured is None:
            continue
        group_key = encode_group_key(scope, captured)
        if group_key in groups:
            stale.append(row.id)
        elif row.stac_item_id in suppressed.get(group_key, ()):
            stale.append(row.id)
            suppressed_deleted += 1
            logger.warning(
                "Deleting a served snapshot this run suppressed",
                extra={
                    "parcel_id": str(parcel_id),
                    "source": source,
                    "group": group_key,
                    "stac_item_id": row.stac_item_id,
                },
            )

    if not stale:
        return 0

    for snapshot_id in stale:
        db.execute(
            sa_text("DELETE FROM imagery_snapshots WHERE id = :id"),
            {"id": str(snapshot_id)},
        )
    db.commit()

    logger.info(
        "Replaced superseded imagery snapshots",
        extra={
            "parcel_id": str(parcel_id),
            "source": source,
            "deleted": len(stale),
            "suppressed_deleted": suppressed_deleted,
            "scope": scope,
            "groups": sorted(groups),
        },
    )
    return len(stale)


def upsert_imagery_snapshot(
    db: Session,
    *,
    parcel_id: uuid.UUID,
    source: str,
    capture_date: date,
    stac_item_id: str,
    stac_collection: str,
    cog_url: str,
    additional_cog_urls: list[str] | None = None,
    thumbnail_url: str | None = None,
    resolution_m: float | None = None,
    cloud_cover_pct: float | None = None,
    bbox_wkt: str | None = None,
) -> bool:
    """Insert an imagery snapshot, refreshing URLs on conflict (idempotent).

    Uses raw SQL to avoid GeoAlchemy2's GeomFromEWKT on NULL values.
    ``ON CONFLICT … DO UPDATE`` keeps cog/thumbnail URLs current across
    re-runs.

    Returns True if a new row was inserted, False if an existing row was
    updated. Detection uses ``RETURNING id`` and compares against the
    would-be new UUID — works on both PostgreSQL and SQLite (test DB).
    """
    snap_id = uuid.uuid4()

    if bbox_wkt:
        sql = sa_text(
            """
            INSERT INTO imagery_snapshots
                (id, parcel_id, source, capture_date, stac_item_id, stac_collection,
                 bbox, cog_url, additional_cog_urls, thumbnail_url, resolution_m, cloud_cover_pct)
            VALUES
                (:id, :parcel_id, :source, :capture_date, :stac_item_id, :stac_collection,
                 ST_GeomFromEWKT(:bbox), :cog_url, :additional_cog_urls,
                 :thumbnail_url, :resolution_m, :cloud_cover_pct)
            ON CONFLICT (parcel_id, stac_item_id) DO UPDATE
                SET cog_url = EXCLUDED.cog_url,
                    additional_cog_urls = EXCLUDED.additional_cog_urls,
                    thumbnail_url = EXCLUDED.thumbnail_url
            RETURNING id
            """
        )
        params: dict[str, object] = {
            "id": str(snap_id),
            "parcel_id": str(parcel_id),
            "source": source,
            "capture_date": capture_date.isoformat(),
            "stac_item_id": stac_item_id,
            "stac_collection": stac_collection,
            "bbox": bbox_wkt,
            "cog_url": cog_url,
            "additional_cog_urls": additional_cog_urls,
            "thumbnail_url": thumbnail_url,
            "resolution_m": resolution_m,
            "cloud_cover_pct": cloud_cover_pct,
        }
    else:
        sql = sa_text(
            """
            INSERT INTO imagery_snapshots
                (id, parcel_id, source, capture_date, stac_item_id, stac_collection,
                 cog_url, additional_cog_urls, thumbnail_url, resolution_m, cloud_cover_pct)
            VALUES
                (:id, :parcel_id, :source, :capture_date, :stac_item_id, :stac_collection,
                 :cog_url, :additional_cog_urls, :thumbnail_url, :resolution_m, :cloud_cover_pct)
            ON CONFLICT (parcel_id, stac_item_id) DO UPDATE
                SET cog_url = EXCLUDED.cog_url,
                    additional_cog_urls = EXCLUDED.additional_cog_urls,
                    thumbnail_url = EXCLUDED.thumbnail_url
            RETURNING id
            """
        )
        params = {
            "id": str(snap_id),
            "parcel_id": str(parcel_id),
            "source": source,
            "capture_date": capture_date.isoformat(),
            "stac_item_id": stac_item_id,
            "stac_collection": stac_collection,
            "cog_url": cog_url,
            "additional_cog_urls": additional_cog_urls,
            "thumbnail_url": thumbnail_url,
            "resolution_m": resolution_m,
            "cloud_cover_pct": cloud_cover_pct,
        }

    returned_id = db.execute(sql, params).scalar()
    db.commit()
    return str(returned_id) == str(snap_id)


def _is_postgres(db: Session) -> bool:
    """Return True if the bound engine is PostgreSQL (SQLite lacks PostGIS)."""
    try:
        return db.get_bind().dialect.name == "postgresql"
    except Exception:
        return False


def _bbox_select_sql() -> str:
    """SQL fragment for the four bbox component columns.

    On PostgreSQL, uses PostGIS ``ST_XMin``/``ST_YMin``/``ST_XMax``/``ST_YMax``.
    On SQLite (test DB, no PostGIS), returns NULL columns so the query still
    executes and the Python-side bbox tuple is None.
    """
    return (
        "ST_XMin(bbox) AS bbox_w, ST_YMin(bbox) AS bbox_s, "
        "ST_XMax(bbox) AS bbox_e, ST_YMax(bbox) AS bbox_n"
    )


def _bbox_select_sql_sqlite() -> str:
    return "NULL AS bbox_w, NULL AS bbox_s, NULL AS bbox_e, NULL AS bbox_n"


def get_snapshot_by_id(db: Session, snapshot_id: uuid.UUID) -> ImagerySnapshotRow | None:
    """Return a single imagery snapshot by ID, or None if not found."""
    bbox_select = _bbox_select_sql() if _is_postgres(db) else _bbox_select_sql_sqlite()
    sql = sa_text(
        f"""
        SELECT id, parcel_id, source, capture_date, stac_item_id, stac_collection,
               cog_url, additional_cog_urls, thumbnail_url,
               resolution_m, cloud_cover_pct, created_at,
               {bbox_select}
        FROM imagery_snapshots
        WHERE id = :id
        """
    )
    row = db.execute(sql, {"id": str(snapshot_id)}).mappings().first()
    if not row:
        return None
    return ImagerySnapshotRow(
        id=uuid.UUID(str(row["id"])),
        parcel_id=uuid.UUID(str(row["parcel_id"])),
        source=row["source"],
        capture_date=date.fromisoformat(str(row["capture_date"])),
        stac_item_id=row["stac_item_id"],
        stac_collection=row["stac_collection"],
        cog_url=row["cog_url"],
        additional_cog_urls=row["additional_cog_urls"],
        thumbnail_url=row["thumbnail_url"],
        cloud_cover_pct=row["cloud_cover_pct"],
        resolution_m=row["resolution_m"],
        bbox=_row_bbox(row),
    )


def get_imagery_snapshots(
    db: Session,
    parcel_id: uuid.UUID,
    source: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[ImagerySnapshotRow]:
    """Return imagery snapshots for a parcel, sorted by capture_date ascending.

    Uses raw SQL to avoid GeoAlchemy2 AsEWKB calls on the bbox column.
    """
    where_clauses = ["parcel_id = :parcel_id"]
    params: dict[str, object] = {"parcel_id": str(parcel_id)}

    if source:
        where_clauses.append("source = :source")
        params["source"] = source
    if start_date:
        where_clauses.append("capture_date >= :start_date")
        params["start_date"] = start_date.isoformat()
    if end_date:
        where_clauses.append("capture_date <= :end_date")
        params["end_date"] = end_date.isoformat()

    where_sql = " AND ".join(where_clauses)
    bbox_select = _bbox_select_sql() if _is_postgres(db) else _bbox_select_sql_sqlite()
    sql = sa_text(
        f"""
        SELECT id, parcel_id, source, capture_date, stac_item_id, stac_collection,
               cog_url, additional_cog_urls, thumbnail_url,
               resolution_m, cloud_cover_pct, created_at,
               {bbox_select}
        FROM imagery_snapshots
        WHERE {where_sql}
        ORDER BY capture_date ASC
        """
    )

    rows = db.execute(sql, params).mappings().all()
    return [
        ImagerySnapshotRow(
            id=uuid.UUID(str(row["id"])),
            parcel_id=uuid.UUID(str(row["parcel_id"])),
            source=row["source"],
            capture_date=date.fromisoformat(str(row["capture_date"])),
            stac_item_id=row["stac_item_id"],
            stac_collection=row["stac_collection"],
            cog_url=row["cog_url"],
            additional_cog_urls=row["additional_cog_urls"],
            thumbnail_url=row["thumbnail_url"],
            cloud_cover_pct=row["cloud_cover_pct"],
            resolution_m=row["resolution_m"],
            bbox=_row_bbox(row),
        )
        for row in rows
    ]


def _row_bbox(row: RowMapping) -> tuple[float, float, float, float] | None:
    """Return (w, s, e, n) from a row's bbox_w/s/e/n columns, or None if absent."""
    w = row.get("bbox_w")
    s = row.get("bbox_s")
    e = row.get("bbox_e")
    n = row.get("bbox_n")
    if w is None or s is None or e is None or n is None:
        return None
    return (float(w), float(s), float(e), float(n))

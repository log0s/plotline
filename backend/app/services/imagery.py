"""Imagery and timeline request service layer.

Handles database operations for imagery snapshots and timeline requests.
Business logic (STAC querying) lives in services/stac.py and tasks/timeline.py.

Note: ImagerySnapshot queries use raw SQL to avoid GeoAlchemy2 generating
PostGIS functions (AsEWKB, GeomFromEWKT) that are incompatible with SQLite
test databases.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Uuid, bindparam, select
from sqlalchemy import text as sa_text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.parcels import Parcel, TimelineRequest, TimelineRequestTask
from app.redact import redact
from app.services.admission import AdmissionRefused, ensure_admission

logger = logging.getLogger(__name__)


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

# Longer than the task's 35-minute hard time limit — an in-flight request
# that hasn't been touched for this long was lost (worker killed before
# acking, broker outage at dispatch, ...) and may be taken over.
_STALE_INFLIGHT = timedelta(minutes=45)


def _find_reusable_request(db: Session, parcel_id: uuid.UUID) -> TimelineRequest | None:
    return (
        db.execute(
            select(TimelineRequest)
            .where(TimelineRequest.parcel_id == parcel_id)
            .where(TimelineRequest.status.in_((*_INFLIGHT_STATUSES, "complete")))
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
) -> tuple[TimelineRequest, bool]:
    """Insert a queued request; on losing the one-in-flight-per-parcel race,
    return the winning request instead. Returns (request, created).

    Raises ``AdmissionRefused`` when the kill switch is on or the in-flight
    queue is at its cap — every new pipeline run passes through here.
    """
    ensure_admission(db, get_settings(), what="timeline_request")
    request = TimelineRequest(parcel_id=parcel_id, status="queued")
    db.add(request)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        racing = _find_reusable_request(db, parcel_id)
        if racing is not None and racing.status in _INFLIGHT_STATUSES:
            logger.info(
                "Lost request-creation race; reusing in-flight request",
                extra={"parcel_id": str(parcel_id), "request_id": str(racing.id)},
            )
            return racing, False
        raise
    db.refresh(request)
    logger.info(
        "Created new timeline request",
        extra={"parcel_id": str(parcel_id), "request_id": str(request.id)},
    )
    return request, True


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
    """
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
) -> None:
    """Update a task's status fields."""
    task.status = status
    if items_found is not None:
        task.items_found = items_found
    if status == "processing":
        task.started_at = datetime.now(tz=UTC)
    elif status in ("complete", "failed", "skipped"):
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
    if status in ("complete", "failed"):
        request.completed_at = datetime.now(tz=UTC)
    if error_message:
        request.error_message = redact(error_message)
    db.commit()


def maybe_refetch_for_backfill(
    db: Session,
    parcel: Parcel,
    existing_req: TimelineRequest,
) -> TimelineRequest | None:
    """Return a fresh TimelineRequest if the existing one is missing data
    we can now provide; otherwise None.

    Backfill triggers:
      * Census tract FIPS is now available but no census task ran, or the
        previous census task failed (e.g. a Census API outage).
      * The parcel's county now has a property adapter, but the previous
        run's property task was missing, skipped, or failed (e.g. a county
        portal outage).
      * No usgs_topo snapshots exist (source added after initial fetch).

    Caller is responsible for dispatching the Celery task on the returned
    request.
    """
    if existing_req.status != "complete":
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
            if not prop_task or prop_task.status in ("skipped", "failed"):
                needs_refetch = True
                logger.info(
                    "Property task missing/skipped/failed — refetch needed",
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

    if not needs_refetch:
        return None

    # A source that fails persistently (a retired Census vintage, a county
    # portal that stays down) keeps needs_refetch true forever, and every
    # page view would dispatch the full five-source pipeline again — dozens
    # of upstream calls and minutes of worker time to re-attempt one source.
    # The cooldown makes that visit-driven cost bounded per parcel. It does
    # not narrow the refetch to the missing source; that is deliberately
    # deferred (M3's per-source scope).
    cooldown = timedelta(hours=get_settings().backfill_cooldown_hours)
    last_attempt = db.execute(
        select(TimelineRequest.created_at)
        .where(TimelineRequest.parcel_id == parcel.id)
        .order_by(TimelineRequest.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if last_attempt is not None:
        age = datetime.now(UTC) - _as_utc(last_attempt)
        if age < cooldown:
            logger.info(
                "Backfill suppressed — last attempt is inside the cooldown",
                extra={
                    "parcel_id": str(parcel.id),
                    "age_hours": round(age.total_seconds() / 3600, 2),
                    "cooldown_hours": cooldown.total_seconds() / 3600,
                },
            )
            return None

    try:
        new_req, created = _create_queued_request(db, parcel.id)
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
        extra={"parcel_id": str(parcel.id), "request_id": str(new_req.id)},
    )
    return new_req


# ── Stranded-work janitor ─────────────────────────────────────────────────────

_TERMINAL_REQUEST_STATUSES = ("complete", "failed")
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


def reconcile_source_snapshots(
    db: Session,
    parcel_id: uuid.UUID,
    source: str,
    selected: Iterable[tuple[str, date]],
    *,
    scope: str = "year",
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

    Mosaics are safe because the comparison is against the full set of
    selected item ids: NAIP's several tiles for one year are all in
    ``selected``, so all of them are kept.

    Returns the number of rows deleted. Call after persisting the new
    selection, never before — an interruption then leaves duplicates,
    which is recoverable, rather than an empty timeline, which isn't.
    """
    bucket = SELECTION_SCOPES[scope]

    keep: set[str] = set()
    groups: set[tuple[int, ...]] = set()
    for stac_item_id, capture_date in selected:
        keep.add(stac_item_id)
        groups.add(bucket(capture_date))

    if not keep:
        return 0

    rows = db.execute(
        sa_text(
            "SELECT id, stac_item_id, capture_date FROM imagery_snapshots"
            " WHERE parcel_id = :parcel_id AND source = :source"
        ),
        {"parcel_id": str(parcel_id), "source": source},
    ).all()

    stale: list[object] = []
    for row in rows:
        if row.stac_item_id in keep:
            continue
        captured = _capture_date(row.capture_date)
        if captured is not None and bucket(captured) in groups:
            stale.append(row.id)

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

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
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select, text as sa_text
from sqlalchemy.orm import Session

from app.models.parcels import Parcel, TimelineRequest, TimelineRequestTask

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


def get_or_create_timeline_request(
    db: Session,
    parcel_id: uuid.UUID,
) -> tuple[TimelineRequest, bool]:
    """Return (request, is_new).

    If a 'complete' request already exists for this parcel, return it
    (second visit is instant — no re-fetch needed).
    Otherwise create a new queued request.
    """
    existing = (
        db.execute(
            select(TimelineRequest)
            .where(TimelineRequest.parcel_id == parcel_id)
            .where(TimelineRequest.status == "complete")
            .order_by(TimelineRequest.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if existing:
        logger.debug(
            "Returning existing complete timeline request",
            extra={"parcel_id": str(parcel_id), "request_id": str(existing.id)},
        )
        return existing, False

    request = TimelineRequest(parcel_id=parcel_id, status="queued")
    db.add(request)
    db.commit()
    db.refresh(request)
    logger.info(
        "Created new timeline request",
        extra={"parcel_id": str(parcel_id), "request_id": str(request.id)},
    )
    return request, True


def get_timeline_request(
    db: Session,
    request_id: uuid.UUID,
) -> TimelineRequest | None:
    """Fetch a timeline request by ID, including its per-source tasks."""
    return (
        db.execute(
            select(TimelineRequest).where(TimelineRequest.id == request_id)
        )
        .scalars()
        .first()
    )


def create_request_tasks(
    db: Session,
    timeline_request_id: uuid.UUID,
    sources: list[str],
) -> list[TimelineRequestTask]:
    """Create per-source task rows for a timeline request."""
    tasks = [
        TimelineRequestTask(
            timeline_request_id=timeline_request_id,
            source=source,
            status="queued",
        )
        for source in sources
    ]
    db.add_all(tasks)
    db.commit()
    for t in tasks:
        db.refresh(t)
    return tasks


def update_request_task(
    db: Session,
    task: TimelineRequestTask,
    status: str,
    items_found: int = 0,
    error_message: str | None = None,
) -> None:
    """Update a task's status fields."""
    task.status = status
    task.items_found = items_found
    if status == "processing":
        task.started_at = datetime.now(tz=timezone.utc)
    elif status in ("complete", "failed", "skipped"):
        task.completed_at = datetime.now(tz=timezone.utc)
    if error_message:
        task.error_message = error_message
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
        request.completed_at = datetime.now(tz=timezone.utc)
    if error_message:
        request.error_message = error_message
    db.commit()


def maybe_refetch_for_backfill(
    db: Session,
    parcel: Parcel,
    existing_req: TimelineRequest,
) -> TimelineRequest | None:
    """Return a fresh TimelineRequest if the existing one is missing data
    we can now provide; otherwise None.

    Two backfill triggers:
      * Census tract FIPS is now available but no census snapshots exist.
      * The parcel's county now has a property adapter, but the previous
        run's property task was missing or skipped.

    Caller is responsible for dispatching the Celery task on the returned
    request.
    """
    if existing_req.status != "complete":
        return None

    needs_refetch = False

    if parcel.census_tract_id:
        from app.services import demographics as demographics_service

        if not demographics_service.get_census_snapshots(db, parcel.id):
            needs_refetch = True
            logger.info(
                "Census data missing — refetch needed",
                extra={"parcel_id": str(parcel.id)},
            )

    if parcel.county:
        from app.services.county_adapters import get_adapter_for_county

        if get_adapter_for_county(parcel.county):
            prop_task = db.execute(
                select(TimelineRequestTask)
                .where(TimelineRequestTask.timeline_request_id == existing_req.id)
                .where(TimelineRequestTask.source == "property")
            ).scalars().first()
            if not prop_task or prop_task.status == "skipped":
                needs_refetch = True
                logger.info(
                    "Property task missing/skipped — refetch needed",
                    extra={"parcel_id": str(parcel.id), "county": parcel.county},
                )

    if not needs_refetch:
        return None

    new_req = TimelineRequest(parcel_id=parcel.id, status="queued")
    db.add(new_req)
    db.commit()
    db.refresh(new_req)
    logger.info(
        "Created new timeline request for backfill",
        extra={"parcel_id": str(parcel.id), "request_id": str(new_req.id)},
    )
    return new_req


# ── Imagery snapshot helpers ──────────────────────────────────────────────────


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
        return db.get_bind().dialect.name == "postgresql"  # type: ignore[no-any-return]
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


def _row_bbox(row: dict[str, object]) -> tuple[float, float, float, float] | None:
    """Return (w, s, e, n) from a row's bbox_w/s/e/n columns, or None if absent."""
    w = row.get("bbox_w")
    s = row.get("bbox_s")
    e = row.get("bbox_e")
    n = row.get("bbox_n")
    if w is None or s is None or e is None or n is None:
        return None
    return (float(w), float(s), float(e), float(n))

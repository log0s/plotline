"""Property events service layer.

Handles database operations for property_events — upserts from county
adapters and queries for the events API endpoint.

Uses raw SQL (like imagery.py and demographics.py) to keep things
SQLite-compatible for tests.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class PropertyEventRow:
    """Lightweight row representation, avoids ORM for test compatibility."""

    id: uuid.UUID
    parcel_id: uuid.UUID
    event_type: str
    event_date: date | None
    sale_price: int | None
    permit_type: str | None
    permit_description: str | None
    permit_valuation: int | None
    description: str | None
    source: str
    source_record_id: str | None
    raw_data: dict | None = None


def upsert_property_event(
    db: Session,
    *,
    parcel_id: uuid.UUID,
    event_type: str,
    event_date: date | None,
    sale_price: int | None,
    permit_type: str | None,
    permit_description: str | None,
    permit_valuation: int | None,
    description: str | None,
    source: str,
    source_record_id: str,
    raw_data: dict | None = None,
) -> bool:
    """Insert a property event, skipping on conflict (idempotent).

    Returns True if a row was inserted.
    """
    event_id = uuid.uuid4()

    sql = sa_text(
        """
        INSERT INTO property_events
            (id, parcel_id, event_type, event_date, sale_price,
             permit_type, permit_description, permit_valuation,
             description, source, source_record_id, raw_data)
        VALUES
            (:id, :parcel_id, :event_type, :event_date, :sale_price,
             :permit_type, :permit_description, :permit_valuation,
             :description, :source, :source_record_id, :raw_data)
        ON CONFLICT (parcel_id, source, source_record_id) DO NOTHING
        """
    )

    params = {
        "id": str(event_id),
        "parcel_id": str(parcel_id),
        "event_type": event_type,
        "event_date": str(event_date) if event_date else None,
        "sale_price": sale_price,
        "permit_type": permit_type,
        "permit_description": permit_description,
        "permit_valuation": permit_valuation,
        "description": description,
        "source": source,
        "source_record_id": source_record_id,
        "raw_data": json.dumps(raw_data) if raw_data else None,
    }

    result = db.execute(sql, params)
    db.commit()
    return result.rowcount > 0


def get_property_events(
    db: Session,
    parcel_id: uuid.UUID,
    *,
    event_types: list[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[PropertyEventRow]:
    """Return property events for a parcel, sorted by event_date ascending."""
    conditions = ["parcel_id = :parcel_id"]
    params: dict[str, Any] = {"parcel_id": str(parcel_id)}

    if event_types:
        placeholders = ", ".join(f":type_{i}" for i in range(len(event_types)))
        conditions.append(f"event_type IN ({placeholders})")
        for i, t in enumerate(event_types):
            params[f"type_{i}"] = t

    if start_date:
        conditions.append("event_date >= :start_date")
        params["start_date"] = str(start_date)

    if end_date:
        conditions.append("event_date <= :end_date")
        params["end_date"] = str(end_date)

    where_clause = " AND ".join(conditions)

    sql = sa_text(
        f"""
        SELECT id, parcel_id, event_type, event_date, sale_price,
               permit_type, permit_description, permit_valuation,
               description, source, source_record_id, raw_data
        FROM property_events
        WHERE {where_clause}
        ORDER BY event_date ASC NULLS LAST, created_at ASC
        """
    )

    rows = db.execute(sql, params).mappings().all()
    results = []
    for row in rows:
        raw = row["raw_data"]
        if isinstance(raw, str):
            raw = json.loads(raw)

        event_date_val = row["event_date"]
        if isinstance(event_date_val, str):
            try:
                event_date_val = date.fromisoformat(event_date_val)
            except ValueError:
                event_date_val = None

        results.append(
            PropertyEventRow(
                id=uuid.UUID(str(row["id"])),
                parcel_id=uuid.UUID(str(row["parcel_id"])),
                event_type=row["event_type"],
                event_date=event_date_val,
                sale_price=row["sale_price"],
                permit_type=row["permit_type"],
                permit_description=row["permit_description"],
                permit_valuation=row["permit_valuation"],
                description=row["description"],
                source=row["source"],
                source_record_id=row["source_record_id"],
                raw_data=raw,
            )
        )
    return results


def compute_price_summary(
    events: list[PropertyEventRow],
) -> dict[str, Any]:
    """Compute price history and appreciation from sale events.

    Returns a dict with:
        - price_history: list of {date, price} dicts
        - appreciation: human-readable appreciation string or None
        - total_sales: count of sales
        - total_permits: count of permits
        - total_events: total event count
    """
    sales = [
        e for e in events
        if e.event_type == "sale" and e.sale_price and e.sale_price > 0 and e.event_date
    ]
    sales.sort(key=lambda e: e.event_date)  # type: ignore[arg-type]

    price_history = [
        {"date": str(s.event_date), "price": s.sale_price}
        for s in sales
    ]

    appreciation: str | None = None
    if len(sales) >= 2:
        first_price = sales[0].sale_price
        last_price = sales[-1].sale_price
        if first_price and last_price and first_price > 0:
            pct = round(((last_price - first_price) / first_price) * 100)
            appreciation = f"{pct}% since first recorded sale"

    total_sales = sum(1 for e in events if e.event_type == "sale")
    total_permits = sum(1 for e in events if e.event_type.startswith("permit_"))

    return {
        "price_history": price_history,
        "appreciation": appreciation,
        "total_sales": total_sales,
        "total_permits": total_permits,
        "total_events": len(events),
    }

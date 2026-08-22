"""Global admission control for new parcels and pipeline dispatch.

Why queue depth, not a creation rate, and why the database, not Redis:
a flood looks to the single worker like a backlog it cannot drain —
every search behind it waits, legitimate or not. Depth measures exactly
that, self-corrects as the worker drains (or stops admitting when the
worker is down), and lives in the database the request row is written to,
so it keeps working when Redis — the broker, the cache and the limiter —
is the thing under strain. A fixed per-window counter in Redis would
either starve a legitimate burst or admit a backlog the worker cannot
clear, and would fail with the component it exists to protect.

Existing parcels are never affected: a dedup hit in ``get_or_create_parcel``
returns before the gate, and ``get_or_create_timeline_request`` reuses a
complete request before creating one.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.parcels import TimelineRequest

logger = logging.getLogger(__name__)

_INFLIGHT_STATUSES = ("queued", "processing")


class AdmissionRefused(Exception):
    """New work was refused; ``reason`` is ``kill_switch`` or ``queue_full``."""

    def __init__(self, reason: str, *, depth: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.depth = depth


def inflight_depth(db: Session) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(TimelineRequest)
            .where(TimelineRequest.status.in_(_INFLIGHT_STATUSES))
        ).scalar_one()
    )


def ensure_admission(db: Session, settings: Settings, *, what: str) -> None:
    """Raise ``AdmissionRefused`` when new work must not be started.

    Every refusal is logged with its reason so a flood is visible as a
    count of ``Admission refused`` lines, not as silence.
    """
    if not settings.accept_new_parcels:
        logger.warning("Admission refused", extra={"what": what, "reason": "kill_switch"})
        raise AdmissionRefused("kill_switch")

    depth = inflight_depth(db)
    if depth >= settings.max_inflight_timeline_requests:
        logger.warning(
            "Admission refused",
            extra={
                "what": what,
                "reason": "queue_full",
                "depth": depth,
                "cap": settings.max_inflight_timeline_requests,
            },
        )
        raise AdmissionRefused("queue_full", depth=depth)


REFUSED_DETAIL = (
    "Plotline is busy right now and new address searches are paused. "
    "Existing timelines are still available — please try again in a few minutes."
)

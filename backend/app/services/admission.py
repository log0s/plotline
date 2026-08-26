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
import time
from collections.abc import Callable

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


def effective_cap(settings: Settings, origin: str) -> int:
    """The in-flight cap this origin may fill.

    User traffic gets the whole cap; ``backfill`` and ``heal`` stop
    ``user_admission_reserve`` slots short of it. Before ``origin`` existed
    nothing at the gate could tell a first-time visitor's geocode from a
    six-year-old Landsat gap being retried, and the geocode is the one whose
    refusal a human sees as a 503 (INVESTIGATION §7.2, §7.4).

    The reserve is clamped at the cap, so a misconfigured reserve larger than
    the cap refuses all non-user work rather than admitting it unbounded.
    """
    cap = settings.max_inflight_timeline_requests
    if origin == "user":
        return cap
    return max(0, cap - min(settings.user_admission_reserve, cap))


def ensure_admission(db: Session, settings: Settings, *, what: str, origin: str = "user") -> None:
    """Raise ``AdmissionRefused`` when new work must not be started.

    Every refusal is logged with its reason so a flood is visible as a
    count of ``Admission refused`` lines, not as silence.
    """
    if not settings.accept_new_parcels:
        logger.warning(
            "Admission refused",
            extra={"what": what, "origin": origin, "reason": "kill_switch"},
        )
        raise AdmissionRefused("kill_switch")

    cap = effective_cap(settings, origin)
    depth = inflight_depth(db)
    if depth >= cap:
        logger.warning(
            "Admission refused",
            extra={
                "what": what,
                "origin": origin,
                "reason": "queue_full",
                "depth": depth,
                "cap": cap,
                "hard_cap": settings.max_inflight_timeline_requests,
            },
        )
        raise AdmissionRefused("queue_full", depth=depth)


WAIT_POLL_SECONDS = 5.0


def wait_for_admission_slot(
    db: Session,
    settings: Settings,
    *,
    deadline: float,
    origin: str = "user",
    poll_seconds: float = WAIT_POLL_SECONDS,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Block until the in-flight queue has room. ``True`` if a slot opened.

    For batch callers only. A refusal on the request path is an answer to a
    user and must stay immediate; a refusal inside a sweep is a rate limit
    the sweep should ride out, because the alternative — what
    ``revalidate_landsat.py`` did on 2026-08-25 — is a batch that abandons
    every parcel it has not reached yet.

    Depth comes from ``inflight_depth``, the same query ``ensure_admission``
    gates on, so the wait and the gate cannot disagree about what "full"
    means.

    ``deadline`` is a ``clock()`` value, not a duration. The kill switch is
    not waited out — it is off by operator intent, and no amount of waiting
    changes it.

    ``origin`` selects the cap being waited on, so a heal waits for the queue
    to fall below *its* ceiling rather than the user one — otherwise the wait
    would return, the gate would refuse, and the loop would spin.
    """
    while True:
        if not settings.accept_new_parcels:
            logger.warning(
                "Admission wait abandoned — kill switch is on",
                extra={"reason": "kill_switch"},
            )
            return False

        # Re-read, not re-use: the slot this waits for opens when the
        # *worker* commits, in another process. Seeing that from inside an
        # already-open transaction is a READ COMMITTED property, which is
        # Postgres's default and what production runs. Under REPEATABLE
        # READ this loop would never see the drain and would spend its
        # whole budget — start a fresh session per poll if that ever
        # changes.
        cap = effective_cap(settings, origin)
        if cap <= 0:
            # A reserve at or above the hard cap leaves this origin no slots
            # at all. Depth can never fall below zero, so waiting is a spin,
            # not a wait — refuse and let the caller report it.
            logger.warning(
                "Admission wait abandoned — this origin has no slots",
                extra={
                    "origin": origin,
                    "reason": "queue_full",
                    "hard_cap": settings.max_inflight_timeline_requests,
                    "reserve": settings.user_admission_reserve,
                },
            )
            return False

        depth = inflight_depth(db)
        if depth < cap:
            return True

        remaining = deadline - clock()
        if remaining <= 0:
            logger.warning(
                "Admission wait budget exhausted",
                extra={"reason": "queue_full", "depth": depth, "cap": cap},
            )
            return False

        logger.info(
            "Waiting for an admission slot",
            extra={
                "depth": depth,
                "cap": cap,
                "poll_seconds": poll_seconds,
                "wait_remaining_s": round(remaining, 1),
            },
        )
        sleeper(min(poll_seconds, remaining))


REFUSED_DETAIL = (
    "Plotline is busy right now and new address searches are paused. "
    "Existing timelines are still available — please try again in a few minutes."
)

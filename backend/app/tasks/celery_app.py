"""Celery application and worker lifecycle signals.

The app itself is small: broker/backend configuration plus three signal
handlers (structlog routing, prefork engine disposal, and the stranded-work
janitor). The only registered task is
``app.tasks.timeline.fetch_imagery_timeline``, pulled in via ``include``.
"""

from __future__ import annotations

import logging

from celery import Celery
from celery.signals import setup_logging, worker_process_init, worker_ready

from app.config import get_settings
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)

settings = get_settings()


def _redis_url_with_ssl(url: str) -> str:
    """Upstash/Fly Redis use rediss://; redis-py requires ssl_cert_reqs in the URL.

    CERT_REQUIRED, not CERT_NONE: this URL carries the task queue, and db.py's
    clients already verify certificates against the same server, so there is no
    reason for the broker to be the one connection that doesn't.
    """
    if url.startswith("rediss://") and "ssl_cert_reqs=" not in url:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}ssl_cert_reqs=CERT_REQUIRED"
    return url


_redis_url = _redis_url_with_ssl(settings.redis_url)

celery_app = Celery(
    "plotline",
    broker=_redis_url,
    backend=_redis_url,
    include=["app.tasks.timeline"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Nothing reads task results — imagery.py dispatches with .delay() and
    # polls the timeline_requests table instead — so storing them just fills
    # Redis for a day at a time.
    task_ignore_result=True,
    # Retry policy defaults
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)


def configure_worker_logging(**kwargs: object) -> None:
    """Route worker logs through structlog.

    Connecting to this signal disables Celery's own logging setup, so the
    worker emits the same JSON/console format as the API instead of Celery's
    default text formatter.
    """
    configure_logging(get_settings())


def dispose_inherited_engine(**kwargs: object) -> None:
    """Drop connections inherited across the prefork boundary.

    ``app.db.engine`` is created at import time in the worker parent and
    inherited by every forked child, so a connection the parent opened
    would be shared by several processes at once. Nothing in the parent
    uses it before the fork today — this makes that safe by construction
    rather than by accident. ``close=False`` abandons the file
    descriptors instead of closing them, which would disconnect the
    parent's copy too.
    """
    from app.db import engine

    engine.dispose(close=False)


def sweep_stranded_work(**kwargs: object) -> None:
    """Fail work a dead worker left in flight, once per worker boot.

    An OOM kill bypasses the soft-time-limit handler, so requests and task
    rows stay queued/processing forever — three such rows were live in
    production when the 2026-08 ops audit ran. Startup is the right hook:
    the fleet is small, a worker that was killed comes back, and running it
    per task would put a table scan in front of every job.

    Never fatal: a broker or database hiccup at boot must not stop the
    worker from accepting work.
    """
    from sqlalchemy.exc import SQLAlchemyError

    from app.db import SessionLocal
    from app.services import imagery as imagery_service

    try:
        with SessionLocal() as db:
            imagery_service.sweep_stranded_work(db)
    except SQLAlchemyError:
        logger.warning("Stranded-work sweep failed at worker startup", exc_info=True)


# Connected as calls rather than decorators: Celery's connect() is untyped.
setup_logging.connect(configure_worker_logging)
worker_process_init.connect(dispose_inherited_engine)
worker_ready.connect(sweep_stranded_work)

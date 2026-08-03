"""Celery application and task stubs.

Phase 1: The worker is wired up and running, but tasks are no-ops.
Phase 2 will add real tasks for fetching NAIP/Landsat imagery.
"""

from __future__ import annotations

import logging

from celery import Celery
from celery.signals import setup_logging

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


# Connected as a call rather than a decorator: Celery's connect() is untyped.
setup_logging.connect(configure_worker_logging)

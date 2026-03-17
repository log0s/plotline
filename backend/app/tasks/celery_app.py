"""Celery application and task stubs.

Phase 1: The worker is wired up and running, but tasks are no-ops.
Phase 2 will add real tasks for fetching NAIP/Landsat imagery.
"""

from __future__ import annotations

import logging

from celery import Celery

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

celery_app = Celery(
    "plotline",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.timeline"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Retry policy defaults
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)

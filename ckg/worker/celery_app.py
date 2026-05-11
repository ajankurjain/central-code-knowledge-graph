"""Celery app — imported by both the worker and the API (to enqueue tasks)."""

from __future__ import annotations

from celery import Celery

from ckg.config import get_settings

settings = get_settings()

celery_app = Celery(
    "ckg",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=10,
    task_track_started=True,
)

# Ensure task module is imported so workers know about @celery_app.task
celery_app.autodiscover_tasks(["ckg.worker"])

# Side-effect imports to register task functions on the workers / beat.
from ckg.worker import tasks  # noqa: E402,F401
from ckg.worker import scheduler  # noqa: E402,F401

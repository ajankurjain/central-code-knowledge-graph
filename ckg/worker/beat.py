"""Celery Beat schedule for periodic source + repo refresh.

The scheduler runs `scheduler.scan_sources` and `scheduler.scan_repos`
every minute. Those tasks decide which sources / repos are due based on
the per-row `sync_interval_seconds` / `poll_interval_seconds` columns,
and enqueue work.
"""

from __future__ import annotations

from celery.schedules import schedule

from ckg.worker.celery_app import celery_app

celery_app.conf.beat_schedule = {
    "scan-sources": {
        "task": "ckg.scan_sources_for_sync",
        "schedule": schedule(run_every=60.0),
    },
    "scan-repos": {
        "task": "ckg.scan_repos_for_poll",
        "schedule": schedule(run_every=60.0),
    },
    # Re-publishes orphaned `queued` rows and reaps zombie `running` rows.
    # Cheap (two indexed scans), idempotent — see the docstring on the task.
    "reconcile-stuck-ingests": {
        "task": "ckg.reconcile_stuck_ingests",
        "schedule": schedule(run_every=60.0),
    },
}
celery_app.conf.timezone = "UTC"

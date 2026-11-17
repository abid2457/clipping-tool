"""Persistent background scheduler for channel polling and autonomous pipeline execution."""

from __future__ import annotations

import logging
from typing import Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(daemon=True)
    return _scheduler


def _scheduled_watched_folder_sync() -> None:
    try:
        from app.agent.source_monitor import sync_watched_sources
        count = sync_watched_sources()
        if count > 0:
            logger.info("Watched folder sync: matched/registered %d new source(s)", count)
    except Exception as e:
        logger.debug("Watched folder sync error: %s", e)


def start_scheduler() -> None:
    """Initialize and start background autonomous scheduler."""
    sched = get_scheduler()
    if not sched.running:
        # Schedule watched folder scanner every 60 seconds
        sched.add_job(
            _scheduled_watched_folder_sync,
            trigger=IntervalTrigger(seconds=60),
            id="sync_watched_folder",
            replace_existing=True,
        )
        sched.start()
        logger.info("Autonomous Agent scheduler started.")


def stop_scheduler() -> None:
    """Cleanly shut down the background scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Autonomous Agent scheduler stopped.")

"""Startup recovery routines for reconciling interrupted jobs and orphaned resources."""

from __future__ import annotations

import logging
from app.database.session import db_session
from app.database.repository import Repository

logger = logging.getLogger(__name__)


def run_startup_recovery() -> int:
    """Detect and recover any jobs interrupted by a server restart or crash."""
    try:
        with db_session() as session:
            repo = Repository(session)
            recovered_count = repo.recover_orphaned_jobs()
            if recovered_count > 0:
                logger.warning(
                    f"Startup recovery: reconciled {recovered_count} interrupted job(s) from previous server run."
                )
            return recovered_count
    except Exception as e:
        logger.error(f"Startup recovery failed to reconcile database jobs: {e}")
        return 0

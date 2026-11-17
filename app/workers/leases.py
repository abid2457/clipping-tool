"""Durable job lease manager preventing concurrent worker collision."""

from __future__ import annotations

import os
import socket
import threading
import time
from typing import Optional
from app.database.session import db_session
from app.database.repository import Repository


def get_worker_identity() -> str:
    """Return a unique identifier for the current machine, process, and thread."""
    hostname = socket.gethostname()
    pid = os.getpid()
    tid = threading.get_ident()
    return f"{hostname}:{pid}:{tid}"


class JobLease:
    """Manages lease renewal heartbeats for a running job."""

    def __init__(self, job_id: str, worker_id: Optional[str] = None, lease_ttl_seconds: int = 120) -> None:
        self.job_id = job_id
        self.worker_id = worker_id or get_worker_identity()
        self.lease_ttl_seconds = lease_ttl_seconds
        self._stop_event = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Spawn background thread to continuously renew the lease."""
        self._stop_event.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"lease-heartbeat-{self.job_id}",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        interval = max(5, self.lease_ttl_seconds // 3)
        while not self._stop_event.wait(interval):
            try:
                with db_session() as session:
                    repo = Repository(session)
                    renewed = repo.renew_job_lease(self.job_id, self.worker_id, self.lease_ttl_seconds)
                    if not renewed:
                        # Lease was revoked or claimed by another worker
                        break
            except Exception:
                pass

    def stop(self) -> None:
        """Stop heartbeat thread on job completion or error."""
        self._stop_event.set()
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=2.0)

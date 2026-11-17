"""Persistent history of generated clips backed by SQLite with JSON fallback.

Maintains backward-compatibility with the React frontend and existing
``clips/history.json`` file while persisting all records into the relational database.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .paths import CLIPS_DIR
from app.database.session import db_session
from app.database.repository import Repository
from app.database.models import Clip, Job, SourceVideo

logger = logging.getLogger(__name__)

HISTORY_FILE = CLIPS_DIR / "history.json"
_LOCK = threading.Lock()

_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def clip_path(clip_id: str, index: int) -> Optional[Path]:
    """Resolve clips/<clip_id>/<index>.mp4, or None if the reference is invalid."""
    clean_id = (clip_id or "").split("_")[0]
    if not _ID_RE.match(clean_id or "") or not isinstance(index, int) or index < 0:
        return None
    path = (CLIPS_DIR / clean_id / f"{index}.mp4").resolve()
    # Defence in depth: the resolved path must stay under clips/.
    if CLIPS_DIR.resolve() not in path.parents:
        return None
    return path


def _load_json() -> list:
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        logger.warning("history.json was unreadable.")
        return []


def _save_json(entries: list) -> None:
    try:
        HISTORY_FILE.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        logger.warning("Could not write history.json: %s", exc)


def migrate_json_to_db() -> None:
    """One-time idempotent migration of legacy history.json to SQLite database."""
    entries = _load_json()
    if not entries:
        return

    try:
        with db_session() as session:
            repo = Repository(session)
            for entry in entries:
                clip_id = entry.get("clip_id")
                if not clip_id:
                    continue

                existing_job = repo.get_job(clip_id)
                if not existing_job:
                    # Create source video record
                    src_label = entry.get("source", "Unknown")
                    src_type = entry.get("source_type", "url")
                    src_video = repo.get_or_create_source_video(
                        source_uri=src_label,
                        source_type=src_type,
                    )

                    # Create job record
                    repo.create_job(
                        job_id=clip_id,
                        source_video_id=src_video.id,
                        stage="done",
                        status="completed",
                    )

                    # Create clip records
                    for c in entry.get("clips", []):
                        idx = c.get("index", 0)
                        db_clip_id = f"{clip_id}_{idx}"
                        start_sec = float(c.get("start", 0.0))
                        end_sec = float(c.get("end", 0.0))
                        repo.create_clip(
                            clip_id=db_clip_id,
                            job_id=clip_id,
                            clip_index=idx,
                            start_seconds=start_sec,
                            end_seconds=end_sec,
                            text=c.get("title", f"Clip {idx + 1}"),
                            output_path=c.get("url"),
                            metadata_json=json.dumps(c),
                        )
        logger.info("Successfully synced %d legacy history entries to SQLite database.", len(entries))
    except Exception as e:
        logger.debug("Database sync of history.json skipped: %s", e)


def add_entry(
    clip_id: str,
    source: str,
    settings: dict,
    clips: List[dict],
    source_type: str = "url",
) -> None:
    """Record one finished generation (a job and the clips it produced)."""
    entry = {
        "clip_id": clip_id,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "source_type": source_type,
        "settings": settings,
        "clips": clips,
    }

    # 1. Update JSON fallback
    with _LOCK:
        entries = _load_json()
        entries.append(entry)
        _save_json(entries)

    # 2. Persist to SQLite
    try:
        with db_session() as session:
            repo = Repository(session)
            src_video = repo.get_or_create_source_video(
                source_uri=source,
                source_type=source_type,
            )
            job = repo.get_job(clip_id)
            if not job:
                job = repo.create_job(
                    job_id=clip_id,
                    source_video_id=src_video.id,
                    stage="done",
                    status="completed",
                )
            else:
                repo.update_job_progress(clip_id, stage="done", progress=1.0, status="completed")

            for c in clips:
                idx = c.get("index", 0)
                db_clip_id = f"{clip_id}_{idx}"
                if not repo.get_clip(db_clip_id):
                    repo.create_clip(
                        clip_id=db_clip_id,
                        job_id=clip_id,
                        clip_index=idx,
                        start_seconds=float(c.get("start", 0.0)),
                        end_seconds=float(c.get("end", 0.0)),
                        text=c.get("title"),
                        output_path=c.get("url"),
                        metadata_json=json.dumps(c),
                    )
    except Exception as e:
        logger.warning("Could not persist history entry %s to database: %s", clip_id, e)


def list_entries() -> list:
    """All entries, newest first, each clip annotated with whether it still exists."""
    with _LOCK:
        entries = _load_json()

    for e in entries:
        for c in e.get("clips", []):
            p = clip_path(e.get("clip_id", ""), c.get("index", -1))
            c["exists"] = bool(p and p.exists())
    entries.sort(key=lambda e: e.get("created", ""), reverse=True)
    return entries


def remove_clip(clip_id: str, index: int) -> bool:
    """Delete one clip file and drop it from history. Returns True if a file went."""
    path = clip_path(clip_id, index)
    deleted = False
    if path and path.exists():
        try:
            path.unlink()
            deleted = True
        except OSError as exc:
            logger.warning("Could not delete clip %s/%s: %s", clip_id, index, exc)

    # Remove from SQLite
    try:
        with db_session() as session:
            db_clip_id = f"{clip_id}_{index}"
            clip = session.query(Clip).filter(Clip.id == db_clip_id).first()
            if clip:
                session.delete(clip)
    except Exception as e:
        logger.debug("Could not delete clip from database: %s", e)

    # Update JSON
    with _LOCK:
        entries = _load_json()
        for e in entries:
            if e.get("clip_id") == clip_id:
                e["clips"] = [c for c in e.get("clips", []) if c.get("index") != index]
        kept = []
        for e in entries:
            if e.get("clips"):
                kept.append(e)
            else:
                folder = CLIPS_DIR / e.get("clip_id", "")
                if _ID_RE.match(e.get("clip_id", "")) and folder.exists():
                    shutil.rmtree(folder, ignore_errors=True)
        _save_json(kept)

    return deleted


# Run migration on load
migrate_json_to_db()

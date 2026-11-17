"""Watched folder scanner and compliant media source acquisition manager."""

from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.database.session import db_session
from app.database.repository import Repository
from app.database.models import SourceVideo
from app.paths import WATCHED_DIR

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}


def compute_file_fingerprint(file_path: Path) -> str:
    """Compute lightweight fast fingerprint from file header and size."""
    try:
        size = file_path.stat().st_size
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            header = f.read(65536)  # 64 KB header
            hasher.update(header)
        hasher.update(str(size).encode("utf-8"))
        return hasher.hexdigest()[:32]
    except Exception as e:
        logger.debug("Could not fingerprint %s: %s", file_path, e)
        return ""


def scan_watched_directory(directory: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Scan local watched directory for video master files."""
    target_dir = directory or WATCHED_DIR
    if not target_dir.is_dir():
        return []

    found_files: List[Dict[str, Any]] = []
    for item in target_dir.iterdir():
        if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS:
            fp = compute_file_fingerprint(item)
            found_files.append({
                "path": str(item.resolve()),
                "filename": item.name,
                "stem": item.stem,
                "size_bytes": item.stat().st_size,
                "fingerprint": fp,
            })

    return found_files


def find_matching_source(
    youtube_title: str,
    candidates: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Match a YouTube video with a local file by comparing sanitized title words."""
    yt_tokens = set(re.findall(r'[a-zA-Z0-9]+', youtube_title.lower()))
    # Remove common filler words
    yt_tokens -= {"the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "of", "with"}
    if not yt_tokens:
        return None

    best_match = None
    best_overlap = 0

    for cand in candidates:
        cand_tokens = set(re.findall(r'[a-zA-Z0-9]+', cand["stem"].lower()))
        cand_tokens -= {"the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "of", "with"}
        overlap = len(yt_tokens.intersection(cand_tokens))
        if overlap > best_overlap and overlap >= 2:
            best_overlap = overlap
            best_match = cand

    return best_match


def sync_watched_sources() -> int:
    """Reconcile watched folder files with database source records.

    Returns count of newly registered or matched sources.
    """
    candidates = scan_watched_directory()
    if not candidates:
        return 0

    matched_count = 0
    with db_session() as session:
        repo = Repository(session)

        # 1. Check for any videos awaiting source
        awaiting_stmt = session.query(SourceVideo).filter(SourceVideo.ingest_status == "awaiting_source").all()
        for video in awaiting_stmt:
            match = find_matching_source(video.source_uri, candidates)
            if match:
                video.local_path = match["path"]
                video.fingerprint = match["fingerprint"]
                video.ingest_status = "ready"
                matched_count += 1
                logger.info("Matched awaiting YouTube video '%s' to local source: %s", video.source_uri, match["path"])

        # 2. Register any completely new watched files
        for cand in candidates:
            fp = cand["fingerprint"]
            existing = session.query(SourceVideo).filter(SourceVideo.fingerprint == fp).first()
            if not existing:
                repo.get_or_create_source_video(
                    source_uri=cand["filename"],
                    source_type="watched_folder",
                    local_path=cand["path"],
                    fingerprint=fp,
                )
                matched_count += 1

    return matched_count

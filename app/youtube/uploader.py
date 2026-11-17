"""Resumable YouTube Data API v3 uploader with Shorts/Video mode support."""

from __future__ import annotations

import logging
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import googleapiclient.errors
from googleapiclient.http import MediaFileUpload

from app.youtube.oauth import get_authenticated_service
from app.youtube.quota import can_afford_upload, record_quota_usage, UPLOAD_COST
from app.youtube.format_converter import ensure_shorts_vertical

logger = logging.getLogger(__name__)

# Retriable HTTP status codes
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]
MAX_RETRIES = 5


class YouTubeUploader:
    """Handles reliable, chunked, resumable uploads to YouTube."""

    def __init__(self, credential_id: int) -> None:
        self.credential_id = credential_id
        self.service = get_authenticated_service(credential_id)

    def upload_clip(
        self,
        video_path: Path | str,
        title: str,
        description: str,
        tags: Optional[List[str]] = None,
        privacy_status: str = "private",
        made_for_kids: bool = False,
        progress_callback: Optional[Any] = None,
        upload_mode: str = "shorts",
        category_id: str = "22",
    ) -> Dict[str, Any]:
        """Upload video file to YouTube via resumable session.

        Args:
            upload_mode: "shorts" adds #Shorts tag and enforces short-form rules.
                         "video" uploads as regular long-form content.
            category_id: YouTube category ID (default "22" = People & Blogs).
        """
        path = Path(video_path)
        if not path.is_file():
            raise FileNotFoundError(f"Video file not found at {path}")

        if not can_afford_upload():
            raise RuntimeError(
                "Daily YouTube API quota threshold reached (requires 1,600 units). "
                "Upload queued for tomorrow."
            )

        # Fail-closed safety: default to private if unknown
        if privacy_status not in ("private", "unlisted", "public"):
            privacy_status = "private"

        is_shorts = upload_mode.lower() == "shorts"
        clean_tags = list(tags or [])

        # Process file: guarantee vertical 9:16 aspect ratio for Shorts
        upload_path = path
        if is_shorts:
            try:
                upload_path = ensure_shorts_vertical(path)
            except Exception as e:
                logger.warning("Could not auto-transcode for Shorts: %s. Using original file.", e)
                upload_path = path

            # Shorts: ensure #Shorts tag is present
            if "Shorts" not in clean_tags and "#Shorts" not in clean_tags:
                clean_tags.insert(0, "Shorts")
        else:
            # Video: remove any Shorts tags
            clean_tags = [t for t in clean_tags if t.lower().strip("#") != "shorts"]

        # Title formatting: YouTube requires/recommends #Shorts in the title for immediate indexing
        max_title_len = 60 if is_shorts else 100
        clean_title = title[:max_title_len]
        if is_shorts:
            if "#Shorts" not in clean_title and "#shorts" not in clean_title:
                if len(clean_title) + 8 <= 100:
                    clean_title = f"{clean_title} #Shorts"
                else:
                    clean_title = f"{clean_title[:91].rstrip()} #Shorts"

        body = {
            "snippet": {
                "title": clean_title,
                "description": description[:5000],
                "tags": clean_tags[:30],
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": made_for_kids,
            },
        }

        # For Shorts, ensure #Shorts is in the description as well
        if is_shorts and "#Shorts" not in description and "#shorts" not in description:
            body["snippet"]["description"] = description[:4990] + "\n\n#Shorts"

        media = MediaFileUpload(
            str(upload_path),
            chunksize=1024 * 1024,  # 1 MB chunks
            resumable=True,
            mimetype="video/mp4",
        )

        request = self.service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        error = None
        retry_count = 0

        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    if progress_callback:
                        progress_callback(pct)
                    logger.debug("YouTube upload progress: %d%%", pct)
            except googleapiclient.errors.HttpError as e:
                if e.resp.status in RETRIABLE_STATUS_CODES:
                    error = f"A retriable HTTP error {e.resp.status} occurred: {e.content}"
                else:
                    raise
            except Exception as e:
                error = f"A network connection error occurred: {e}"

            if error:
                retry_count += 1
                if retry_count > MAX_RETRIES:
                    raise RuntimeError(f"Max upload retries exceeded: {error}")

                sleep_seconds = (2 ** retry_count) + random.random()
                logger.warning("%s. Retrying in %.1f seconds...", error, sleep_seconds)
                time.sleep(sleep_seconds)
                error = None

        record_quota_usage(UPLOAD_COST)
        video_id = response.get("id")
        logger.info(
            "Successfully uploaded clip to YouTube as %s! Video ID: %s",
            "Short" if is_shorts else "Video",
            video_id,
        )

        return {
            "youtube_video_id": video_id,
            "url": f"https://youtu.be/{video_id}",
            "privacy_status": privacy_status,
            "title": clean_title,
            "upload_mode": upload_mode,
        }

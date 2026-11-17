"""Background job model + SQLite durable state for the clip pipeline.

The full pipeline (download -> transcribe -> select -> render) can take minutes,
so running it inside the HTTP request would make the browser appear frozen. Each
request creates a :class:`Job`, runs the pipeline on a daemon thread with lease
heartbeating, and reports fine-grained progress that the frontend streams live
(see the SSE endpoint in ``main.py``).

In v2.0, jobs are persisted to SQLite so progress, status, and history survive
server restarts, crashes, and network disconnections.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from typing import Dict, List, Optional

from . import captions, downloader, history, music, pretranscribe, reframe, selector, transcriber, uploads
from .clipper import ClipOptions, generate_clip, target_size
from .models import (
    LANGUAGE_NAMES,
    ClipGenerationError,
    GenerateRequest,
    InvalidVideoURLError,
    TranscriptionError,
)
from .paths import CLIPS_DIR
from app.database.session import db_session
from app.database.repository import Repository
from app.workers.leases import JobLease

logger = logging.getLogger("ai_video_clipper.jobs")


# Overall-progress span (0..1) owned by each stage.
_STAGE_SPANS = {
    "queued": (0.0, 0.0),
    "downloading": (0.02, 0.25),
    "transcribing": (0.25, 0.70),
    "selecting": (0.70, 0.74),
    "rendering": (0.74, 0.99),
    "done": (1.0, 1.0),
    "error": (0.0, 0.0),
}

STAGE_LABELS = {
    "downloading": "Download",
    "transcribing": "Transcribe",
    "selecting": "Analyze",
    "rendering": "Render",
}

_BAD_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def download_filename(title: str, language: Optional[str], index: int) -> str:
    """Suggested download name for a clip, written in the caption's language."""
    lang = (language or "").strip().lower()
    native = LANGUAGE_NAMES.get(lang, lang.upper() if lang else "Clip")
    clean_title = _BAD_FILENAME_CHARS.sub(" ", (title or "").strip()).strip()
    clean_title = re.sub(r"\s+", " ", clean_title)
    if clean_title:
        name = f"{native} - {clean_title}"
    else:
        name = f"{native} - clip {index + 1}"
    return name[:120].strip() + ".mp4"


class Job:
    """A single pipeline run with thread-safe progress + persistent result state."""

    def __init__(self, req: Optional[GenerateRequest] = None, job_id: Optional[str] = None) -> None:
        self.id = job_id or uuid.uuid4().hex
        self.req = req
        self.status = "queued"  # queued | running | done | error | cancelled
        self.stage = "queued"
        self.stage_progress = 0.0  # 0..1 within current stage
        self.progress = 0.0  # 0..1 overall
        self.message = "Queued..."
        self.clips: List[dict] = []
        self.error: Optional[str] = None
        self.clip_id: Optional[str] = None
        self.cancelled = False
        self._lock = threading.Lock()
        self._rev = 0  # bumped on every change for SSE diffs

    def cancel(self) -> None:
        """Flag the run for cancellation; pipeline stops at next checkpoint."""
        with self._lock:
            if self.status in ("done", "error"):
                return
            self.cancelled = True
            self.status = "cancelled"
            self.stage = "cancelled"
            self.message = "Cancelled."
            self._rev += 1

        self._sync_db()

    def set_stage(self, stage: str, frac: float, message: str) -> None:
        """Move to/within a stage and recompute overall progress band."""
        frac = min(1.0, max(0.0, frac))
        lo, hi = _STAGE_SPANS.get(stage, (0.0, 0.0))
        with self._lock:
            self.status = "running"
            self.stage = stage
            self.stage_progress = frac
            self.progress = lo + frac * (hi - lo)
            self.message = message
            self._rev += 1

        self._sync_db()

    def add_clip(self, clip: dict) -> None:
        """Publish a finished clip so UI can show it before run ends."""
        with self._lock:
            self.clips.append(clip)
            self._rev += 1

    def finish(self, clips: List[dict]) -> None:
        with self._lock:
            self.status = "done"
            self.stage = "done"
            self.stage_progress = 1.0
            self.progress = 1.0
            self.message = f"Done - {len(clips)} clip(s) ready."
            self.clips = clips
            self._rev += 1

        self._sync_db()

    def fail(self, message: str) -> None:
        with self._lock:
            self.status = "error"
            self.stage = "error"
            self.error = message
            self.message = message
            self._rev += 1

        self._sync_db()

    def _sync_db(self) -> None:
        """Persist current status to SQLite asynchronously/safely."""
        try:
            with db_session() as session:
                repo = Repository(session)
                db_status = "completed" if self.status == "done" else ("failed" if self.status == "error" else self.status)
                repo.update_job_progress(
                    job_id=self.id,
                    stage=self.stage,
                    progress=self.progress,
                    status=db_status,
                    error_message=self.error,
                )
        except Exception:
            pass

    def snapshot(self) -> dict:
        """Return a JSON-serialisable view of current state."""
        with self._lock:
            return {
                "id": self.id,
                "status": self.status,
                "stage": self.stage,
                "stage_progress": round(self.stage_progress, 4),
                "progress": round(self.progress, 4),
                "message": self.message,
                "clips": list(self.clips),
                "error": self.error,
                "clip_id": self.clip_id,
                "rev": self._rev,
            }


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
_JOBS: Dict[str, Job] = {}
_JOBS_LOCK = threading.Lock()


def create_job(req: GenerateRequest) -> Job:
    job = Job(req)
    with _JOBS_LOCK:
        _JOBS[job.id] = job

    # Persist in SQLite
    try:
        with db_session() as session:
            repo = Repository(session)
            src_uri = req.video_url or req.upload_name or "local_source"
            src_video = repo.get_or_create_source_video(
                source_uri=src_uri,
                source_type="upload" if req.upload_id else "url",
            )
            repo.create_job(
                job_id=job.id,
                source_video_id=src_video.id,
                stage="queued",
                status="pending",
            )
    except Exception as e:
        logger.warning("[%s] Failed to record initial job in DB: %s", job.id, e)

    return job


def get_job(job_id: str) -> Optional[Job]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job:
            return job

    # Reconstruct from SQLite if missing from memory
    try:
        with db_session() as session:
            repo = Repository(session)
            db_job = repo.get_job(job_id)
            if db_job:
                reconstructed = Job(req=None, job_id=db_job.id)
                reconstructed.status = "done" if db_job.status == "completed" else db_job.status
                reconstructed.stage = db_job.stage
                reconstructed.progress = db_job.progress
                reconstructed.error = db_job.error_message
                reconstructed.clip_id = db_job.id

                # Load clips
                db_clips = repo.get_clips_for_job(job_id)
                for c in db_clips:
                    reconstructed.clips.append({
                        "index": c.clip_index,
                        "title": c.text or f"Clip {c.clip_index + 1}",
                        "start": c.start_seconds,
                        "end": c.end_seconds,
                        "url": c.output_path or f"/clips/{job_id}/{c.clip_index}.mp4",
                        "score": c.score,
                    })

                with _JOBS_LOCK:
                    _JOBS[job_id] = reconstructed
                return reconstructed
    except Exception as e:
        logger.debug("Failed restoring job %s from DB: %s", job_id, e)

    return None


def start_job(job: Job) -> None:
    """Run pipeline on background daemon thread with durable lease."""
    thread = threading.Thread(target=_run_pipeline, args=(job,), daemon=True)
    thread.start()


# --------------------------------------------------------------------------- #
# Pipeline runner
# --------------------------------------------------------------------------- #
def _run_pipeline(job: Job) -> None:
    """download -> transcribe -> select -> render, updating `job` and DB throughout."""
    req = job.req
    if not req:
        return

    logger.info("[%s] starting pipeline: %s", job.id, req.model_dump())
    lease = JobLease(job_id=job.id)
    lease.start()

    try:
        # 1) Get source video
        source_mp4 = None

        if req.download_id:
            try:
                source_mp4 = uploads.resolve_upload(req.download_id)
                job.set_stage("downloading", 1.0, "Video already downloaded. Preparing...")
            except InvalidVideoURLError:
                logger.warning("[%s] prefetched file %s missing; re-downloading.", job.id, req.download_id)

        if source_mp4 is None and req.upload_id:
            job.set_stage("downloading", 0.2, "Loading uploaded video...")
            source_mp4 = uploads.resolve_upload(req.upload_id)
            job.set_stage("downloading", 1.0, "Uploaded video ready. Preparing...")

        if source_mp4 is None:
            job.set_stage("downloading", 0.0, "Starting download...")

            def on_download(d: dict) -> None:
                status = d.get("status")
                if status == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate")
                    done = d.get("downloaded_bytes") or 0
                    if total:
                        pct = int(done * 100 / total)
                        job.set_stage("downloading", done / total, f"Downloading video... {pct}%")
                    else:
                        mb = done / 1_048_576
                        job.set_stage("downloading", 0.1, f"Downloading video... {mb:.1f} MB")
                elif status == "finished":
                    job.set_stage("downloading", 1.0, "Download complete. Preparing...")

            source_mp4 = downloader.download_video(req.video_url, progress_hook=on_download)

        # 2) Transcribe locally
        clip_id = uuid.uuid4().hex
        job.clip_id = clip_id
        source_id = source_mp4.stem
        device_label = {"auto": "Auto", "cuda": "GPU", "cpu": "CPU"}.get(
            req.device.value, "Auto"
        )

        def on_transcribe(frac: float, msg: str) -> None:
            job.set_stage("transcribing", frac, msg)

        if pretranscribe.cached(source_id, req.language) is not None:
            job.set_stage(
                "transcribing", 1.0, "Using transcript prepared while you set things up..."
            )
        else:
            running = pretranscribe.find_running(source_id)
            if running is not None:
                while True:
                    snap = running.snapshot()
                    if snap.get("status") != "running":
                        break
                    job.set_stage(
                        "transcribing", snap.get("progress", 0.0),
                        f"Transcribing audio with local Whisper ({device_label})... "
                        f"{int((snap.get('progress') or 0) * 100)}%",
                    )
                    time.sleep(0.4)
            else:
                job.set_stage(
                    "transcribing", 0.0,
                    f"Transcribing audio with local Whisper ({device_label})...",
                )

        transcript = pretranscribe.get_or_transcribe(
            source_mp4, source_id, req.device.value,
            progress=on_transcribe, language=req.language,
        )

        forced = (req.language or "").strip().lower()
        caption_language = (
            forced if forced and forced != "auto" else transcript.get("language")
        )

        # 3) Select clips
        job.set_stage("selecting", 0.3, "Analyzing transcript for the best moments...")
        windows = selector.select_clips(transcript, req.num_clips, req.clip_length)
        if not windows:
            raise ClipGenerationError(
                "Could not find any suitable clip windows in this video. "
                "Try a longer video or fewer clips."
            )
        job.set_stage("selecting", 1.0, f"Found {len(windows)} clip(s) to render.")

        # 4) Per clip: build ASS captions + render with ffmpeg
        words = transcript.get("words") or []
        caption_overrides = (
            req.caption_overrides.model_dump() if req.caption_overrides else None
        )
        cinematic = req.cinematic.model_dump() if req.cinematic else None
        music_path = None
        if req.music_track:
            try:
                music_path = music.resolve_track(req.music_track)
            except InvalidVideoURLError:
                logger.warning("[%s] music track %r not found; skipping.", job.id, req.music_track)
        width, height = target_size(req.aspect_ratio, req.fit_mode)
        clip_dir = CLIPS_DIR / clip_id
        clip_dir.mkdir(parents=True, exist_ok=True)

        results: List[dict] = []
        total = len(windows)
        for index, win in enumerate(windows):
            if job.cancelled:
                logger.info("[%s] cancelled before clip %d", job.id, index)
                return
            start, end = float(win["start"]), float(win["end"])
            job.set_stage(
                "rendering",
                index / total,
                f"Rendering clip {index + 1} of {total}...",
            )

            clip_words = [w for w in words if w["end"] > start and w["start"] < end]
            ass_path = clip_dir / f"{index}.ass"
            captions.build_ass(
                words=clip_words,
                style_preset=req.caption_style,
                video_w=width,
                video_h=height,
                out_path=ass_path,
                clip_start=start,
                overrides=caption_overrides,
                fit_mode=req.fit_mode.value,
            )

            opts = ClipOptions(
                aspect_ratio=req.aspect_ratio,
                fit_mode=req.fit_mode,
                square_corners=req.square_corners.value,
                ass_path=ass_path,
                clip_id=clip_id,
                index=index,
                bar_text=req.bar_text,
                bar_text_color=req.bar_text_color or "#FFFFFF",
                bar_text_anim=req.bar_text_anim or "none",
                cinematic=cinematic,
                music_path=music_path,
                music_volume=req.music_volume if req.music_volume is not None else 35.0,
                music_duck=req.music_duck if req.music_duck is not None else 70.0,
                music_start=req.music_start if req.music_start is not None else 0.0,
                signature=req.signature.model_dump() if req.signature else None,
            )
            generate_clip(source_mp4, start, end, opts)

            reframe.save_recipe(
                clip_id, index, source_mp4=source_mp4, start=start, end=end,
                opts_kwargs={
                    "aspect_ratio": opts.aspect_ratio,
                    "fit_mode": opts.fit_mode,
                    "square_corners": opts.square_corners,
                    "ass_path": opts.ass_path,
                    "bar_text": opts.bar_text,
                    "bar_text_color": opts.bar_text_color,
                    "bar_text_anim": opts.bar_text_anim,
                    "cinematic": opts.cinematic,
                    "music_path": opts.music_path,
                    "music_volume": opts.music_volume,
                    "music_duck": opts.music_duck,
                    "music_start": opts.music_start,
                    "signature": opts.signature,
                },
            )

            title = win.get("title") or f"Clip {index + 1}"
            clip = {
                "index": index,
                "title": title,
                "start": round(start, 2),
                "end": round(end, 2),
                "url": f"/clips/{clip_id}/{index}.mp4",
                "language": caption_language,
                "filename": download_filename(title, caption_language, index),
            }
            results.append(clip)
            job.add_clip(clip)

        job.finish(results)
        logger.info("[%s] pipeline complete: %d clips", job.id, len(results))

        if req.upload_id:
            source_label = req.upload_name or "Uploaded file"
            source_type = "upload"
        else:
            source_label = req.video_url or "Unknown source"
            source_type = "url"

        try:
            history.add_entry(
                clip_id=clip_id,
                source=source_label,
                source_type=source_type,
                settings={
                    "aspect_ratio": req.aspect_ratio.value,
                    "fit_mode": req.fit_mode.value,
                    "caption_style": req.caption_style,
                    "num_clips": req.num_clips,
                    "language": caption_language,
                },
                clips=results,
            )
        except Exception:
            logger.warning("[%s] could not write history entry", job.id, exc_info=True)

    except InvalidVideoURLError as exc:
        logger.warning("[%s] download error: %s", job.id, exc)
        job.fail(str(exc))
    except TranscriptionError as exc:
        logger.warning("[%s] transcription error: %s", job.id, exc)
        job.fail(str(exc))
    except ClipGenerationError as exc:
        logger.warning("[%s] render error: %s", job.id, exc)
        job.fail(str(exc))
    except Exception as exc:
        logger.exception("[%s] unexpected pipeline failure", job.id)
        job.fail(f"Unexpected error: {exc}")
    finally:
        lease.stop()

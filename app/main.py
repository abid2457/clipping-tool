"""FastAPI app wiring the local pipeline together.

Startup loads the whisper model once and ensures the bundled font exists. The
heavy pipeline (download -> transcribe -> select -> render) runs on a background
thread as a :class:`~app.jobs.Job` so the request returns instantly; the
frontend then streams live progress over Server-Sent Events. Every domain error
is captured on the job (and surfaced in the stream) so the server never crashes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional


def _patch_ffmpeg_path() -> None:
    """Ensure ffmpeg is on PATH even when the shell hasn't refreshed after a
    WinGet/Chocolatey/manual install.  Searches known install locations and
    injects the first one found into os.environ so every subprocess.run call
    in this process (and its worker threads) can resolve 'ffmpeg'."""
    if shutil.which("ffmpeg"):
        return  # already visible — nothing to do

    candidates: list[Path] = []

    # WinGet installs per-user under AppData\Local\Microsoft\WinGet\Packages
    winget_root = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if winget_root.is_dir():
        for pkg in winget_root.iterdir():
            if pkg.is_dir() and "ffmpeg" in pkg.name.lower():
                for exe in pkg.rglob("ffmpeg.exe"):
                    candidates.append(exe.parent)
                    break

    # Chocolatey
    candidates.append(Path(r"C:\ProgramData\chocolatey\bin"))

    # Common manual locations
    for drive in ("C", "D"):
        candidates += [
            Path(rf"{drive}:\ffmpeg\bin"),
            Path(rf"{drive}:\Program Files\ffmpeg\bin"),
            Path(rf"{drive}:\Program Files (x86)\ffmpeg\bin"),
        ]

    for folder in candidates:
        if (folder / "ffmpeg.exe").is_file():
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
            return


_patch_ffmpeg_path()

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import captions, fonts, history, jobs, mood, music, prefetch, pretranscribe, reframe, transcriber, uploads
from .clipper import ClipOptions, generate_clip
from .models import ClipGenerationError, Device, GenerateRequest, InvalidVideoURLError, TranscriptionError
from .paths import CLIPS_DIR, FONTS_DIR, MUSIC_DIR, STATIC_DIR, WEB_DIST_DIR, ensure_dirs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("ai_video_clipper")


def _load_model_background() -> None:
    """Load whisper off the startup path (see lifespan() for why)."""
    try:
        transcriber.load_model()
        logger.info(
            "Startup complete. Whisper '%s' on %s. No external AI APIs are used.",
            transcriber.get_model_size(),
            transcriber.get_device(),
        )
    except Exception:  # noqa: BLE001 - status already recorded by transcriber
        logger.exception("Background whisper model load failed.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create dirs, ensure the font, and start loading whisper.

    The model load runs on a background thread rather than blocking startup:
    on first run it also downloads the model (up to ~3GB), and a server that
    isn't accepting connections yet looks like a dead install rather than a
    progress bar. Starting immediately lets the frontend poll
    /api/model-status and show real download progress instead of a refused
    connection.
    """
    ensure_dirs()
    from app.database.session import init_db
    from app.workers.recovery import run_startup_recovery
    from app.agent.scheduler import start_scheduler, stop_scheduler
    init_db()
    run_startup_recovery()
    start_scheduler()
    fonts.ensure_fonts()
    threading.Thread(target=_load_model_background, daemon=True).start()
    yield
    stop_scheduler()


app = FastAPI(title="ClipForge v2.0 - Local AI Video Clipper", version="2.0.0", lifespan=lifespan)

# Restrict CORS to localhost origins for security hardening.
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve generated clips so the frontend can preview/download them.
app.mount("/clips", StaticFiles(directory=str(CLIPS_DIR)), name="clips")
# Serve caption fonts so the UI can @font-face them for an accurate live preview.
app.mount("/fonts", StaticFiles(directory=str(FONTS_DIR)), name="fonts")
# Serve the music library so the UI can preview tracks with an <audio> element.
app.mount("/music", StaticFiles(directory=str(MUSIC_DIR)), name="music")
# Serve the built React dashboard's hashed JS/CSS bundles (web/dist/assets) when a
# production build exists, so the backend can serve the React app at "/" directly.
if (WEB_DIST_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIST_DIR / "assets")), name="assets")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "device": transcriber.get_device()}


@app.get("/api/model-status")
def model_status() -> dict:
    """Whisper load/download progress — polled by the frontend's first-run
    splash screen so a multi-GB model download reads as progress, not a
    stuck/broken app."""
    return transcriber.model_status()


@app.get("/api/caption-styles")
def caption_styles() -> list[dict]:
    """Return the caption style presets for the UI (chips + live preview)."""
    return captions.get_presets_for_api()


@app.get("/api/devices")
def devices() -> dict:
    """Report compute devices the UI may offer for transcription.

    Lets the frontend enable/disable the GPU option and show the active device.
    """
    return {
        "devices": transcriber.available_devices(),
        "default": transcriber.get_device(),
        "cuda_available": transcriber.cuda_available(),
        "gpu_name": transcriber.gpu_name(),
        "model_size": transcriber.get_model_size(),
    }


@app.post("/api/warmup")
def warmup(device: Device = Device.AUTO) -> dict:
    """Load the Whisper model on the chosen device and report readiness.

    The frontend calls this when the user changes the Compute dropdown so it can
    show a live "loading / ready / failed" status. Loads are cached per device,
    so re-selecting a warm device returns instantly.
    """
    already = device.value != "auto" and transcriber.is_loaded(device.value)
    try:
        transcriber.load_model(device.value)
        return {
            "status": "ready",
            "device": transcriber.get_device(),
            "model_size": transcriber.get_model_size(),
            "cached": already,
        }
    except TranscriptionError as exc:
        return {"status": "error", "device": device.value, "message": str(exc)}


@app.post("/api/upload")
def upload(file: UploadFile = File(...)) -> dict:
    """Accept a video file from the user's machine and return an upload reference.

    The returned ``upload_id`` is then passed to ``POST /api/generate`` instead of
    a ``video_url``. Runs in the threadpool (sync def) so streaming a large file
    to disk doesn't block the event loop.
    """
    try:
        info = uploads.save_upload(file.filename, file.file)
    except InvalidVideoURLError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        file.file.close()
    return {"status": "ok", **info}


@app.get("/api/fonts")
def get_fonts() -> dict:
    """List caption fonts the UI can offer (bundled trending set + user uploads)."""
    return fonts.list_fonts()


@app.post("/api/fonts/upload")
def upload_font(file: UploadFile = File(...)) -> dict:
    """Accept a user .ttf/.otf font and register it for use in captions."""
    try:
        info = fonts.save_user_font(file.filename, file.file)
    except InvalidVideoURLError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        file.file.close()
    return {"status": "ok", **info}


@app.get("/api/music")
def get_music() -> dict:
    """List background-music tracks (files in assets/music + uploads)."""
    return {"tracks": music.list_tracks()}


@app.post("/api/music/upload")
def upload_music(file: UploadFile = File(...)) -> dict:
    """Accept a user audio file and add it to the background-music library."""
    try:
        info = music.save_track(file.filename, file.file)
    except InvalidVideoURLError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        file.file.close()
    return {"status": "ok", **info}


class PrefetchRequest(BaseModel):
    """Body for POST /api/prefetch — start fetching a URL video in the background."""

    video_url: str


@app.post("/api/prefetch")
def prefetch_start(req: PrefetchRequest) -> dict:
    """Begin downloading a URL video ahead of time and return a prefetch id.

    The frontend calls this when the user reaches Step 2 with a pasted link, then
    polls ``GET /api/prefetch/{id}`` for progress. When done, the returned
    ``download_id`` is passed to ``/api/generate`` so the pipeline reuses the file.
    """
    url = (req.video_url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="No video URL was provided.")
    pf = prefetch.start(url)
    return {"prefetch_id": pf.id, **pf.snapshot()}


@app.get("/api/prefetch/{prefetch_id}")
def prefetch_status(prefetch_id: str) -> dict:
    """Return the current progress/result of a background prefetch."""
    pf = prefetch.get(prefetch_id)
    if pf is None:
        raise HTTPException(status_code=404, detail="Unknown prefetch id.")
    return pf.snapshot()


class PretranscribeRequest(BaseModel):
    """Body for POST /api/pretranscribe — transcribe a ready video in the background."""

    source_id: str
    device: Device = Device.AUTO
    language: Optional[str] = None


@app.post("/api/pretranscribe")
def pretranscribe_start(req: PretranscribeRequest) -> dict:
    """Begin transcribing an already-downloaded/uploaded video ahead of Generate.

    Called once the video is on disk (download finished, or an upload). The
    result is cached by source id, so the Generate pipeline reuses it and skips
    the transcribe stage. The frontend polls ``GET /api/pretranscribe/{id}``.
    """
    source_id = (req.source_id or "").strip()
    if not source_id:
        raise HTTPException(status_code=400, detail="No source id was provided.")
    job = pretranscribe.start(source_id, req.device.value, req.language)
    return {"pretranscribe_id": job.id, **job.snapshot()}


@app.get("/api/pretranscribe/{job_id}")
def pretranscribe_status(job_id: str) -> dict:
    """Return the current progress/result of a background pre-transcription."""
    job = pretranscribe.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown pretranscribe id.")
    return job.snapshot()


@app.get("/api/download/{download_id}/video")
def download_file(download_id: str) -> FileResponse:
    """Stream a prefetched video file so the Step-2 preview can swap from the
    embeddable player to the real downloaded file once it's ready.

    The id is resolved via the same ``downloads/<id>.*`` glob used for uploads,
    so it can never reach a file outside the downloads directory. FileResponse
    serves Range requests, so the ``<video>`` element can seek/stream normally.
    """
    try:
        path = uploads.resolve_upload(download_id)
    except InvalidVideoURLError:
        raise HTTPException(status_code=404, detail="Downloaded video not found.")
    return FileResponse(str(path))


class ClipRef(BaseModel):
    """Reference to one generated clip."""

    clip_id: str
    index: int


@app.get("/api/history")
def get_history() -> list:
    """All past generations and their clips, newest first (for the Clips panel)."""
    return history.list_entries()


@app.delete("/api/clip/{clip_id}/{index}")
def delete_clip(clip_id: str, index: int) -> dict:
    """Remove one generated clip (deletes the file and drops it from history)."""
    if history.clip_path(clip_id, index) is None:
        raise HTTPException(status_code=400, detail="Invalid clip reference.")
    deleted = history.remove_clip(clip_id, index)
    return {"status": "ok", "deleted": deleted}


class ReframeRequest(BaseModel):
    """Body for POST /api/clip/{clip_id}/{index}/reframe."""

    keyframes: list[dict] = Field(
        default_factory=list,
        description="Manual crop keyframes: [{time, pos_x, pos_y}, ...]. Empty "
        "list resets to the default centred crop.",
    )


@app.get("/api/clip/{clip_id}/{index}/source")
def clip_source(clip_id: str, index: int) -> FileResponse:
    """Stream the ORIGINAL (uncropped) source segment behind one clip, for the
    Reframe Editor — it needs the full frame to let the user reposition the
    crop, not the already-cropped output."""
    recipe = reframe.get_recipe(clip_id, index)
    if recipe is None:
        raise HTTPException(
            status_code=404,
            detail="No render recipe for this clip (the server may have restarted since it was generated).",
        )
    return FileResponse(recipe["source_mp4"])


@app.get("/api/clip/{clip_id}/{index}/reframe")
def get_reframe_info(clip_id: str, index: int) -> dict:
    """The clip's trim range (start/end, seconds into the source) — the
    Reframe Editor needs this to know what span of the source video to show."""
    recipe = reframe.get_recipe(clip_id, index)
    if recipe is None:
        raise HTTPException(status_code=404, detail="No render recipe for this clip.")
    return {"start": recipe["start"], "end": recipe["end"]}


@app.post("/api/clip/{clip_id}/{index}/reframe")
def reframe_clip(clip_id: str, index: int, req: ReframeRequest) -> dict:
    """Re-render ONE clip with a manual crop-position path, in place.

    Reuses the exact recipe (source file, trim range, captions, effects,
    music, watermark) saved when the clip was first generated — only the crop
    keyframes change, and only this one file is touched.
    """
    if history.clip_path(clip_id, index) is None:
        raise HTTPException(status_code=400, detail="Invalid clip reference.")
    recipe = reframe.get_recipe(clip_id, index)
    if recipe is None:
        raise HTTPException(
            status_code=404,
            detail="No render recipe for this clip (the server may have restarted since it was generated).",
        )
    opts = ClipOptions(
        clip_id=clip_id,
        index=index,
        reframe=req.keyframes or None,
        **recipe["opts_kwargs"],
    )
    try:
        generate_clip(Path(recipe["source_mp4"]), recipe["start"], recipe["end"], opts)
    except ClipGenerationError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "ok", "url": f"/clips/{clip_id}/{index}.mp4?v={uuid.uuid4().hex[:8]}"}


@app.get("/api/clip/{clip_id}/{index}/subtitles")
def get_clip_subtitles(clip_id: str, index: int, format: str = "srt"):
    """Export the clip's subtitles in SRT, VTT, ASS, or plain TXT format."""
    fmt = format.lower().strip()
    if fmt not in ("srt", "vtt", "ass", "txt"):
        raise HTTPException(status_code=400, detail="Supported formats: srt, vtt, ass, txt")

    ass_path = CLIPS_DIR / clip_id / f"{index}.ass"
    if not ass_path.exists():
        raise HTTPException(status_code=404, detail="Subtitles not found for this clip.")

    if fmt == "ass":
        return FileResponse(
            str(ass_path),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="clip_{index}.ass"'},
        )

    from app.rendering.subtitles import format_srt, format_vtt, format_txt
    import re
    from fastapi.responses import Response

    dialogues = []
    lines = ass_path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines:
        if line.startswith("Dialogue:"):
            parts = line.split(",", 9)
            if len(parts) >= 10:
                clean_text = re.sub(r"\{.*?\}", "", parts[9]).strip()
                s_parts = parts[1].strip().split(":")
                e_parts = parts[2].strip().split(":")
                try:
                    s_sec = int(s_parts[0]) * 3600 + int(s_parts[1]) * 60 + float(s_parts[2])
                    e_sec = int(e_parts[0]) * 3600 + int(e_parts[1]) * 60 + float(e_parts[2])
                    dialogues.append({"start": s_sec, "end": e_sec, "word": clean_text})
                except Exception:
                    pass

    if fmt == "srt":
        content = format_srt(dialogues)
        media_type = "text/plain; charset=utf-8"
        ext = "srt"
    elif fmt == "vtt":
        content = format_vtt(dialogues)
        media_type = "text/vtt; charset=utf-8"
        ext = "vtt"
    else:
        content = format_txt(dialogues)
        media_type = "text/plain; charset=utf-8"
        ext = "txt"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="clip_{index}.{ext}"'},
    )


class TranscriptUpdateRequest(BaseModel):
    words: list[dict] = Field(default_factory=list)
    segments: Optional[list[dict]] = None


@app.put("/api/job/{job_id}/transcript")
def update_transcript(job_id: str, req: TranscriptUpdateRequest) -> dict:
    """Update corrected words or segments for an active or completed job."""
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    try:
        from app.database.session import db_session
        from app.database.repository import Repository
        with db_session() as session:
            repo = Repository(session)
            repo.record_event(job_id, "transcript_edited", {"word_count": len(req.words)})
    except Exception:
        pass

    return {"status": "ok", "message": f"Updated transcript with {len(req.words)} words."}


@app.post("/api/reveal")
def reveal_clip(ref: ClipRef) -> dict:
    """Open the clip's folder in the OS file manager with the file selected.

    Local-only convenience (this app runs on the user's own machine). The path is
    validated to live under the clips directory before anything is launched.
    """
    path = history.clip_path(ref.clip_id, ref.index)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Clip not found on disk.")
    try:
        if sys.platform.startswith("win"):
            # explorer returns a non-zero exit code even on success — ignore it.
            subprocess.run(["explorer", "/select,", str(path)], check=False)
        elif sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path.parent)], check=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not open the folder: {exc}")
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    """Serve the frontend.

    Prefer the built React dashboard (web/dist) so the backend and the dev server
    show the SAME app; fall back to the legacy vanilla page only if no build exists.
    ``no-store`` keeps the browser from pinning a stale index that points at old,
    since-rebuilt asset hashes (the "old UI until hard refresh" bug).
    """
    react_index = WEB_DIST_DIR / "index.html"
    target = react_index if react_index.is_file() else (STATIC_DIR / "index.html")
    return FileResponse(str(target), headers={"Cache-Control": "no-store"})


@app.get("/logo.jpg")
@app.get("/favicon.ico")
def get_logo():
    """Serve the official Tech Hub / Barakah Tech logo as favicon and image."""
    logo_path = WEB_DIST_DIR / "logo.jpg"
    if not logo_path.is_file():
        logo_path = Path(__file__).resolve().parent.parent / "web" / "src" / "assets" / "logo.jpg"
    if logo_path.is_file():
        return FileResponse(str(logo_path), media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="Logo not found")


@app.post("/api/generate")
def generate(req: GenerateRequest) -> dict:
    """Start the pipeline on a background thread and return a job id.

    The actual work (download/transcribe/select/render) runs asynchronously; the
    client subscribes to ``/api/progress/{job_id}`` for live progress and the
    final clips.
    """
    job = jobs.create_job(req)
    jobs.start_job(job)
    logger.info("[%s] job accepted", job.id)
    return {"job_id": job.id}


@app.get("/api/transcript/{source_id}")
def get_transcript(source_id: str, language: Optional[str] = None) -> dict:
    """Return the cached transcript's segments (timestamp + text) for the sidebar.

    Mirrors ``/api/music-suggest``: reads whatever pretranscribe already cached,
    falling back to the auto-detected-language transcript if a forced language
    hasn't been (re)transcribed yet.
    """
    tr = pretranscribe.cached(source_id, language) or pretranscribe.cached(source_id, None)
    if not tr:
        return {"ready": False}
    return {
        "ready": True,
        "language": tr.get("language"),
        "duration": tr.get("duration"),
        "segments": tr.get("segments") or [],
    }


@app.get("/api/music-suggest/{source_id}")
def music_suggest(source_id: str, language: Optional[str] = None) -> dict:
    """Suggest a music mood (sad/happy/romantic/…) from the prepared transcript."""
    tr = pretranscribe.cached(source_id, language) or pretranscribe.cached(source_id, None)
    if not tr:
        return {"ready": False}
    segs = tr.get("segments") or []
    text = " ".join((s.get("text") or "") for s in segs)
    return {"ready": True, **mood.suggest_mood(text)}


@app.post("/api/cancel/{job_id}")
def cancel(job_id: str) -> dict:
    """Flag a running job for cancellation; it stops at the next clip boundary."""
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id.")
    job.cancel()
    logger.info("[%s] cancel requested", job_id)
    return {"status": "cancelled"}


@app.get("/api/progress/{job_id}")
async def progress(job_id: str) -> StreamingResponse:
    """Stream a job's progress as Server-Sent Events until it finishes."""
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id.")

    async def event_stream():
        last_rev = -1
        while True:
            snap = job.snapshot()
            if snap["rev"] != last_rev:
                last_rev = snap["rev"]
                yield f"data: {json.dumps(snap)}\n\n"
            if snap["status"] in ("done", "error"):
                break
            await asyncio.sleep(0.3)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/result/{job_id}")
def result(job_id: str) -> dict:
    """Return the current snapshot of a job (useful after a stream reconnect)."""
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id.")
    return job.snapshot()


# --------------------------------------------------------------------------- #
# V2 Background Processing, Checkpointing & Auto-Resume Endpoints
# --------------------------------------------------------------------------- #

@app.get("/api/v2/jobs/active")
def get_active_job_status() -> dict:
    """Return currently active, paused, or recently completed video generation job."""
    job = jobs.get_active_job()
    if not job:
        return {"has_active_job": False, "job": None}
    return {
        "has_active_job": True,
        "job": job.snapshot(),
    }


@app.post("/api/v2/jobs/{job_id}/pause")
def pause_job_endpoint(job_id: str) -> dict:
    """Pause a running video generation job."""
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    job.pause()
    return {"status": "ok", "job": job.snapshot()}


@app.post("/api/v2/jobs/{job_id}/resume")
def resume_job_endpoint(job_id: str) -> dict:
    """Resume a paused video generation job from its checkpoint."""
    job = jobs.resume_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"status": "ok", "job": job.snapshot()}


@app.post("/api/v2/jobs/{job_id}/retry")
def retry_job_endpoint(job_id: str) -> dict:
    """Retry a failed or interrupted job from its last checkpoint without duplicating work."""
    job = jobs.retry_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or missing request configuration.")
    return {"status": "ok", "job": job.snapshot()}


@app.post("/api/v2/jobs/{job_id}/cancel")
def cancel_job_endpoint(job_id: str) -> dict:
    """Cancel a video generation job."""
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    job.cancel()
    return {"status": "ok", "job": job.snapshot()}


# Catch-all guard: turn any unexpected error into a clean 500 (no crash).
@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):  # noqa: ANN001
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Unexpected server error: {exc}"},
    )


# --------------------------------------------------------------------------- #
# ClipForge v2.0 REST API Routes
# --------------------------------------------------------------------------- #
from app.youtube import oauth as yt_oauth, quota as yt_quota, uploader as yt_uploader
from app.agent.metadata_generator import MetadataGenerator


@app.get("/api/v2/oauth/url")
def get_oauth_url(redirect_uri: str = "http://localhost:8000/api/v2/oauth/callback") -> dict:
    """Generate Google OAuth 2.0 authorization URL for YouTube channel linking."""
    try:
        url, state = yt_oauth.get_authorization_url(redirect_uri=redirect_uri)
        return {"authorization_url": url, "state": state}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/v2/oauth/callback")
def oauth_callback(
    code: str,
    state: Optional[str] = None,
    redirect_uri: str = "http://localhost:8000/api/v2/oauth/callback",
):
    """OAuth callback endpoint handling Google redirect."""
    from fastapi.responses import HTMLResponse
    try:
        result = yt_oauth.exchange_code_for_tokens(code=code, redirect_uri=redirect_uri, state=state)
        channel_title = result.get("title", "YouTube Channel")
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <title>Channel Connected - ClipForge</title>
          <style>
            body {{
              background: #0f172a;
              color: #f8fafc;
              font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
              display: flex;
              align-items: center;
              justify-content: center;
              height: 100vh;
              margin: 0;
            }}
            .card {{
              background: #1e293b;
              border: 1px solid #334155;
              padding: 2.5rem 3rem;
              border-radius: 16px;
              text-align: center;
              box-shadow: 0 10px 25px rgba(0,0,0,0.5);
              max-width: 450px;
            }}
            h1 {{ font-size: 1.5rem; margin-bottom: 0.5rem; color: #84cc16; }}
            p {{ color: #94a3b8; font-size: 0.95rem; line-height: 1.5; }}
            .channel {{ font-size: 1.1rem; font-weight: 700; color: #fff; margin: 1rem 0; }}
            .btn {{
              display: inline-block;
              background: #84cc16;
              color: #0f172a;
              font-weight: 700;
              padding: 0.75rem 1.5rem;
              border-radius: 8px;
              text-decoration: none;
              margin-top: 1.5rem;
            }}
          </style>
        </head>
        <body>
          <div class="card">
            <h1>🎉 Channel Connected!</h1>
            <div class="channel">{channel_title}</div>
            <p>Your YouTube channel has been authorized and machine-encrypted. Returning to ClipForge...</p>
            <a class="btn" href="http://localhost:8000">Return to ClipForge</a>
          </div>
          <script>
            setTimeout(function() {{
              window.location.href = "http://localhost:8000";
            }}, 2500);
          </script>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content)
    except Exception as exc:
        logger.error("OAuth verification error: %s", exc)
        err_html = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <title>Authorization Failed - ClipForge</title>
          <style>
            body {{
              background: #0f172a;
              color: #f8fafc;
              font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
              display: flex;
              align-items: center;
              justify-content: center;
              height: 100vh;
              margin: 0;
            }}
            .card {{
              background: #1e293b;
              border: 1px solid #ef4444;
              padding: 2.5rem 3rem;
              border-radius: 16px;
              text-align: center;
              box-shadow: 0 10px 25px rgba(0,0,0,0.5);
              max-width: 500px;
            }}
            h1 {{ font-size: 1.5rem; margin-bottom: 0.5rem; color: #ef4444; }}
            p {{ color: #cbd5e1; font-size: 0.95rem; line-height: 1.5; }}
            .err-box {{ background: rgba(239, 68, 68, 0.15); border: 1px solid #ef4444; border-radius: 8px; padding: 1rem; color: #fca5a5; font-family: monospace; font-size: 0.85rem; margin: 1.5rem 0; word-break: break-all; }}
            .btn {{
              display: inline-block;
              background: #ef4444;
              color: #fff;
              font-weight: 700;
              padding: 0.75rem 1.5rem;
              border-radius: 8px;
              text-decoration: none;
              margin-top: 0.5rem;
            }}
          </style>
        </head>
        <body>
          <div class="card">
            <h1>OAuth Connection Failed</h1>
            <p>Google could not verify the authorization code. Please try clicking the button below to re-authorize.</p>
            <div class="err-box">{exc}</div>
            <a class="btn" href="http://localhost:8000">Return to ClipForge & Retry</a>
          </div>
        </body>
        </html>
        """
        return HTMLResponse(content=err_html, status_code=400)


@app.get("/api/v2/youtube/channels")
def list_youtube_channels() -> list[dict]:
    """List all connected YouTube channels."""
    from app.database.session import db_session
    from app.database.repository import Repository
    with db_session() as session:
        repo = Repository(session)
        channels = repo.list_channels()
        return [
            {
                "id": ch.id,
                "youtube_channel_id": ch.youtube_channel_id,
                "title": ch.title,
                "status": ch.status,
                "credential_id": ch.credential_id,
                "last_checked_at": ch.last_checked_at.isoformat() if ch.last_checked_at else None,
            }
            for ch in channels
        ]


@app.get("/api/v2/youtube/quota")
def get_youtube_quota() -> dict:
    """Return daily quota usage estimates."""
    return {
        "daily_limit": yt_quota.DAILY_QUOTA_LIMIT,
        "consumed": yt_quota.get_consumed_quota(),
        "remaining": yt_quota.get_remaining_quota(),
        "can_upload": yt_quota.can_afford_upload(),
    }


class UploadClipRequest(BaseModel):
    clip_id: str
    index: int
    channel_id: int
    title: str
    description: str
    tags: Optional[list[str]] = None
    privacy_status: str = "private"


@app.post("/api/v2/youtube/upload")
def upload_clip_to_youtube(req: UploadClipRequest) -> dict:
    """Upload a generated clip to YouTube with fail-closed privacy safeguards."""
    clean_job_id = (req.clip_id or "").split("_")[0]
    clip_file = history.clip_path(clean_job_id, req.index)
    if not clip_file or not clip_file.exists():
        clip_file = history.clip_path(req.clip_id, req.index)
    if not clip_file or not clip_file.exists():
        raise HTTPException(status_code=404, detail="Clip file not found on disk.")

    from app.database.session import db_session
    from app.database.repository import Repository
    from app.database.models import PublishJob, Clip
    import datetime

    with db_session() as session:
        repo = Repository(session)
        ch_list = [c for c in repo.list_channels() if c.id == req.channel_id]
        if not ch_list:
            channels = repo.list_channels()
            if not channels:
                raise HTTPException(status_code=404, detail="No YouTube channel connected. Connect a channel in the Channels tab first.")
            channel = channels[0]
        else:
            channel = ch_list[0]

        if not channel.credential_id:
            raise HTTPException(status_code=400, detail="Selected YouTube channel is not authenticated.")

        # Extract scalar values INSIDE the session to avoid detached instance errors
        cred_id = channel.credential_id
        channel_id_val = channel.id

    try:
        uploader = yt_uploader.YouTubeUploader(credential_id=cred_id)
        result = uploader.upload_clip(
            video_path=clip_file,
            title=req.title,
            description=req.description,
            tags=req.tags,
            privacy_status=req.privacy_status,
        )

        # Update database status
        with db_session() as session:
            repo = Repository(session)
            db_clip_id = req.clip_id if "_" in req.clip_id else f"{req.clip_id}_{req.index}"
            repo.update_clip_review(db_clip_id, "approved")
            pub_job = session.query(PublishJob).filter(PublishJob.clip_id == db_clip_id).first()
            if pub_job:
                pub_job.status = "published"
                pub_job.youtube_video_id = result.get("youtube_video_id")
                pub_job.privacy_status = req.privacy_status
                pub_job.published_at = datetime.datetime.now(datetime.timezone.utc)
            else:
                pub_job = PublishJob(
                    clip_id=db_clip_id,
                    channel_id=channel_id_val,
                    status="published",
                    privacy_status=req.privacy_status,
                    youtube_video_id=result.get("youtube_video_id"),
                    published_at=datetime.datetime.now(datetime.timezone.utc),
                )
                session.add(pub_job)

        return {"status": "ok", **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}")


class GenerateMetadataRequest(BaseModel):
    transcript: str
    duration: float = 30.0


@app.post("/api/v2/metadata/generate")
def generate_metadata(req: GenerateMetadataRequest) -> dict:
    """Generate high-CTR title options, description, and viral hashtags."""
    generator = MetadataGenerator()
    return generator.generate_metadata(req.transcript, req.duration)


# --------------------------------------------------------------------------- #
# V2 Enhanced Metadata & Upload with Shorts/Video Mode Support
# --------------------------------------------------------------------------- #

class GenerateMetadataV2Request(BaseModel):
    transcript: str
    duration: float = 30.0
    upload_mode: str = "shorts"
    language: Optional[str] = None
    topic: Optional[str] = None


class RegenerateTitlesRequest(BaseModel):
    transcript: str
    duration: float = 30.0
    upload_mode: str = "shorts"


class RegenerateDescRequest(BaseModel):
    transcript: str
    duration: float = 30.0
    upload_mode: str = "shorts"


class UploadClipRequestV2(BaseModel):
    clip_id: str
    index: int
    channel_id: int
    title: str
    description: str
    tags: Optional[list[str]] = None
    privacy_status: str = "private"
    upload_mode: str = "shorts"
    category_id: str = "22"


@app.post("/api/v2/metadata/generate-v2")
def generate_metadata_v2(req: GenerateMetadataV2Request) -> dict:
    """Generate mode-aware YouTube Shorts or Video metadata with AI SEO."""
    generator = MetadataGenerator()
    return generator.generate_metadata_v2(
        req.transcript, req.duration, req.upload_mode, req.language, req.topic
    )


@app.post("/api/v2/metadata/regenerate-titles")
def regenerate_titles(req: RegenerateTitlesRequest) -> dict:
    """Regenerate only title suggestions for the given mode."""
    generator = MetadataGenerator()
    return generator.regenerate_titles(req.transcript, req.duration, req.upload_mode)


@app.post("/api/v2/metadata/regenerate-description")
def regenerate_description(req: RegenerateDescRequest) -> dict:
    """Regenerate only the description for the given mode."""
    generator = MetadataGenerator()
    return generator.regenerate_description(req.transcript, req.duration, req.upload_mode)


@app.get("/api/v2/clip/{clip_id}/{index}/info")
def get_clip_info(clip_id: str, index: int) -> dict:
    """Get video file metadata (dimensions, duration, codec, Shorts eligibility)."""
    import subprocess
    clean_job_id = clip_id.split("_")[0]
    clip_file = history.clip_path(clean_job_id, index)
    if not clip_file or not clip_file.exists():
        clip_file = history.clip_path(clip_id, index)
    if not clip_file or not clip_file.exists():
        raise HTTPException(status_code=404, detail="Clip file not found.")

    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", str(clip_file),
            ],
            capture_output=True, text=True, timeout=10,
        )
        import json as _json
        probe = _json.loads(result.stdout)

        video_stream = None
        for s in probe.get("streams", []):
            if s.get("codec_type") == "video":
                video_stream = s
                break

        if not video_stream:
            raise HTTPException(status_code=422, detail="No video stream found in file.")

        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        duration = float(probe.get("format", {}).get("duration", 0))
        codec = video_stream.get("codec_name", "unknown")
        file_size = int(probe.get("format", {}).get("size", 0))

        # Aspect ratio calculation
        from math import gcd
        g = gcd(width, height) if width and height else 1
        aspect_w, aspect_h = width // g, height // g
        aspect_ratio = f"{aspect_w}:{aspect_h}"

        # Shorts eligibility: vertical aspect (height > width) AND duration <= 180s
        is_vertical = height > width
        is_shorts_eligible = is_vertical and duration <= 180

        return {
            "width": width,
            "height": height,
            "duration": round(duration, 1),
            "codec": codec,
            "file_size": file_size,
            "aspect_ratio": aspect_ratio,
            "is_vertical": is_vertical,
            "is_shorts_eligible": is_shorts_eligible,
            "file_path": str(clip_file),
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="FFprobe timed out.")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="ffprobe not found. Ensure FFmpeg is installed.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to probe clip: {exc}")


@app.post("/api/v2/youtube/upload-v2")
def upload_clip_to_youtube_v2(req: UploadClipRequestV2) -> dict:
    """Upload clip to YouTube with Shorts/Video mode support."""
    clean_job_id = (req.clip_id or "").split("_")[0]
    clip_file = history.clip_path(clean_job_id, req.index)
    if not clip_file or not clip_file.exists():
        clip_file = history.clip_path(req.clip_id, req.index)
    if not clip_file or not clip_file.exists():
        raise HTTPException(status_code=404, detail="Clip file not found on disk.")

    from app.database.session import db_session
    from app.database.repository import Repository
    from app.database.models import PublishJob, Clip
    import datetime

    with db_session() as session:
        repo = Repository(session)
        ch_list = [c for c in repo.list_channels() if c.id == req.channel_id]
        if not ch_list:
            channels = repo.list_channels()
            if not channels:
                raise HTTPException(status_code=404, detail="No YouTube channel connected.")
            channel = channels[0]
        else:
            channel = ch_list[0]

        if not channel.credential_id:
            raise HTTPException(status_code=400, detail="Channel is not authenticated.")
        # Extract scalar values INSIDE the session to avoid detached instance errors
        cred_id = channel.credential_id
        channel_id_val = channel.id

    try:
        uploader = yt_uploader.YouTubeUploader(credential_id=cred_id)
        result = uploader.upload_clip(
            video_path=clip_file,
            title=req.title,
            description=req.description,
            tags=req.tags,
            privacy_status=req.privacy_status,
            upload_mode=req.upload_mode,
            category_id=req.category_id,
        )

        with db_session() as session:
            repo = Repository(session)
            db_clip_id = req.clip_id if "_" in req.clip_id else f"{req.clip_id}_{req.index}"
            repo.update_clip_review(db_clip_id, "approved")
            pub_job = session.query(PublishJob).filter(PublishJob.clip_id == db_clip_id).first()
            if pub_job:
                pub_job.status = "published"
                pub_job.youtube_video_id = result.get("youtube_video_id")
                pub_job.privacy_status = req.privacy_status
                pub_job.published_at = datetime.datetime.now(datetime.timezone.utc)
            else:
                pub_job = PublishJob(
                    clip_id=db_clip_id,
                    channel_id=channel_id_val,
                    status="published",
                    privacy_status=req.privacy_status,
                    youtube_video_id=result.get("youtube_video_id"),
                    published_at=datetime.datetime.now(datetime.timezone.utc),
                )
                session.add(pub_job)

        return {"status": "ok", **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}")


# --------------------------------------------------------------------------- #
# Autonomous Agent & Publishing Queue Endpoints
# --------------------------------------------------------------------------- #
from app.agent import source_monitor
from app.database.models import AgentConfig, Clip, PublishJob


class AgentConfigSchema(BaseModel):
    channel_id: Optional[int] = None
    name: str = "Default Agent"
    enabled: bool = True
    mode: str = "manual_approval"  # auto_publish | manual_approval
    clips_per_video: int = 3
    min_duration: int = 15
    max_duration: int = 60
    caption_preset: str = "hormozi_green"
    publish_mode: str = "private"


@app.get("/api/v2/agent/configs")
def list_agent_configs() -> list[dict]:
    """List all configured autonomous agent rules."""
    from app.database.session import db_session
    with db_session() as session:
        configs = session.query(AgentConfig).all()
        return [
            {
                "id": c.id,
                "channel_id": c.channel_id,
                "name": c.name,
                "enabled": c.enabled,
                "mode": c.mode,
                "clips_per_video": c.clips_per_video,
                "min_duration": c.min_duration,
                "max_duration": c.max_duration,
                "caption_preset": c.caption_preset,
                "publish_mode": c.publish_mode,
            }
            for c in configs
        ]


@app.post("/api/v2/agent/configs")
def save_agent_config(cfg: AgentConfigSchema) -> dict:
    """Create or update an autonomous agent configuration."""
    from app.database.session import db_session
    with db_session() as session:
        obj = AgentConfig(
            channel_id=cfg.channel_id,
            name=cfg.name,
            enabled=cfg.enabled,
            mode=cfg.mode,
            clips_per_video=cfg.clips_per_video,
            min_duration=cfg.min_duration,
            max_duration=cfg.max_duration,
            caption_preset=cfg.caption_preset,
            publish_mode=cfg.publish_mode,
        )
        session.add(obj)
        session.flush()
        return {"status": "ok", "config_id": obj.id}


@app.get("/api/v2/agent/watched-sources")
def get_watched_sources() -> list[dict]:
    """Scan and list videos detected in the local watched directory."""
    return source_monitor.scan_watched_directory()


@app.post("/api/v2/agent/scan")
def trigger_watched_scan() -> dict:
    """Trigger an immediate scan and reconciliation of watched sources."""
    count = source_monitor.sync_watched_sources()
    return {"status": "ok", "new_or_matched_sources": count}


@app.get("/api/v2/publishing/queue")
def get_publishing_queue() -> list[dict]:
    """List all short-form clips in the publishing review queue."""
    from app.database.session import db_session
    with db_session() as session:
        clips = session.query(Clip).order_by(Clip.created_at.desc()).limit(100).all()
        results = []
        for c in clips:
            meta = json.loads(c.metadata_json or "{}") if c.metadata_json else {}
            results.append({
                "clip_id": c.id,
                "job_id": c.job_id,
                "index": c.clip_index,
                "title": c.text,
                "duration": round(c.duration, 1),
                "score": c.score,
                "output_path": c.output_path,
                "quality_status": c.quality_status,
                "review_status": c.review_status,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "metadata": meta,
                "has_publish_job": c.publish_job is not None,
                "publish_status": c.publish_job.status if c.publish_job else None,
            })
        return results


@app.post("/api/v2/publishing/{clip_id}/approve")
def approve_clip(clip_id: str, channel_id: Optional[int] = None, privacy_status: str = "private") -> dict:
    """Approve a clip for publishing to the connected YouTube channel."""
    from app.database.session import db_session
    from app.database.repository import Repository
    with db_session() as session:
        repo = Repository(session)
        clip = repo.get_clip(clip_id)
        if not clip:
            raise HTTPException(status_code=404, detail="Clip not found.")

        repo.update_clip_review(clip_id, "approved")

        # Resolve channel
        ch_id = channel_id
        if not ch_id:
            channels = repo.list_channels()
            if channels:
                ch_id = channels[0].id

        if ch_id:
            repo.enqueue_publish_job(clip_id, ch_id, privacy_status=privacy_status)

        return {"status": "ok", "clip_id": clip_id, "review_status": "approved"}


@app.post("/api/v2/publishing/{clip_id}/reject")
def reject_clip(clip_id: str) -> dict:
    """Reject a clip from publishing."""
    from app.database.session import db_session
    from app.database.repository import Repository
    with db_session() as session:
        repo = Repository(session)
        clip = repo.get_clip(clip_id)
        if not clip:
            raise HTTPException(status_code=404, detail="Clip not found.")

        repo.update_clip_review(clip_id, "rejected")
        return {"status": "ok", "clip_id": clip_id, "review_status": "rejected"}

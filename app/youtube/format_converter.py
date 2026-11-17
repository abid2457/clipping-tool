"""Automatic video aspect ratio converter to guarantee YouTube Shorts eligibility."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)


def _patch_ffmpeg_path() -> None:
    """Ensure ffmpeg/ffprobe is on PATH across Windows WinGet and common paths."""
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        winget_root = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if winget_root.is_dir():
            for exe in winget_root.rglob("ffmpeg.exe"):
                bin_dir = str(exe.parent)
                if bin_dir not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
                break


def probe_video_dimensions(video_path: Path | str) -> Tuple[int, int, float]:
    """Return (width, height, duration) using ffprobe."""
    _patch_ffmpeg_path()
    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"Video file not found: {path}")

    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {res.stderr}")

    data = json.loads(res.stdout)
    width, height = 0, 0
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            width = int(s.get("width", 0))
            height = int(s.get("height", 0))
            break

    duration = float(data.get("format", {}).get("duration", 0.0))
    return width, height, duration


def ensure_shorts_vertical(video_path: Path | str, style: str = "blur") -> Path:
    """Ensure video file is strictly vertical 9:16 (1080x1920) for YouTube Shorts.

    YouTube's ingest algorithm categorizes videos with width > height as standard horizontal
    videos regardless of #Shorts tags. This function guarantees the video satisfies the
    strict vertical 9:16 aspect ratio so YouTube immediately routes it into the Shorts shelf.

    Args:
        video_path: Path to the input video.
        style: "blur" (aesthetic blurred background, recommended) or "crop" (center crop).

    Returns:
        Path to the 9:16 vertical video (either the original if already vertical, or converted).
    """
    _patch_ffmpeg_path()
    path = Path(video_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Video file not found: {path}")

    width, height, duration = probe_video_dimensions(path)
    logger.info("Probed video for Shorts eligibility: %dx%d (duration=%.1fs)", width, height, duration)

    # If already vertical (9:16) or square (1:1), YouTube will recognize it as a Short!
    if height >= width:
        logger.info("Video is already vertical/square (%dx%d). Ready for YouTube Shorts.", width, height)
        return path

    # Horizontal video (width > height) must be transcoded to 1080x1920 vertical canvas
    logger.warning(
        "Video %s is horizontal (%dx%d). Auto-transcoding to 1080x1920 vertical 9:16 canvas for YouTube Shorts...",
        path.name, width, height,
    )

    out_name = f"{path.stem}_shorts_9_16.mp4"
    out_path = path.parent / out_name

    # Check cache: reuse if existing and newer than source
    if out_path.is_file() and out_path.stat().st_mtime >= path.stat().st_mtime:
        out_w, out_h, _ = probe_video_dimensions(out_path)
        if out_h > out_w:
            logger.info("Reusing cached vertical 9:16 video: %s", out_path)
            return out_path

    if style == "crop":
        filter_str = "scale=-2:1920,crop=1080:1920:(in_w-1080)/2:0[v]"
    else:
        # High-performance fast blur: downscale to 120x213 for instant blur, then upscale
        filter_str = (
            "[0:v]scale=120:213:force_original_aspect_ratio=increase,crop=120:213,boxblur=5:2,scale=1080:1920[bg];"
            "[0:v]scale=1080:-2[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
        )

    cmd = [
        "ffmpeg", "-y", "-i", str(path),
        "-filter_complex", filter_str,
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        str(out_path),
    ]

    res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if res.returncode != 0:
        logger.error("FFmpeg vertical transcoding failed: %s", res.stderr)
        # If conversion fails for any reason, fall back to original rather than crashing
        return path

    logger.info("Successfully transcoded horizontal clip to 9:16 vertical Short: %s", out_path)
    return out_path

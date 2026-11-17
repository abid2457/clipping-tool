"""Hardware encoder detection and parameter selection for FFmpeg."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_DETECTED_ENCODER: Optional[str] = None


def _ensure_ffmpeg_on_path() -> None:
    """Check common Windows install locations if ffmpeg is not already in PATH."""
    if shutil.which("ffmpeg") is not None:
        return

    candidates: List[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        winget_root = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if winget_root.is_dir():
            for pkg in winget_root.iterdir():
                if pkg.is_dir() and "ffmpeg" in pkg.name.lower():
                    for exe in pkg.rglob("ffmpeg.exe"):
                        candidates.append(exe.parent)
                        break

    candidates.append(Path(r"C:\ProgramData\chocolatey\bin"))
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


def detect_best_encoder() -> str:
    """Probe FFmpeg to detect available hardware-accelerated H.264 encoders.

    Returns:
    - 'h264_nvenc' for NVIDIA GPUs
    - 'h264_qsv' for Intel QuickSync
    - 'h264_amf' for AMD GPUs
    - 'libx264' fallback for CPU encoding
    """
    global _DETECTED_ENCODER
    if _DETECTED_ENCODER is not None:
        return _DETECTED_ENCODER

    # Allow environment override (e.g. FORCE_CPU=1 or ENCODER=h264_nvenc)
    env_override = os.environ.get("CLIPFORGE_ENCODER")
    if env_override:
        _DETECTED_ENCODER = env_override
        return env_override

    if os.environ.get("FORCE_CPU") == "1":
        _DETECTED_ENCODER = "libx264"
        return "libx264"

    _ensure_ffmpeg_on_path()
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"

    try:
        proc = subprocess.run(
            [ffmpeg_bin, "-encoders"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        output = proc.stdout or ""

        candidates = []
        if "h264_nvenc" in output:
            candidates.append("h264_nvenc")
        if "h264_qsv" in output:
            candidates.append("h264_qsv")
        if "h264_amf" in output:
            candidates.append("h264_amf")

        for cand in candidates:
            test_cmd = [
                ffmpeg_bin,
                "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1",
                "-c:v", cand,
                "-f", "null", "-",
            ]
            try:
                test_proc = subprocess.run(
                    test_cmd,
                    capture_output=True,
                    timeout=3,
                    check=False,
                )
                if test_proc.returncode == 0:
                    logger.info("Hardware acceleration verified: using '%s'", cand)
                    _DETECTED_ENCODER = cand
                    return cand
            except Exception:
                pass

    except Exception as e:
        logger.debug("Encoder probing encountered error: %s", e)

    logger.info("Using standard CPU encoder: 'libx264'")
    _DETECTED_ENCODER = "libx264"
    return "libx264"


def get_video_encode_args() -> List[str]:
    """Return optimized FFmpeg video and audio encoding arguments."""
    encoder = detect_best_encoder()

    if encoder == "h264_nvenc":
        video_args = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "22", "-pix_fmt", "yuv420p"]
    elif encoder == "h264_qsv":
        video_args = ["-c:v", "h264_qsv", "-global_quality", "22", "-pix_fmt", "nv12"]
    elif encoder == "h264_amf":
        video_args = ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_p", "22", "-qp_i", "22", "-pix_fmt", "yuv420p"]
    else:
        video_args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]

    audio_args = ["-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"]
    return video_args + audio_args

"""Multi-gate automated quality assurance and verification engine."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.youtube.quota import can_afford_upload

logger = logging.getLogger(__name__)


class QualityReport:
    def __init__(self) -> None:
        self.passed: bool = True
        self.status: str = "passed"  # passed, warning, failed
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.details: Dict[str, Any] = {}

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.passed = False
        self.status = "failed"

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)
        if self.status != "failed":
            self.status = "warning"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "status": self.status,
            "errors": self.errors,
            "warnings": self.warnings,
            "details": self.details,
        }


class QualityChecker:
    """Validates rendered clips against technical, content, and publishing standards."""

    def __init__(self) -> None:
        self.ffprobe_bin = shutil.which("ffprobe") or "ffprobe"

    def probe_video(self, video_path: Path) -> Dict[str, Any]:
        """Inspect video streams via ffprobe."""
        cmd = [
            self.ffprobe_bin,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(video_path),
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
            if res.returncode == 0 and res.stdout:
                return json.loads(res.stdout)
        except Exception as e:
            logger.debug("ffprobe failed: %s", e)
        return {}

    def run_all_checks(
        self,
        clip_path: Path | str,
        expected_duration: Optional[float] = None,
        transcript_text: Optional[str] = None,
        check_publishing: bool = False,
    ) -> QualityReport:
        """Execute full technical, content, and publishing quality validation gates."""
        report = QualityReport()
        path = Path(clip_path)

        # -------------------------------------------------------------
        # 1. Technical Gate
        # -------------------------------------------------------------
        if not path.is_file():
            report.add_error(f"Rendered video file does not exist: {path}")
            return report

        file_size = path.stat().st_size
        report.details["file_size_bytes"] = file_size
        if file_size < 100_000:  # < 100 KB indicates broken or empty file
            report.add_error(f"File size too small ({file_size} bytes). Likely a render failure.")

        probe_data = self.probe_video(path)
        if probe_data:
            streams = probe_data.get("streams", [])
            has_video = any(s.get("codec_type") == "video" for s in streams)
            has_audio = any(s.get("codec_type") == "audio" for s in streams)

            if not has_video:
                report.add_error("Video stream missing or corrupt.")
            if not has_audio:
                report.add_warning("Audio stream missing from rendered clip.")

            fmt = probe_data.get("format", {})
            dur = float(fmt.get("duration", 0.0))
            report.details["probed_duration"] = dur
            if dur < 3.0:
                report.add_error(f"Duration too short ({dur:.1f}s). Minimum valid clip is 3s.")
            elif dur > 120.0:
                report.add_warning(f"Duration ({dur:.1f}s) exceeds standard YouTube Shorts limit (60s).")

            if expected_duration and abs(dur - expected_duration) > 2.0:
                report.add_warning(f"Rendered duration ({dur:.1f}s) differs from target ({expected_duration:.1f}s).")

        # -------------------------------------------------------------
        # 2. Content Gate
        # -------------------------------------------------------------
        if transcript_text is not None:
            words = transcript_text.strip().split()
            report.details["word_count"] = len(words)
            if len(words) < 3:
                report.add_warning("Very low word density in clip (less than 3 words).")

        # -------------------------------------------------------------
        # 3. Publishing Gate
        # -------------------------------------------------------------
        if check_publishing:
            if not can_afford_upload():
                report.add_error("Daily YouTube API quota insufficient for uploading (need 1,600 units).")

        return report

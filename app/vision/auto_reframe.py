"""Auto-reframing coordinator generating dynamic pan/zoom keyframes from face tracking."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Any
from app.vision.face_tracker import FaceTracker
from app.vision.smoothing import smooth_trajectory

logger = logging.getLogger(__name__)

_tracker = None


def get_face_tracker() -> FaceTracker:
    global _tracker
    if _tracker is None:
        _tracker = FaceTracker()
    return _tracker


def generate_auto_keyframes(
    video_path: Path | str,
    start_seconds: float,
    end_seconds: float,
    aspect_ratio: str = "9:16",
    sample_fps: float = 2.0,
) -> List[Dict[str, float]]:
    """Analyze video subject positions and generate smooth crop keyframes.

    Returns:
    - List of keyframe dicts matching ReframeKeyframe schema:
      [{'time': 0.0, 'pos_x': 52.0, 'pos_y': 50.0, 'zoom': 100.0}, ...]
    """
    default_kf = [{"time": 0.0, "pos_x": 50.0, "pos_y": 50.0, "zoom": 100.0}]

    # If not vertical 9:16 crop, center crop is standard
    if aspect_ratio != "9:16":
        return default_kf

    try:
        tracker = get_face_tracker()
        raw_trajectory = tracker.track_clip(
            video_path=video_path,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            sample_fps=sample_fps,
        )

        if not raw_trajectory:
            return default_kf

        smoothed = smooth_trajectory(
            raw_points=raw_trajectory,
            alpha=0.25,
            deadband=0.035,
            min_keyframe_interval=1.2,
        )

        keyframes: List[Dict[str, float]] = []
        for k in smoothed:
            # Map normalized [0.0 - 1.0] to percentage [0.0 - 100.0]
            pct_x = max(0.0, min(100.0, k["x"] * 100.0))
            keyframes.append({
                "time": round(k["t"], 2),
                "pos_x": round(pct_x, 1),
                "pos_y": 50.0,
                "zoom": 100.0,
            })

        logger.info(
            "Auto-reframe generated %d keyframe(s) for %.1fs - %.1fs (start pos_x: %.1f%%)",
            len(keyframes),
            start_seconds,
            end_seconds,
            keyframes[0]["pos_x"],
        )
        return keyframes

    except Exception as e:
        logger.warning("Auto-reframe failed, defaulting to center crop: %s", e)
        return default_kf

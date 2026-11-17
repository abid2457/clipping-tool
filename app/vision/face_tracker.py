"""Lightweight face detection and speaker tracking via OpenCV."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple
import cv2

logger = logging.getLogger(__name__)


class FaceTracker:
    """Detects facial centers across video frames using OpenCV Haar Cascades."""

    def __init__(self) -> None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self.cascade = cv2.CascadeClassifier(cascade_path)
        if self.cascade.empty():
            logger.warning("Could not load Haar Cascade from %s", cascade_path)

    def detect_primary_face(self, frame_bgr) -> Optional[float]:
        """Detect the largest face in frame and return its normalized horizontal center [0.0 - 1.0]."""
        if frame_bgr is None or self.cascade.empty():
            return None

        h, w = frame_bgr.shape[:2]
        if h == 0 or w == 0:
            return None

        # Downscale frame for fast detection (max 640px width)
        scale = 1.0
        if w > 640:
            scale = 640.0 / w
            new_w, new_h = 640, int(h * scale)
            small = cv2.resize(frame_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
        else:
            small = frame_bgr

        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)

        faces = self.cascade.detectMultiScale(
            gray,
            scaleFactor=1.15,
            minNeighbors=4,
            minSize=(24, 24),
            flags=cv2.CASCADE_SCALE_IMAGE,
        )

        if len(faces) == 0:
            return None

        # Pick largest face by area (closest speaker / main subject)
        largest_face = max(faces, key=lambda f: f[2] * f[3])
        fx, fy, fw, fh = largest_face

        # Center in small frame coordinates
        face_center_x = (fx + fw / 2.0) / small.shape[1]
        return round(float(face_center_x), 3)

    def track_clip(
        self,
        video_path: Path | str,
        start_seconds: float,
        end_seconds: float,
        sample_fps: float = 2.0,
    ) -> List[Tuple[float, float]]:
        """Sample video frames across duration and return [(relative_time, x_center), ...]."""
        path_str = str(video_path)
        cap = cv2.VideoCapture(path_str)
        if not cap.isOpened():
            logger.warning("OpenCV could not open video: %s", path_str)
            return []

        trajectory: List[Tuple[float, float]] = []
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            duration = (total_frames / fps) if fps > 0 else (end_seconds + 5.0)

            start_t = max(0.0, float(start_seconds))
            end_t = min(duration, float(end_seconds))
            clip_dur = max(0.5, end_t - start_t)

            step_sec = 1.0 / max(1.0, sample_fps)
            current_t = start_t
            last_known_x = 0.5

            while current_t <= end_t:
                target_frame = int(current_t * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                ret, frame = cap.read()
                if not ret or frame is None:
                    break

                detected_x = self.detect_primary_face(frame)
                if detected_x is not None:
                    last_known_x = detected_x

                rel_t = current_t - start_t
                trajectory.append((rel_t, last_known_x))
                current_t += step_sec

        except Exception as e:
            logger.warning("Error during video face sampling: %s", e)
        finally:
            cap.release()

        return trajectory

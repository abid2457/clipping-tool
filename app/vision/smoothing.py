"""Trajectory smoothing and deadband filtering for camera pan keyframes."""

from __future__ import annotations

from typing import List, Tuple, Dict


def smooth_trajectory(
    raw_points: List[Tuple[float, float]],
    alpha: float = 0.3,
    deadband: float = 0.04,
    min_keyframe_interval: float = 1.0,
) -> List[Dict[str, float]]:
    """Smooth raw face center coordinates and emit sparse, stable pan keyframes.

    Parameters:
    - raw_points: List of (time_in_seconds, normalized_x_center [0.0 - 1.0])
    - alpha: Exponential smoothing factor (0.0 = static, 1.0 = raw unsmoothed)
    - deadband: Minimum shift required to register camera movement (prevents head wobble jitter)
    - min_keyframe_interval: Minimum time between emitted keyframes unless a major shift occurs

    Returns:
    - List of keyframe dicts: [{'t': float, 'x': float}, ...]
    """
    if not raw_points:
        return [{"t": 0.0, "x": 0.5}]

    # 1. Exponential moving average smoothing
    smoothed_series: List[Tuple[float, float]] = []
    current_smooth = raw_points[0][1]

    for t, raw_x in raw_points:
        current_smooth = alpha * raw_x + (1.0 - alpha) * current_smooth
        smoothed_series.append((t, current_smooth))

    # 2. Sparse keyframe generation with deadband
    keyframes: List[Dict[str, float]] = []
    first_t, first_x = smoothed_series[0]
    keyframes.append({"t": round(first_t, 2), "x": round(first_x, 3)})

    last_emitted_t = first_t
    last_emitted_x = first_x

    for t, x in smoothed_series[1:]:
        delta_x = abs(x - last_emitted_x)
        delta_t = t - last_emitted_t

        # Emit keyframe if moved beyond deadband and past minimum interval, or if major cut/movement
        if (delta_x >= deadband and delta_t >= min_keyframe_interval) or (delta_x >= deadband * 2.5):
            keyframes.append({"t": round(t, 2), "x": round(x, 3)})
            last_emitted_t = t
            last_emitted_x = x

    # Ensure last frame is anchored if clip is longer than 2s
    last_t, last_x = smoothed_series[-1]
    if last_t - keyframes[-1]["t"] > 1.5:
        keyframes.append({"t": round(last_t, 2), "x": round(last_x, 3)})

    return keyframes

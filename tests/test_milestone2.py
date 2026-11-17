"""Tests for Milestone 2: AI Clipping, Computer Vision & Rendering Improvements."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.intelligence.ollama_client import OllamaClient
from app.intelligence.prompts import compute_composite_virality_score, format_virality_prompt
from app.intelligence.smart_selector import SmartSelector
from app.rendering.hardware import detect_best_encoder, get_video_encode_args
from app.rendering.subtitles import format_srt, format_vtt, format_txt
from app.vision.smoothing import smooth_trajectory


def test_virality_prompt_and_scoring():
    prompt = format_virality_prompt("This is a remarkable revelation that will change everything.", 25.5)
    assert "25.5 seconds" in prompt
    assert "remarkable revelation" in prompt

    scores = {
        "hook_score": 9,
        "coherence_score": 8,
        "emotion_score": 7,
        "virality_score": 8,
        "payoff_score": 6,
    }
    # 9*0.3 + 8*0.2 + 7*0.2 + 8*0.2 + 6*0.1 = 2.7 + 1.6 + 1.4 + 1.6 + 0.6 = 7.9
    composite = compute_composite_virality_score(scores)
    assert composite == 7.9


def test_ollama_client_json_cleanup():
    client = OllamaClient()

    # Test extracting JSON from markdown wrapping
    markdown_wrapped = """Here is the score:
    ```json
    {
      "hook_score": 8,
      "coherence_score": 9,
      "title": "Secret Revealed"
    }
    ```
    Hope this helps!"""

    with patch.object(client, "generate", return_value=markdown_wrapped):
        parsed = client.generate_json("test prompt")
        assert parsed is not None
        assert parsed.get("hook_score") == 8
        assert parsed.get("title") == "Secret Revealed"


def test_smart_selector_fallback():
    selector = SmartSelector()
    sample_transcript = {
        "duration": 60.0,
        "segments": [
            {"start": 0.0, "end": 10.0, "text": "Why do most people fail at this secret?"},
            {"start": 10.0, "end": 25.0, "text": "Because they never practice the fundamentals every single day."},
            {"start": 25.0, "end": 45.0, "text": "When you actually change your daily habits, everything improves dramatically."},
            {"start": 45.0, "end": 60.0, "text": "And that is how you win in the long run."},
        ],
    }

    # Should select clips seamlessly even with Ollama disabled/offline
    clips = selector.select_clips(sample_transcript, num_clips=2, clip_length=30.0, use_ai=False)
    assert len(clips) >= 1
    assert "start" in clips[0]
    assert "end" in clips[0]
    assert "title" in clips[0]


def test_trajectory_smoothing():
    # Simulate face centered, drifting right, with high frequency noise
    raw_points = [
        (0.0, 0.50),
        (0.5, 0.51),  # tiny wobble within deadband
        (1.0, 0.50),  # tiny wobble within deadband
        (1.5, 0.70),  # major movement right
        (2.0, 0.72),
        (2.5, 0.71),
        (3.0, 0.70),
    ]

    keyframes = smooth_trajectory(raw_points, alpha=0.3, deadband=0.04)
    assert len(keyframes) >= 2
    assert keyframes[0]["t"] == 0.0
    # Initial position centered
    assert 0.45 <= keyframes[0]["x"] <= 0.55
    # Later keyframe shifted right
    assert keyframes[-1]["x"] > 0.55


def test_hardware_encoder_args():
    enc = detect_best_encoder()
    assert enc in ("h264_nvenc", "h264_qsv", "h264_amf", "libx264")

    args = get_video_encode_args()
    assert "-c:v" in args
    assert "-c:a" in args
    assert "aac" in args
    assert "-movflags" in args


def test_subtitle_formatters():
    words = [
        {"start": 1.25, "end": 1.80, "word": "Hello"},
        {"start": 1.85, "end": 2.40, "word": "world!"},
        {"start": 3.00, "end": 3.60, "word": "ClipForge"},
        {"start": 3.65, "end": 4.10, "word": "is"},
        {"start": 4.15, "end": 4.80, "word": "ready."},
    ]

    srt = format_srt(words, start_offset=0.0)
    assert "1" in srt
    assert "00:00:01,250 -->" in srt
    assert "Hello world!" in srt

    vtt = format_vtt(words, start_offset=0.0)
    assert vtt.startswith("WEBVTT")
    assert "00:00:01.250 -->" in vtt

    txt = format_txt(words)
    assert "Hello world!" in txt
    assert "ClipForge is ready." in txt


def test_transcript_update_api(client):
    res = client.put(
        "/api/job/test_job_123/transcript",
        json={
            "words": [
                {"start": 0.0, "end": 1.5, "word": "Corrected"},
                {"start": 1.5, "end": 3.0, "word": "transcript"},
            ]
        },
    )
    # If job not found, 404 is valid; let's create a job first
    if res.status_code == 404:
        from app.database.session import db_session
        from app.database.repository import Repository
        with db_session() as session:
            repo = Repository(session)
            repo.create_job(job_id="test_job_123")

        res_retry = client.put(
            "/api/job/test_job_123/transcript",
            json={"words": [{"word": "Corrected"}]},
        )
        assert res_retry.status_code == 200
        assert res_retry.json()["status"] == "ok"
    else:
        assert res.status_code == 200

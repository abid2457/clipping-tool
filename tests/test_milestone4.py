"""Tests for Milestone 4: Autonomous YouTube Agent, Watched Folders & Quality Control."""

from pathlib import Path
from app.agent import source_monitor
from app.agent.quality_checker import QualityChecker


def test_watched_source_matching():
    candidates = [
        {"stem": "episode_42_how_to_build_an_ai_startup_master", "path": "/watched/ep42.mp4", "fingerprint": "abc1"},
        {"stem": "podcast_interview_john_doe_final_cut", "path": "/watched/pod.mp4", "fingerprint": "abc2"},
    ]

    # YouTube video title from channel
    yt_title = "How To Build An AI Startup in 2026 (Episode 42)"
    match = source_monitor.find_matching_source(yt_title, candidates)
    assert match is not None
    assert match["stem"] == "episode_42_how_to_build_an_ai_startup_master"

    # Completely unrelated title should not match
    no_match = source_monitor.find_matching_source("Cooking Delicious Italian Pizza At Home", candidates)
    assert no_match is None


def test_quality_checker_missing_file():
    checker = QualityChecker()
    report = checker.run_all_checks(Path("/nonexistent/video.mp4"))
    assert report.passed is False
    assert report.status == "failed"
    assert any("does not exist" in err for err in report.errors)


def test_quality_checker_content_gate(tmp_path):
    dummy_video = tmp_path / "dummy.mp4"
    # Create 150 KB dummy file to pass the size gate
    dummy_video.write_bytes(b"\x00" * 150_000)

    checker = QualityChecker()
    report = checker.run_all_checks(dummy_video, transcript_text="too short")
    # Low word count triggers warning
    assert any("Very low word density" in warn for warn in report.warnings)


def test_agent_api_endpoints(client):
    # 1. Configs
    res_cfg = client.post(
        "/api/v2/agent/configs",
        json={"name": "Tech Channel Agent", "clips_per_video": 4, "publish_mode": "private"},
    )
    assert res_cfg.status_code == 200
    assert "config_id" in res_cfg.json()

    res_list = client.get("/api/v2/agent/configs")
    assert res_list.status_code == 200
    assert len(res_list.json()) >= 1

    # 2. Watched sources
    res_watched = client.get("/api/v2/agent/watched-sources")
    assert res_watched.status_code == 200
    assert isinstance(res_watched.json(), list)

    res_scan = client.post("/api/v2/agent/scan")
    assert res_scan.status_code == 200
    assert "new_or_matched_sources" in res_scan.json()

    # 3. Publishing Queue
    res_queue = client.get("/api/v2/publishing/queue")
    assert res_queue.status_code == 200
    assert isinstance(res_queue.json(), list)

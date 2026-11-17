"""Mode B Autonomous Orchestrator executing the complete pipeline from source to publish queue."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from app.database.session import db_session
from app.database.repository import Repository
from app.database.models import AgentConfig, SourceVideo, Job, Clip, PublishJob
from app.intelligence.smart_selector import SmartSelector
from app.vision.auto_reframe import generate_auto_keyframes
from app.agent.quality_checker import QualityChecker
from app.agent.metadata_generator import MetadataGenerator
from app.clipper import ClipOptions, generate_clip, target_size
from app.models import AspectRatio, FitMode
from app import captions, pretranscribe
from app.paths import CLIPS_DIR

logger = logging.getLogger(__name__)


class AutonomousOrchestrator:
    """Orchestrates end-to-end Mode B processing for a source video and agent configuration."""

    def __init__(self) -> None:
        self.selector = SmartSelector()
        self.quality = QualityChecker()
        self.metadata_gen = MetadataGenerator()

    def process_source_video(self, source_video_id: int, agent_config_id: Optional[int] = None) -> Optional[str]:
        """Execute full autonomous pipeline on a source video."""
        with db_session() as session:
            repo = Repository(session)
            source_video = session.query(SourceVideo).filter(SourceVideo.id == source_video_id).first()
            if not source_video:
                logger.error("SourceVideo %d not found.", source_video_id)
                return None

            if not source_video.local_path or not Path(source_video.local_path).is_file():
                source_video.ingest_status = "awaiting_source"
                logger.info("SourceVideo %d has no valid local file. Marked 'awaiting_source'.", source_video_id)
                return None

            config = None
            if agent_config_id:
                config = session.query(AgentConfig).filter(AgentConfig.id == agent_config_id).first()

            job_id = uuid.uuid4().hex
            job = repo.create_job(
                job_id=job_id,
                source_video_id=source_video.id,
                agent_config_id=config.id if config else None,
                stage="queued",
                status="running",
            )

        # Execute processing
        try:
            self._execute_pipeline(job_id, source_video.local_path, config)
            return job_id
        except Exception as e:
            logger.exception("Autonomous pipeline failed for job %s: %s", job_id, e)
            with db_session() as session:
                repo = Repository(session)
                repo.update_job_progress(job_id, stage="error", progress=0.0, status="failed", error_message=str(e))
            return None

    def _execute_pipeline(self, job_id: str, video_path_str: str, config: Optional[AgentConfig]) -> None:
        source_path = Path(video_path_str)
        source_id = source_path.stem
        num_clips = config.clips_per_video if config else 3
        caption_preset = config.caption_preset if config else "hormozi_green"
        publish_mode = config.publish_mode if config else "private"
        auto_mode = config.mode if config else "manual_approval"

        with db_session() as session:
            repo = Repository(session)
            repo.update_job_progress(job_id, stage="transcribing", progress=0.25)

        # 1. Transcribe
        transcript = pretranscribe.get_or_transcribe(source_path, source_id, device="auto")

        with db_session() as session:
            repo = Repository(session)
            repo.update_job_progress(job_id, stage="selecting", progress=0.60)

        # 2. Select Viral Moments
        windows = self.selector.select_clips(transcript, num_clips=num_clips)
        if not windows:
            raise RuntimeError("No candidate moments found in video.")

        with db_session() as session:
            repo = Repository(session)
            repo.update_job_progress(job_id, stage="rendering", progress=0.75)

        # 3. Render Clips with Auto Face Tracking
        words = transcript.get("words") or []
        width, height = target_size(AspectRatio.VERTICAL_9_16, FitMode.CROP)
        clip_dir = CLIPS_DIR / job_id
        clip_dir.mkdir(parents=True, exist_ok=True)

        for idx, win in enumerate(windows):
            start = float(win["start"])
            end = float(win["end"])
            duration = end - start
            clip_words = [w for w in words if w["end"] > start and w["start"] < end]
            text = win.get("text") or " ".join(w["word"] for w in clip_words)

            ass_path = clip_dir / f"{idx}.ass"
            captions.build_ass(
                words=clip_words,
                style_preset=caption_preset,
                video_w=width,
                video_h=height,
                out_path=ass_path,
                clip_start=start,
            )

            # Auto Face-Tracking Keyframes
            auto_kfs = generate_auto_keyframes(source_path, start, end, aspect_ratio="9:16")

            opts = ClipOptions(
                aspect_ratio=AspectRatio.VERTICAL_9_16,
                fit_mode=FitMode.CROP,
                ass_path=ass_path,
                clip_id=job_id,
                index=idx,
                reframe=auto_kfs,
            )

            rendered_mp4 = generate_clip(source_path, start, end, opts)

            # 4. Multi-Gate Quality Assurance
            q_report = self.quality.run_all_checks(
                clip_path=rendered_mp4,
                expected_duration=duration,
                transcript_text=text,
            )

            # 5. Generate SEO Metadata
            meta = self.metadata_gen.generate_metadata(text, duration)

            # 6. Save in SQLite
            db_clip_id = f"{job_id}_{idx}"
            with db_session() as session:
                repo = Repository(session)
                clip_rec = repo.create_clip(
                    clip_id=db_clip_id,
                    job_id=job_id,
                    clip_index=idx,
                    start_seconds=start,
                    end_seconds=end,
                    score=float(win.get("score", 7.5)),
                    text=meta.get("primary_title") or win.get("title"),
                    output_path=f"/clips/{job_id}/{idx}.mp4",
                    metadata_json=json.dumps(meta),
                )
                clip_rec.quality_status = q_report.status

                # If channel is linked, enqueue into publishing queue
                if config and config.channel_id:
                    review_state = "approved" if auto_mode == "auto_publish" else "pending"
                    clip_rec.review_status = review_state

                    if review_state == "approved" and q_report.passed:
                        repo.enqueue_publish_job(
                            clip_id=db_clip_id,
                            channel_id=config.channel_id,
                            privacy_status=publish_mode,
                        )

        with db_session() as session:
            repo = Repository(session)
            repo.update_job_progress(job_id, stage="done", progress=1.0, status="completed")

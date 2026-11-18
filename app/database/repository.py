"""Transactional repository and database abstraction for ClipForge v2.0."""

from __future__ import annotations

import datetime
import json
from typing import Any, Dict, List, Optional
from sqlalchemy import select, update, and_, or_, desc
from sqlalchemy.orm import Session
from app.database.models import (
    YouTubeChannel,
    OAuthCredential,
    SourceVideo,
    AgentConfig,
    Job,
    Clip,
    PublishJob,
    Schedule,
    JobEvent,
    utcnow,
)


class Repository:
    """Encapsulates all atomic queries and database transactions."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # -------------------------------------------------------------------------
    # Jobs
    # -------------------------------------------------------------------------
    def create_job(
        self,
        job_id: str,
        source_video_id: Optional[int] = None,
        agent_config_id: Optional[int] = None,
        idempotency_key: Optional[str] = None,
        stage: str = "queued",
        status: str = "pending",
        request_json: Optional[str] = None,
        checkpoint_json: Optional[str] = None,
    ) -> Job:
        job = Job(
            id=job_id,
            source_video_id=source_video_id,
            agent_config_id=agent_config_id,
            idempotency_key=idempotency_key,
            stage=stage,
            status=status,
            progress=0.0,
            attempt_count=0,
            request_json=request_json,
            checkpoint_json=checkpoint_json,
        )
        self.db.add(job)
        self.db.flush()
        self.record_event(job_id, "job_created", {"status": status, "stage": stage})
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        return self.db.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()

    def get_active_job(self) -> Optional[Job]:
        """Find the most recent non-completed, non-failed job (running, pending, paused, queued)."""
        stmt = (
            select(Job)
            .where(Job.status.in_(("pending", "running", "paused", "queued")))
            .order_by(desc(Job.created_at))
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_latest_job(self) -> Optional[Job]:
        """Find the most recent job regardless of status."""
        stmt = select(Job).order_by(desc(Job.created_at)).limit(1)
        return self.db.execute(stmt).scalar_one_or_none()

    def update_job_progress(
        self,
        job_id: str,
        stage: str,
        progress: float,
        status: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        checkpoint_json: Optional[str] = None,
    ) -> Optional[Job]:
        values: Dict[str, Any] = {
            "stage": stage,
            "progress": round(float(progress), 2),
            "updated_at": utcnow(),
        }
        if status:
            values["status"] = status
        if error_code is not None:
            values["error_code"] = error_code
        if error_message is not None:
            values["error_message"] = error_message
        if checkpoint_json is not None:
            values["checkpoint_json"] = checkpoint_json

        stmt = update(Job).where(Job.id == job_id).values(**values)
        self.db.execute(stmt)
        self.db.flush()

        if status in ("failed", "completed"):
            self.record_event(job_id, f"job_{status}", {"error_code": error_code, "error_message": error_message})
        return self.get_job(job_id)

    def list_jobs(self, limit: int = 50, offset: int = 0) -> List[Job]:
        stmt = select(Job).order_by(desc(Job.created_at)).limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars().all())

    # -------------------------------------------------------------------------
    # Worker Leases & State Recovery
    # -------------------------------------------------------------------------
    def acquire_job_lease(self, worker_id: str, lease_duration_seconds: int = 120) -> Optional[Job]:
        """Atomically claim the next pending or expired job."""
        now = utcnow()
        expires = now + datetime.timedelta(seconds=lease_duration_seconds)

        # Candidate: status in ('pending', 'running') and (lease_expires_at is null or lease_expires_at < now)
        stmt = (
            select(Job)
            .where(
                or_(
                    Job.status == "pending",
                    and_(Job.status == "running", Job.lease_expires_at < now),
                )
            )
            .order_by(Job.created_at.asc())
            .limit(1)
        )
        job = self.db.execute(stmt).scalar_one_or_none()
        if job:
            job.lease_owner = worker_id
            job.lease_expires_at = expires
            job.status = "running"
            job.attempt_count += 1
            job.updated_at = now
            self.db.flush()
            self.record_event(job.id, "lease_acquired", {"worker": worker_id, "attempt": job.attempt_count})
            return job
        return None

    def renew_job_lease(self, job_id: str, worker_id: str, lease_duration_seconds: int = 120) -> bool:
        now = utcnow()
        expires = now + datetime.timedelta(seconds=lease_duration_seconds)
        stmt = (
            update(Job)
            .where(and_(Job.id == job_id, Job.lease_owner == worker_id))
            .values(lease_expires_at=expires, updated_at=now)
        )
        res = self.db.execute(stmt)
        return res.rowcount > 0

    def recover_orphaned_jobs(self) -> int:
        """Mark stale leased jobs as failed or reset them to pending on server boot."""
        now = utcnow()
        stmt = (
            update(Job)
            .where(and_(Job.status == "running", Job.lease_expires_at < now))
            .values(
                status="failed",
                error_code="WORKER_TIMEOUT_OR_CRASH",
                error_message="Job was interrupted by unexpected server restart or worker timeout.",
                updated_at=now,
            )
        )
        res = self.db.execute(stmt)
        return res.rowcount

    # -------------------------------------------------------------------------
    # Clips
    # -------------------------------------------------------------------------
    def create_clip(
        self,
        clip_id: str,
        job_id: str,
        clip_index: int,
        start_seconds: float,
        end_seconds: float,
        score: float = 0.0,
        text: Optional[str] = None,
        output_path: Optional[str] = None,
        render_recipe_json: Optional[str] = None,
        metadata_json: Optional[str] = None,
    ) -> Clip:
        clip = Clip(
            id=clip_id,
            job_id=job_id,
            clip_index=clip_index,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            duration=max(0.0, end_seconds - start_seconds),
            score=score,
            text=text,
            output_path=output_path,
            render_recipe_json=render_recipe_json,
            metadata_json=metadata_json,
            quality_status="passed",
            review_status="pending",
        )
        self.db.add(clip)
        self.db.flush()
        return clip

    def get_clip(self, clip_id: str) -> Optional[Clip]:
        return self.db.execute(select(Clip).where(Clip.id == clip_id)).scalar_one_or_none()

    def get_clips_for_job(self, job_id: str) -> List[Clip]:
        stmt = select(Clip).where(Clip.job_id == job_id).order_by(Clip.clip_index.asc())
        return list(self.db.execute(stmt).scalars().all())

    def update_clip_recipe(self, clip_id: str, recipe_dict: Dict[str, Any]) -> bool:
        stmt = (
            update(Clip)
            .where(Clip.id == clip_id)
            .values(render_recipe_json=json.dumps(recipe_dict))
        )
        res = self.db.execute(stmt)
        return res.rowcount > 0

    def update_clip_review(self, clip_id: str, review_status: str) -> bool:
        stmt = (
            update(Clip)
            .where(Clip.id == clip_id)
            .values(review_status=review_status)
        )
        res = self.db.execute(stmt)
        return res.rowcount > 0

    def list_all_clips(self, limit: int = 100, offset: int = 0) -> List[Clip]:
        stmt = select(Clip).order_by(desc(Clip.created_at)).limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars().all())

    # -------------------------------------------------------------------------
    # Source Videos
    # -------------------------------------------------------------------------
    def get_or_create_source_video(
        self,
        source_uri: str,
        source_type: str = "url",
        channel_id: Optional[int] = None,
        youtube_video_id: Optional[str] = None,
        local_path: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        fingerprint: Optional[str] = None,
    ) -> SourceVideo:
        stmt = select(SourceVideo).where(SourceVideo.source_uri == source_uri)
        existing = self.db.execute(stmt).scalar_one_or_none()
        if existing:
            if local_path and not existing.local_path:
                existing.local_path = local_path
            if duration_seconds and not existing.duration_seconds:
                existing.duration_seconds = duration_seconds
            return existing

        video = SourceVideo(
            source_uri=source_uri,
            source_type=source_type,
            channel_id=channel_id,
            youtube_video_id=youtube_video_id,
            local_path=local_path,
            duration_seconds=duration_seconds,
            fingerprint=fingerprint,
            ingest_status="ready" if local_path else "pending",
        )
        self.db.add(video)
        self.db.flush()
        return video

    def find_source_video_by_yt_id(self, yt_id: str) -> Optional[SourceVideo]:
        return self.db.execute(select(SourceVideo).where(SourceVideo.youtube_video_id == yt_id)).scalar_one_or_none()

    # -------------------------------------------------------------------------
    # YouTube Channels & OAuth Credentials
    # -------------------------------------------------------------------------
    def get_or_create_channel(self, channel_id: str, title: str, credential_id: Optional[int] = None) -> YouTubeChannel:
        stmt = select(YouTubeChannel).where(YouTubeChannel.youtube_channel_id == channel_id)
        ch = self.db.execute(stmt).scalar_one_or_none()
        if ch:
            ch.title = title
            if credential_id:
                ch.credential_id = credential_id
            return ch

        new_ch = YouTubeChannel(
            youtube_channel_id=channel_id,
            title=title,
            credential_id=credential_id,
            status="active",
        )
        self.db.add(new_ch)
        self.db.flush()
        return new_ch

    def list_channels(self) -> List[YouTubeChannel]:
        return list(self.db.execute(select(YouTubeChannel).order_by(YouTubeChannel.title)).scalars().all())

    def save_credential(self, provider: str, encrypted_token: str, metadata: Dict[str, Any]) -> OAuthCredential:
        cred = OAuthCredential(
            provider=provider,
            encrypted_refresh_token=encrypted_token,
            token_metadata_json=json.dumps(metadata),
        )
        self.db.add(cred)
        self.db.flush()
        return cred

    def get_credential(self, cred_id: int) -> Optional[OAuthCredential]:
        return self.db.execute(select(OAuthCredential).where(OAuthCredential.id == cred_id)).scalar_one_or_none()

    # -------------------------------------------------------------------------
    # Publishing Queue
    # -------------------------------------------------------------------------
    def enqueue_publish_job(
        self,
        clip_id: str,
        channel_id: int,
        privacy_status: str = "private",
        scheduled_at: Optional[datetime.datetime] = None,
    ) -> PublishJob:
        existing = self.db.execute(select(PublishJob).where(PublishJob.clip_id == clip_id)).scalar_one_or_none()
        if existing:
            existing.channel_id = channel_id
            existing.privacy_status = privacy_status
            existing.scheduled_at = scheduled_at
            existing.status = "queued"
            existing.last_error = None
            self.db.flush()
            return existing

        pub = PublishJob(
            clip_id=clip_id,
            channel_id=channel_id,
            privacy_status=privacy_status,
            scheduled_at=scheduled_at,
            status="queued",
        )
        self.db.add(pub)
        self.db.flush()
        return pub

    def list_publish_queue(self, status: Optional[str] = None) -> List[PublishJob]:
        stmt = select(PublishJob)
        if status:
            stmt = stmt.where(PublishJob.status == status)
        stmt = stmt.order_by(PublishJob.created_at.asc())
        return list(self.db.execute(stmt).scalars().all())

    # -------------------------------------------------------------------------
    # Job Events
    # -------------------------------------------------------------------------
    def record_event(self, job_id: str, event_type: str, payload: Optional[Dict[str, Any]] = None) -> JobEvent:
        event = JobEvent(
            job_id=job_id,
            event_type=event_type,
            payload_json=json.dumps(payload) if payload else None,
        )
        self.db.add(event)
        self.db.flush()
        return event

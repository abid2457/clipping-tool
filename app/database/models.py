"""SQLAlchemy ORM models for ClipForge v2.0."""

from __future__ import annotations

import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.database.session import Base


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class YouTubeChannel(Base):
    """Monitored YouTube channels for autonomous clipping."""
    __tablename__ = "youtube_channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    youtube_channel_id = Column(String(128), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    credential_id = Column(Integer, ForeignKey("oauth_credentials.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), default="active", nullable=False)  # active, paused, revoked
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    credential = relationship("OAuthCredential", back_populates="channels")
    source_videos = relationship("SourceVideo", back_populates="channel", cascade="all, delete-orphan")
    agent_configs = relationship("AgentConfig", back_populates="channel", cascade="all, delete-orphan")
    publish_jobs = relationship("PublishJob", back_populates="channel")


class OAuthCredential(Base):
    """Encrypted OAuth 2.0 credentials for channel management."""
    __tablename__ = "oauth_credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(50), default="google", nullable=False)
    encrypted_refresh_token = Column(Text, nullable=False)
    token_metadata_json = Column(Text, nullable=True)  # client_id, scopes, email, channel_id
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    channels = relationship("YouTubeChannel", back_populates="credential")


class SourceVideo(Base):
    """Raw video sources (uploaded, fetched via URL, or detected in watched folder)."""
    __tablename__ = "source_videos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(Integer, ForeignKey("youtube_channels.id", ondelete="SET NULL"), nullable=True, index=True)
    youtube_video_id = Column(String(64), nullable=True, index=True)
    source_type = Column(String(50), default="url", nullable=False)  # url, upload, watched_folder
    source_uri = Column(Text, nullable=False)
    local_path = Column(Text, nullable=True)
    fingerprint = Column(String(128), nullable=True, index=True)
    duration_seconds = Column(Float, nullable=True)
    ingest_status = Column(String(50), default="ready", nullable=False)  # pending, downloading, ready, awaiting_source, failed
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    channel = relationship("YouTubeChannel", back_populates="source_videos")
    jobs = relationship("Job", back_populates="source_video", cascade="all, delete-orphan")


class AgentConfig(Base):
    """Configuration rules for Mode B autonomous agent execution."""
    __tablename__ = "agent_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(Integer, ForeignKey("youtube_channels.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String(100), default="Default Agent", nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    mode = Column(String(50), default="manual_approval", nullable=False)  # auto_publish, manual_approval
    clips_per_video = Column(Integer, default=3, nullable=False)
    min_duration = Column(Integer, default=15, nullable=False)
    max_duration = Column(Integer, default=60, nullable=False)
    caption_preset = Column(String(50), default="hormozi", nullable=False)
    auto_reframe = Column(Boolean, default=True, nullable=False)
    publish_mode = Column(String(50), default="private", nullable=False)  # draft, private, unlisted, public
    preset_json = Column(Text, nullable=True)  # aspect ratio, music, effects overrides
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    channel = relationship("YouTubeChannel", back_populates="agent_configs")
    jobs = relationship("Job", back_populates="agent_config")
    schedules = relationship("Schedule", back_populates="agent_config", cascade="all, delete-orphan")


class Job(Base):
    """Durable state for video processing jobs."""
    __tablename__ = "jobs"

    id = Column(String(64), primary_key=True)  # Hex job_id or UUID
    source_video_id = Column(Integer, ForeignKey("source_videos.id", ondelete="SET NULL"), nullable=True, index=True)
    agent_config_id = Column(Integer, ForeignKey("agent_configs.id", ondelete="SET NULL"), nullable=True, index=True)
    idempotency_key = Column(String(128), unique=True, nullable=True, index=True)
    status = Column(String(50), default="pending", nullable=False, index=True)  # pending, running, completed, failed, cancelled
    stage = Column(String(50), default="queued", nullable=False)  # queued, downloading, transcribing, selecting, reframing, rendering, validating, done
    progress = Column(Float, default=0.0, nullable=False)
    attempt_count = Column(Integer, default=0, nullable=False)
    lease_owner = Column(String(128), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    error_code = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    request_json = Column(Text, nullable=True)  # Serialized GenerateRequest payload
    checkpoint_json = Column(Text, nullable=True)  # Checkpoint state (source_mp4, transcript, windows, rendered_indexes)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    source_video = relationship("SourceVideo", back_populates="jobs")
    agent_config = relationship("AgentConfig", back_populates="jobs")
    clips = relationship("Clip", back_populates="job", cascade="all, delete-orphan")
    events = relationship("JobEvent", back_populates="job", cascade="all, delete-orphan")


class Clip(Base):
    """Generated short-form clip records."""
    __tablename__ = "clips"

    id = Column(String(128), primary_key=True)  # {job_id}_{index}
    job_id = Column(String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    clip_index = Column(Integer, default=0, nullable=False)
    start_seconds = Column(Float, nullable=False)
    end_seconds = Column(Float, nullable=False)
    duration = Column(Float, nullable=False)
    score = Column(Float, default=0.0, nullable=False)
    text = Column(Text, nullable=True)
    output_path = Column(Text, nullable=True)
    render_recipe_json = Column(Text, nullable=True)  # Complete FFmpeg recipe, fonts, crops, audio
    metadata_json = Column(Text, nullable=True)  # Suggested titles, tags, description, SEO
    quality_status = Column(String(50), default="passed", nullable=False)  # pending, passed, warning, failed
    review_status = Column(String(50), default="pending", nullable=False)  # pending, approved, rejected
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    job = relationship("Job", back_populates="clips")
    publish_job = relationship("PublishJob", back_populates="clip", uselist=False, cascade="all, delete-orphan")


class PublishJob(Base):
    """Publishing state machine for YouTube uploads."""
    __tablename__ = "publish_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    clip_id = Column(String(128), ForeignKey("clips.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    channel_id = Column(Integer, ForeignKey("youtube_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), default="queued", nullable=False, index=True)  # queued, uploading, published, failed
    privacy_status = Column(String(50), default="private", nullable=False)  # private, unlisted, public
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    youtube_video_id = Column(String(64), nullable=True, index=True)
    upload_session_ref = Column(Text, nullable=True)
    attempt_count = Column(Integer, default=0, nullable=False)
    last_error = Column(Text, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    clip = relationship("Clip", back_populates="publish_job")
    channel = relationship("YouTubeChannel", back_populates="publish_jobs")


class Schedule(Base):
    """Scheduled autonomous polling or publishing jobs."""
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_config_id = Column(Integer, ForeignKey("agent_configs.id", ondelete="CASCADE"), nullable=False, index=True)
    schedule_type = Column(String(50), default="interval", nullable=False)  # interval, cron
    schedule_json = Column(Text, nullable=False)  # {'minutes': 60} or cron expr
    timezone = Column(String(50), default="UTC", nullable=False)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    agent_config = relationship("AgentConfig", back_populates="schedules")


class JobEvent(Base):
    """Audit log of job state transitions and execution events."""
    __tablename__ = "job_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(100), nullable=False)
    payload_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    job = relationship("Job", back_populates="events")

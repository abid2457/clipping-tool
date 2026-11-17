"""Unit tests for SQLite database schema and repository operations."""

import datetime
from app.database.models import YouTubeChannel, Job, Clip, SourceVideo, utcnow


def test_channel_and_credentials(repo, in_memory_db):
    cred = repo.save_credential("google", "enc_token_123", {"client_id": "cid"})
    assert cred.id is not None
    assert cred.provider == "google"

    channel = repo.get_or_create_channel("UC1234567890", "Test Tech Channel", cred.id)
    assert channel.id is not None
    assert channel.youtube_channel_id == "UC1234567890"
    assert channel.credential_id == cred.id

    channels = repo.list_channels()
    assert len(channels) == 1
    assert channels[0].title == "Test Tech Channel"


def test_source_video_creation(repo, in_memory_db):
    video = repo.get_or_create_source_video(
        source_uri="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        source_type="url",
        youtube_video_id="dQw4w9WgXcQ",
        duration_seconds=212.0,
    )
    assert video.id is not None
    assert video.youtube_video_id == "dQw4w9WgXcQ"

    # Idempotent retrieval
    same_video = repo.get_or_create_source_video("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert same_video.id == video.id


def test_job_lifecycle_and_leases(repo, in_memory_db):
    job_id = "test_job_001"
    job = repo.create_job(job_id=job_id, stage="queued", status="pending")
    assert job.id == job_id
    assert job.status == "pending"

    # Lease acquisition
    claimed = repo.acquire_job_lease("worker-node-1", lease_duration_seconds=60)
    assert claimed is not None
    assert claimed.id == job_id
    assert claimed.lease_owner == "worker-node-1"
    assert claimed.status == "running"

    # Progress update
    updated = repo.update_job_progress(job_id, stage="transcribing", progress=0.45)
    assert updated.stage == "transcribing"
    assert updated.progress == 0.45

    # Lease renewal
    renewed = repo.renew_job_lease(job_id, "worker-node-1", lease_duration_seconds=120)
    assert renewed is True

    # Complete job
    finished = repo.update_job_progress(job_id, stage="done", progress=1.0, status="completed")
    assert finished.status == "completed"


def test_orphaned_job_recovery(repo, in_memory_db):
    job_id = "stale_job_999"
    repo.create_job(job_id=job_id, stage="rendering", status="pending")
    job = repo.acquire_job_lease("worker-old", lease_duration_seconds=10)

    # Artificially expire lease in the past
    job.lease_expires_at = utcnow() - datetime.timedelta(seconds=100)
    in_memory_db.commit()

    recovered = repo.recover_orphaned_jobs()
    assert recovered == 1

    check = repo.get_job(job_id)
    assert check.status == "failed"
    assert check.error_code == "WORKER_TIMEOUT_OR_CRASH"


def test_clip_creation_and_recipe(repo, in_memory_db):
    job_id = "job_clip_test"
    repo.create_job(job_id=job_id)

    clip = repo.create_clip(
        clip_id=f"{job_id}_0",
        job_id=job_id,
        clip_index=0,
        start_seconds=10.0,
        end_seconds=40.0,
        score=8.5,
        text="Sample engaging hook",
        output_path="/clips/test/0.mp4",
    )
    assert clip.duration == 30.0
    assert clip.quality_status == "passed"
    assert clip.review_status == "pending"

    # Recipe update
    recipe_dict = {"aspect_ratio": "9:16", "crop": [100, 200, 300, 400]}
    updated = repo.update_clip_recipe(clip.id, recipe_dict)
    assert updated is True

    # Review update
    approved = repo.update_clip_review(clip.id, "approved")
    assert approved is True


def test_publish_queue_workflow(repo, in_memory_db):
    job_id = "job_pub_test"
    repo.create_job(job_id=job_id)
    clip = repo.create_clip(
        clip_id=f"{job_id}_0",
        job_id=job_id,
        clip_index=0,
        start_seconds=0.0,
        end_seconds=15.0,
    )
    ch = repo.get_or_create_channel("UC_PUB_TEST", "Test Channel")

    pub_job = repo.enqueue_publish_job(clip.id, ch.id, privacy_status="private")
    assert pub_job.id is not None
    assert pub_job.status == "queued"
    assert pub_job.privacy_status == "private"

    queue = repo.list_publish_queue(status="queued")
    assert len(queue) == 1
    assert queue[0].clip_id == clip.id

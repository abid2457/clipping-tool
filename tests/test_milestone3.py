"""Tests for Milestone 3: YouTube API Integration, OAuth Crypto & Metadata Generation."""

from app.youtube.crypto import encrypt_token, decrypt_token
from app.youtube import quota
from app.agent.metadata_generator import MetadataGenerator


def test_crypto_token_encryption():
    sample_refresh_token = "1//04test_refresh_token_very_long_secret_1234567890"
    encrypted = encrypt_token(sample_refresh_token)

    assert encrypted != sample_refresh_token
    assert len(encrypted) > 20

    decrypted = decrypt_token(encrypted)
    assert decrypted == sample_refresh_token


def test_quota_tracking():
    initial_consumed = quota.get_consumed_quota()
    initial_remaining = quota.get_remaining_quota()
    assert initial_consumed + initial_remaining == quota.DAILY_QUOTA_LIMIT

    # Record usage
    quota.record_quota_usage(100)
    assert quota.get_consumed_quota() == initial_consumed + 100
    assert quota.get_remaining_quota() == initial_remaining - 100
    assert quota.can_afford_upload() is True


def test_metadata_generator_fallback():
    generator = MetadataGenerator()
    transcript = (
        "Here is the single biggest mistake people make with video editing. "
        "They spend hours adjusting color grades when the story itself lacks a strong hook. "
        "Focus on the first five seconds and you will see your watch time double immediately."
    )

    metadata = generator.generate_metadata(transcript, duration_sec=32.0)
    assert "titles" in metadata
    assert len(metadata["titles"]) >= 3
    assert "description" in metadata
    assert "hashtags" in metadata
    assert any("Shorts" in tag for tag in metadata["hashtags"])


def test_api_v2_quota_and_channels(client):
    res_quota = client.get("/api/v2/youtube/quota")
    assert res_quota.status_code == 200
    data = res_quota.json()
    assert "daily_limit" in data
    assert "remaining" in data

    res_ch = client.get("/api/v2/youtube/channels")
    assert res_ch.status_code == 200
    assert isinstance(res_ch.json(), list)


def test_api_v2_metadata_generate(client):
    res = client.post(
        "/api/v2/metadata/generate",
        json={"transcript": "How to double your productivity in one simple step.", "duration": 20.0},
    )
    assert res.status_code == 200
    body = res.json()
    assert "titles" in body
    assert "description" in body

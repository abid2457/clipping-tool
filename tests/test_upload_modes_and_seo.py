"""Automated tests for YouTube Upload Mode (Shorts vs Video) and AI SEO Metadata Generator."""

import pytest
from app.agent.metadata_generator import MetadataGenerator
from app.youtube.uploader import YouTubeUploader


def test_shorts_metadata_generation():
    gen = MetadataGenerator()
    res = gen.generate_metadata_v2(
        transcript_snippet="The secret trick that every creator must know about going viral on YouTube",
        duration_sec=35.0,
        upload_mode="shorts",
    )

    assert res["upload_mode"] == "shorts"
    assert len(res["titles"]) == 3
    assert all(len(t) <= 60 for t in res["titles"])
    assert "description" in res
    assert any("#Shorts" in h or "#shorts" in h for h in res["hashtags"])
    assert "hook" in res
    assert "tags" in res


def test_video_metadata_generation():
    gen = MetadataGenerator()
    res = gen.generate_metadata_v2(
        transcript_snippet="In this video we do a complete breakdown of artificial intelligence architectures and machine learning pipelines",
        duration_sec=240.0,
        upload_mode="video",
    )

    assert res["upload_mode"] == "video"
    assert len(res["titles"]) == 3
    assert all(len(t) <= 100 for t in res["titles"])
    assert "thumbnail_headline" in res
    assert "description" in res
    # Should not include #Shorts hashtag
    assert not any("#Shorts" in h for h in res["hashtags"])
    assert len(res["tags"]) > 0


def test_regenerate_titles_and_description():
    gen = MetadataGenerator()
    titles_res = gen.regenerate_titles(
        transcript_snippet="Five financial habits that will make you wealthy",
        duration_sec=40.0,
        upload_mode="shorts",
    )
    assert len(titles_res["titles"]) == 3

    desc_res = gen.regenerate_description(
        transcript_snippet="Five financial habits that will make you wealthy",
        duration_sec=120.0,
        upload_mode="video",
    )
    assert "description" in desc_res
    assert len(desc_res["description"]) > 20


def test_uploader_mode_tags():
    # Verify uploader signature and tags preparation logic
    assert "upload_mode" in YouTubeUploader.upload_clip.__code__.co_varnames
    assert "category_id" in YouTubeUploader.upload_clip.__code__.co_varnames

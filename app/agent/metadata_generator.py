"""Automated YouTube metadata generator with Shorts/Video mode support and AI SEO."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from app.intelligence.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompts for each upload mode
# ---------------------------------------------------------------------------

SHORTS_SYSTEM_PROMPT = """You are a top YouTube Shorts SEO growth expert.
Given a video clip transcript, generate high-CTR metadata tailored for YouTube Shorts.

Analyze the transcript for:
- Main topic and subject matter
- Key moments, quotes, or hooks
- Emotional tone (humor, surprise, controversy, inspiration)
- Target audience and niche
- Relevant search keywords

Output ONLY valid JSON matching this schema:
{
  "titles": [
    "<Option 1: Curiosity hook, <= 60 chars>",
    "<Option 2: Direct value / bold claim, <= 60 chars>",
    "<Option 3: Question / mystery, <= 60 chars>"
  ],
  "primary_title": "<Pick the best of the 3>",
  "description": "<Engaging 2-3 sentence description summarizing the clip's best moment + call to action>",
  "hashtags": ["#Shorts", "#<RelevantTag1>", "#<RelevantTag2>", "#<RelevantTag3>", "#<RelevantTag4>"],
  "tags": ["shorts", "<keyword1>", "<keyword2>", "<keyword3>", "<keyword4>", "<keyword5>"],
  "hook": "<A compelling 1-sentence opening hook that makes viewers stop scrolling>"
}

Rules for Shorts titles:
- Must be under 60 characters
- Use power words: Secret, Truth, Why, How, Watch, Never, Always
- Create curiosity gaps
- Avoid misleading clickbait
- Include relevant context from the transcript

Do not include markdown blocks, preamble, or conversational filler."""

VIDEO_SYSTEM_PROMPT = """You are a YouTube SEO specialist for long-form video content.
Given a video transcript, generate search-optimized metadata for a regular YouTube video.

Analyze the transcript for:
- Main topic, theme, and subject matter
- Key talking points and important moments
- Target audience and content category
- Relevant search queries viewers would use
- Competitive keywords in this niche

Output ONLY valid JSON matching this schema:
{
  "titles": [
    "<Option 1: SEO keyword-rich title, <= 100 chars>",
    "<Option 2: Benefit-driven title, <= 100 chars>",
    "<Option 3: Curiosity/story title, <= 100 chars>"
  ],
  "primary_title": "<Pick the best of the 3>",
  "description": "<Detailed 4-6 sentence description: summarize content, mention key topics, include natural keywords, add call to action and timestamps placeholder>",
  "hashtags": ["#<MainTopic>", "#<Niche>", "#<Keyword1>", "#<Keyword2>"],
  "tags": ["<primary keyword>", "<secondary keyword>", "<long-tail phrase 1>", "<long-tail phrase 2>", "<related topic 1>", "<related topic 2>", "<brand/channel>"],
  "thumbnail_headline": "<Bold 3-5 word headline for a YouTube thumbnail>"
}

Rules for Video titles:
- Must be under 100 characters
- Front-load primary keyword
- Provide clear value proposition
- Avoid excessive caps or clickbait
- Be accurate to the content
- Do NOT include #Shorts

Do not include markdown blocks, preamble, or conversational filler."""

TITLES_ONLY_SHORTS_PROMPT = """You are a YouTube Shorts title specialist.
Given a transcript, generate 3 fresh catchy title options for YouTube Shorts.
Each must be <= 60 characters, attention-grabbing, and accurate to the content.
Output ONLY valid JSON: {"titles": ["<title1>", "<title2>", "<title3>"]}"""

TITLES_ONLY_VIDEO_PROMPT = """You are a YouTube SEO title specialist.
Given a transcript, generate 3 fresh SEO-optimized title options for a regular YouTube video.
Each must be <= 100 characters, keyword-rich, and accurate to the content.
Output ONLY valid JSON: {"titles": ["<title1>", "<title2>", "<title3>"]}"""

DESC_ONLY_SHORTS_PROMPT = """You are a YouTube Shorts description writer.
Given a transcript, write an engaging 2-3 sentence description for a YouTube Short.
Include a call to action and relevant context.
Output ONLY valid JSON: {"description": "<description text>"}"""

DESC_ONLY_VIDEO_PROMPT = """You are a YouTube video description writer.
Given a transcript, write a detailed 4-6 sentence description for a YouTube video.
Include content summary, key topics, natural keywords, and a call to action.
Output ONLY valid JSON: {"description": "<description text>"}"""


class MetadataGenerator:
    """Generates viral YouTube metadata via local LLM with rule-based fallback."""

    def __init__(self, ollama_client: Optional[OllamaClient] = None) -> None:
        self.ollama = ollama_client or OllamaClient()

    # -------------------------------------------------------------------
    # Legacy method — backward compatible
    # -------------------------------------------------------------------
    def generate_metadata(self, transcript_snippet: str, duration_sec: float) -> Dict[str, Any]:
        """Generate title variants, description, and hashtags (Shorts only, legacy)."""
        return self.generate_metadata_v2(transcript_snippet, duration_sec, upload_mode="shorts")

    # -------------------------------------------------------------------
    # V2 — Mode-aware metadata generation
    # -------------------------------------------------------------------
    def generate_metadata_v2(
        self,
        transcript_snippet: str,
        duration_sec: float,
        upload_mode: str = "shorts",
        language: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate mode-aware YouTube metadata with AI or heuristic fallback."""
        clean_text = transcript_snippet.strip()[:2000]
        is_shorts = upload_mode.lower() == "shorts"
        system_prompt = SHORTS_SYSTEM_PROMPT if is_shorts else VIDEO_SYSTEM_PROMPT

        if self.ollama.is_available():
            try:
                extra_context = ""
                if language:
                    extra_context += f"\nVideo Language: {language}"
                if topic:
                    extra_context += f"\nMain Topic: {topic}"

                prompt = (
                    f"Upload Mode: {'YouTube Shorts' if is_shorts else 'YouTube Video'}\n"
                    f"Clip Duration: {duration_sec:.1f} seconds{extra_context}\n\n"
                    f"Clip Transcript:\n\"\"\"\n{clean_text}\n\"\"\"\n\n"
                    f"Generate optimized {'YouTube Shorts' if is_shorts else 'YouTube Video'} metadata JSON."
                )
                result = self.ollama.generate_json(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    timeout=45.0,
                )
                if result and "titles" in result:
                    result["upload_mode"] = upload_mode
                    return result
            except Exception as e:
                logger.warning("Ollama metadata generation failed: %s. Using heuristic fallback.", e)

        return self._fallback_metadata_v2(clean_text, duration_sec, upload_mode)

    # -------------------------------------------------------------------
    # Regenerate individual fields
    # -------------------------------------------------------------------
    def regenerate_titles(
        self, transcript_snippet: str, duration_sec: float, upload_mode: str = "shorts"
    ) -> Dict[str, Any]:
        """Regenerate only titles."""
        clean_text = transcript_snippet.strip()[:1500]
        is_shorts = upload_mode.lower() == "shorts"
        system_prompt = TITLES_ONLY_SHORTS_PROMPT if is_shorts else TITLES_ONLY_VIDEO_PROMPT

        if self.ollama.is_available():
            try:
                prompt = (
                    f"Duration: {duration_sec:.1f}s\n\n"
                    f"Transcript:\n\"\"\"\n{clean_text}\n\"\"\"\n\n"
                    "Generate 3 fresh title options."
                )
                result = self.ollama.generate_json(prompt=prompt, system_prompt=system_prompt, timeout=30.0)
                if result and "titles" in result:
                    return result
            except Exception as e:
                logger.warning("Ollama title regen failed: %s", e)

        fb = self._fallback_metadata_v2(clean_text, duration_sec, upload_mode)
        return {"titles": fb["titles"]}

    def regenerate_description(
        self, transcript_snippet: str, duration_sec: float, upload_mode: str = "shorts"
    ) -> Dict[str, Any]:
        """Regenerate only description."""
        clean_text = transcript_snippet.strip()[:1500]
        is_shorts = upload_mode.lower() == "shorts"
        system_prompt = DESC_ONLY_SHORTS_PROMPT if is_shorts else DESC_ONLY_VIDEO_PROMPT

        if self.ollama.is_available():
            try:
                prompt = (
                    f"Duration: {duration_sec:.1f}s\n\n"
                    f"Transcript:\n\"\"\"\n{clean_text}\n\"\"\"\n\n"
                    "Generate optimized description."
                )
                result = self.ollama.generate_json(prompt=prompt, system_prompt=system_prompt, timeout=30.0)
                if result and "description" in result:
                    return result
            except Exception as e:
                logger.warning("Ollama description regen failed: %s", e)

        fb = self._fallback_metadata_v2(clean_text, duration_sec, upload_mode)
        return {"description": fb["description"]}

    # -------------------------------------------------------------------
    # Heuristic fallback — works without Ollama
    # -------------------------------------------------------------------
    def _fallback_metadata_v2(self, text: str, duration_sec: float, upload_mode: str) -> Dict[str, Any]:
        """Deterministic rule-based metadata generator for both modes."""
        words = text.split()
        first_words = " ".join(words[:8]).capitalize()
        first_words = re.sub(r'[^\w\s\'-]', '', first_words).strip()
        is_shorts = upload_mode.lower() == "shorts"

        # Extract potential keywords from text
        word_freq: Dict[str, int] = {}
        stop_words = {"the", "a", "an", "is", "it", "in", "on", "at", "to", "and", "or", "but", "i", "you",
                       "he", "she", "we", "they", "this", "that", "was", "are", "be", "have", "has", "do",
                       "did", "will", "would", "can", "could", "not", "so", "if", "my", "me", "your", "of",
                       "for", "with", "just", "like", "its", "what", "how", "why", "when", "where", "no",
                       "yes", "oh", "um", "uh", "yeah", "okay", "ok", "right", "well", "got", "get",
                       "going", "gonna", "want", "think", "know", "say", "said", "go", "come", "make"}
        for w in words:
            clean_w = re.sub(r'[^\w]', '', w.lower())
            if len(clean_w) > 3 and clean_w not in stop_words:
                word_freq[clean_w] = word_freq.get(clean_w, 0) + 1
        top_keywords = sorted(word_freq, key=word_freq.get, reverse=True)[:6]

        if is_shorts:
            title_1 = f"Wait For It... {first_words}"[:60]
            title_2 = f"Nobody Talks About This"[:60]
            title_3 = f"The Truth About {' '.join(top_keywords[:3]).title()}"[:60]

            description = (
                f"{first_words}... You need to hear this!\n\n"
                f"{text[:200]}...\n\n"
                "🔔 Subscribe for daily content!\n\n"
                "#Shorts #Trending #Viral"
            )

            hashtags = ["#Shorts", "#Trending", "#Viral"]
            for kw in top_keywords[:3]:
                hashtags.append(f"#{kw.capitalize()}")

            tags = ["shorts", "viral", "trending"] + top_keywords[:5]
            hook = f"You won't believe what happens when {' '.join(words[:5]).lower()}..."

            return {
                "titles": [title_1, title_2, title_3],
                "primary_title": title_1,
                "description": description,
                "hashtags": hashtags,
                "tags": tags,
                "hook": hook,
                "upload_mode": "shorts",
            }
        else:
            topic_phrase = " ".join(top_keywords[:3]).title() if top_keywords else "This Topic"
            title_1 = f"{topic_phrase} - Everything You Need To Know"[:100]
            title_2 = f"How {first_words} Changes Everything"[:100]
            title_3 = f"The Complete Guide to {topic_phrase}"[:100]

            description = (
                f"In this video, we explore {topic_phrase.lower()} and break down "
                f"the key insights you need to know.\n\n"
                f"Key topics covered:\n"
                f"• {first_words}\n"
                f"• {' '.join(words[8:16]).capitalize() if len(words) > 16 else 'More insights'}\n\n"
                f"{text[:300]}...\n\n"
                "⏱️ Timestamps:\n"
                "0:00 - Introduction\n\n"
                "👍 Like & Subscribe for more content!\n\n"
                + " ".join(f"#{kw.capitalize()}" for kw in top_keywords[:4])
            )

            hashtags = [f"#{kw.capitalize()}" for kw in top_keywords[:5]]
            tags = top_keywords[:7] + ["guide", "explained", "breakdown"]
            thumbnail = f"{' '.join(top_keywords[:2]).upper()} EXPLAINED" if top_keywords else "MUST WATCH"

            return {
                "titles": [title_1, title_2, title_3],
                "primary_title": title_1,
                "description": description,
                "hashtags": hashtags,
                "tags": tags,
                "thumbnail_headline": thumbnail,
                "upload_mode": "video",
            }

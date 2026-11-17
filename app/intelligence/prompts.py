"""Structured prompts and schema definitions for local LLM inference."""

from __future__ import annotations

import json
from typing import Dict, Any


VIRALITY_SYSTEM_PROMPT = """You are an elite short-form video editor and viral content strategist.
Your task is to analyze candidate video transcript segments for YouTube Shorts, Instagram Reels, and TikTok.

Score each transcript window on 5 key pillars using a 1-10 integer scale:
1. hook_score (1-10): Opening 3-5 seconds impact. Does it immediately grab attention and stop the scroll?
2. coherence_score (1-10): Can a viewer fully understand this clip without watching the rest of the video?
3. emotion_score (1-10): Does it evoke curiosity, surprise, humor, controversy, inspiration, or strong opinion?
4. virality_score (1-10): How shareable is this? Will viewers comment, save, or argue about it?
5. payoff_score (1-10): Does it deliver on the premise or finish with a punchy conclusion?

Output ONLY valid JSON matching this schema:
{
  "hook_score": <1-10 integer>,
  "coherence_score": <1-10 integer>,
  "emotion_score": <1-10 integer>,
  "virality_score": <1-10 integer>,
  "payoff_score": <1-10 integer>,
  "title": "<Catchy hook title <= 8 words, capitalize first letters>",
  "virality_reason": "<One sentence explaining why this clip will engage viewers>"
}
Do not write explanations, markdown code blocks, or conversational filler."""


def format_virality_prompt(transcript_snippet: str, duration_sec: float) -> str:
    """Format virality evaluation prompt for a single transcript candidate window."""
    return (
        f"Candidate Clip Duration: {duration_sec:.1f} seconds\n\n"
        f"Transcript Content:\n\"\"\"\n{transcript_snippet.strip()}\n\"\"\"\n\n"
        "Evaluate this clip according to the 5 virality pillars and respond with ONLY the required JSON object."
    )


def compute_composite_virality_score(scores: Dict[str, Any]) -> float:
    """Calculate weighted composite score from 0.0 to 10.0.

    Weights:
    - 30% Hook Strength (immediate retention)
    - 20% Standalone Coherence (context completeness)
    - 20% Emotional Energy (viewer sentiment)
    - 20% Virality & Shareability (algorithmic boost)
    - 10% Payoff / Punchline (satisfaction)
    """
    hook = float(scores.get("hook_score", 5))
    coherence = float(scores.get("coherence_score", 5))
    emotion = float(scores.get("emotion_score", 5))
    virality = float(scores.get("virality_score", 5))
    payoff = float(scores.get("payoff_score", 5))

    weighted = (
        hook * 0.30 +
        coherence * 0.20 +
        emotion * 0.20 +
        virality * 0.20 +
        payoff * 0.10
    )
    return round(max(0.0, min(10.0, weighted)), 2)

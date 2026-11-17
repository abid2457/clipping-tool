"""Smart Clip Selector combining rule-based heuristics and local LLM virality analysis."""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Any
from app.intelligence.ollama_client import OllamaClient
from app.intelligence.prompts import (
    VIRALITY_SYSTEM_PROMPT,
    format_virality_prompt,
    compute_composite_virality_score,
)
from app.selector import (
    _build_candidate_windows,
    _fallback_even_split,
    _derive_title,
    _overlaps,
    IDEAL_CLIP_LEN,
    MAX_CLIP_LEN,
)

logger = logging.getLogger(__name__)


class SmartSelector:
    """Intelligent clip selector with multi-pillar evaluation and graceful fallback."""

    def __init__(self, ollama_client: Optional[OllamaClient] = None) -> None:
        self.ollama = ollama_client or OllamaClient()

    def select_clips(
        self,
        transcript: Dict[str, Any],
        num_clips: int,
        clip_length: Optional[float] = None,
        use_ai: bool = True,
    ) -> List[Dict[str, Any]]:
        """Select the highest-potential non-overlapping clips from a transcript."""
        segments = transcript.get("segments") or []
        if not segments:
            return _fallback_even_split(transcript, num_clips, clip_length)

        duration = float(transcript.get("duration") or (segments[-1].get("end") or 0.0))

        # 1. Build candidate windows
        if clip_length and clip_length > 0:
            candidates = _build_candidate_windows(segments, float(clip_length), exact_len=float(clip_length))
        else:
            target = (duration / num_clips) if (num_clips and duration) else IDEAL_CLIP_LEN
            target = max(15.0, min(MAX_CLIP_LEN, target * 0.85))
            candidates = _build_candidate_windows(segments, target)

        if not candidates:
            return _fallback_even_split(transcript, num_clips, clip_length)

        # 2. Check if local AI virality evaluation is requested and available
        ollama_active = (
            use_ai and
            (os.environ.get("USE_OLLAMA", "1") == "1") and
            self.ollama.is_available()
        )

        if ollama_active:
            try:
                selected = self._score_with_ollama(candidates, num_clips)
                if selected:
                    logger.info("Ollama AI virality engine selected %d high-potential clips.", len(selected))
                    return selected
            except Exception as e:
                logger.warning("Local Ollama scoring encountered error, falling back to heuristics: %s", e)

        # 3. Fallback to heuristic selection
        return self._score_heuristic(candidates, num_clips)

    def _score_with_ollama(self, candidates: List[Dict[str, Any]], num_clips: int) -> List[Dict[str, Any]]:
        """Evaluate top candidates with local LLM 5-pillar scoring."""
        # Pre-rank by heuristic to select the best candidates for LLM review (caps local inference latency)
        pre_ranked = sorted(candidates, key=lambda c: c.get("score", 0.0), reverse=True)[: num_clips * 3]

        scored_candidates: List[Dict[str, Any]] = []
        for cand in pre_ranked:
            text = cand.get("text", "")
            duration = cand["end"] - cand["start"]
            prompt = format_virality_prompt(text, duration)

            json_resp = self.ollama.generate_json(
                prompt=prompt,
                system_prompt=VIRALITY_SYSTEM_PROMPT,
                timeout=30.0,
            )

            if json_resp and isinstance(json_resp, dict):
                composite_score = compute_composite_virality_score(json_resp)
                suggested_title = json_resp.get("title") or _derive_title(text)
                virality_reason = json_resp.get("virality_reason", "")
            else:
                composite_score = float(cand.get("score", 5.0)) / 10.0  # Normalized
                suggested_title = _derive_title(text)
                virality_reason = "Selected based on high speech density and keyword hook analysis."

            scored_candidates.append({
                "start": cand["start"],
                "end": cand["end"],
                "score": round(composite_score, 2),
                "title": _derive_title(suggested_title),
                "text": text,
                "metadata": {
                    "virality_score": composite_score,
                    "reason": virality_reason,
                    "pillar_breakdown": json_resp if json_resp else {},
                },
            })

        # Sort by virality score descending
        scored_candidates.sort(key=lambda c: c["score"], reverse=True)

        # Greedy non-overlapping selection
        chosen: List[Dict[str, Any]] = []
        for cand in scored_candidates:
            if len(chosen) >= num_clips:
                break
            if any(_overlaps(cand, c) for c in chosen):
                continue
            chosen.append(cand)

        # Return chronologically sorted
        chosen.sort(key=lambda c: c["start"])
        return chosen

    def _score_heuristic(self, candidates: List[Dict[str, Any]], num_clips: int) -> List[Dict[str, Any]]:
        """Pure heuristic selection based on word density, hook words, and cadence."""
        ranked = sorted(candidates, key=lambda c: c.get("score", 0.0), reverse=True)

        chosen: List[Dict[str, Any]] = []
        for cand in ranked:
            if len(chosen) >= num_clips:
                break
            if any(_overlaps(cand, c) for c in chosen):
                continue
            chosen.append({
                "start": cand["start"],
                "end": cand["end"],
                "title": _derive_title(cand.get("text", "")),
                "score": round(float(cand.get("score", 50.0)) / 10.0, 2),
                "text": cand.get("text", ""),
                "metadata": {
                    "source": "heuristic",
                    "reason": "High keyword hook score and sentence boundary integrity.",
                },
            })

        chosen.sort(key=lambda c: c["start"])
        return chosen

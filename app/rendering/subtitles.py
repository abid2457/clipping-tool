"""Multi-format subtitle formatter (SRT, VTT, ASS, TXT) for clip export."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional


def _format_time_srt(seconds: float) -> str:
    """Format seconds into SRT timestamp HH:MM:SS,mmm."""
    seconds = max(0.0, float(seconds))
    td = datetime.timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        millis = 999
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _format_time_vtt(seconds: float) -> str:
    """Format seconds into WebVTT timestamp HH:MM:SS.mmm."""
    seconds = max(0.0, float(seconds))
    td = datetime.timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        millis = 999
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def _group_words_into_lines(words: List[Dict[str, Any]], max_words_per_line: int = 5) -> List[Dict[str, Any]]:
    """Group fine-grained word timestamps into legible 3-6 word subtitle lines."""
    if not words:
        return []

    lines: List[Dict[str, Any]] = []
    current_line: List[Dict[str, Any]] = []

    for w in words:
        current_line.append(w)
        text = w.get("word", "").strip()
        # End line on punctuation or when max words reached
        if len(current_line) >= max_words_per_line or any(text.endswith(p) for p in (".", "!", "?", "।", "…")):
            start = current_line[0]["start"]
            end = current_line[-1]["end"]
            combined = " ".join(item.get("word", "").strip() for item in current_line)
            lines.append({"start": start, "end": end, "text": combined})
            current_line = []

    if current_line:
        start = current_line[0]["start"]
        end = current_line[-1]["end"]
        combined = " ".join(item.get("word", "").strip() for item in current_line)
        lines.append({"start": start, "end": end, "text": combined})

    return lines


def format_srt(words: List[Dict[str, Any]], start_offset: float = 0.0) -> str:
    """Format words into standard SubRip (.srt) subtitle string."""
    lines = _group_words_into_lines(words)
    output: List[str] = []

    for idx, line in enumerate(lines, start=1):
        rel_start = max(0.0, line["start"] - start_offset)
        rel_end = max(rel_start + 0.1, line["end"] - start_offset)
        output.append(str(idx))
        output.append(f"{_format_time_srt(rel_start)} --> {_format_time_srt(rel_end)}")
        output.append(line["text"])
        output.append("")

    return "\n".join(output)


def format_vtt(words: List[Dict[str, Any]], start_offset: float = 0.0) -> str:
    """Format words into WebVTT (.vtt) subtitle string."""
    lines = _group_words_into_lines(words)
    output: List[str] = ["WEBVTT", ""]

    for idx, line in enumerate(lines, start=1):
        rel_start = max(0.0, line["start"] - start_offset)
        rel_end = max(rel_start + 0.1, line["end"] - start_offset)
        output.append(str(idx))
        output.append(f"{_format_time_vtt(rel_start)} --> {_format_time_vtt(rel_end)}")
        output.append(line["text"])
        output.append("")

    return "\n".join(output)


def format_txt(words: List[Dict[str, Any]]) -> str:
    """Format words into readable plain text."""
    lines = _group_words_into_lines(words, max_words_per_line=12)
    return "\n".join(l["text"] for l in lines)

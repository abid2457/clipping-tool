"""Resilient local Ollama client for local LLM inference."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "llama3")

# Cache availability for 15 seconds to prevent spamming localhost on every check
_AVAILABILITY_CACHE: Dict[str, Any] = {"available": None, "checked_at": 0.0}


class OllamaClient:
    """Zero-cloud client for local Ollama instance."""

    def __init__(self, base_url: str = DEFAULT_OLLAMA_URL, default_model: str = DEFAULT_MODEL) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model

    def is_available(self, force_refresh: bool = False) -> bool:
        """Return True if local Ollama daemon is reachable."""
        now = time.time()
        if not force_refresh and _AVAILABILITY_CACHE["available"] is not None:
            if now - _AVAILABILITY_CACHE["checked_at"] < 15.0:
                return _AVAILABILITY_CACHE["available"]

        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=1.5)
            status = resp.status_code == 200
        except Exception:
            status = False

        _AVAILABILITY_CACHE["available"] = status
        _AVAILABILITY_CACHE["checked_at"] = now
        return status

    def list_models(self) -> List[str]:
        """List local installed model tags."""
        if not self.is_available():
            return []
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=2.0)
            if resp.status_code == 200:
                data = resp.json()
                return [m.get("name") for m in data.get("models", []) if m.get("name")]
        except Exception as e:
            logger.debug("Failed to list Ollama models: %s", e)
        return []

    def select_best_model(self) -> str:
        """Pick default_model if available, else first installed model, else default."""
        models = self.list_models()
        if not models:
            return self.default_model

        for m in models:
            if self.default_model in m:
                return m

        # Fallback priority: llama3 > mistral > qwen > phi3 > first available
        for preferred in ("llama3", "mistral", "qwen", "phi3", "gemma"):
            for m in models:
                if preferred in m.lower():
                    return m

        return models[0]

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 45.0,
    ) -> Optional[str]:
        """Execute a text generation call against local Ollama."""
        if not self.is_available():
            return None

        chosen_model = model or self.select_best_model()
        payload: Dict[str, Any] = {
            "model": chosen_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "top_p": 0.9},
        }
        if system_prompt:
            payload["system"] = system_prompt

        try:
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=timeout,
            )
            if resp.status_code == 200:
                return resp.json().get("response", "").strip()
        except Exception as e:
            logger.warning("Ollama generation call failed: %s", e)

        return None

    def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 45.0,
    ) -> Optional[Dict[str, Any]]:
        """Generate response and parse cleanly into structured JSON dictionary."""
        raw_text = self.generate(prompt, system_prompt=system_prompt, model=model, timeout=timeout)
        if not raw_text:
            return None

        # Clean markdown wrappers (```json ... ```)
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)

        # Regex search for outermost JSON object {...}
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        try:
            return json.loads(cleaned)
        except Exception as e:
            logger.debug("Failed parsing JSON from Ollama response: %s (Raw: %s)", e, raw_text[:200])

        return None

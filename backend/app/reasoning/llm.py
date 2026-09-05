"""A minimal client for a local Ollama server.

Written against Ollama's HTTP API directly rather than through a wrapper: the
surface used here is two endpoints, and a dependency that abstracts two
endpoints is a dependency that will break the build one day for nothing.

Every failure mode - server down, model missing, timeout, garbage output - is a
normal outcome, not an exception to propagate. The agent must keep trading with
its rules when the model is unavailable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

REQUEST_TIMEOUT_SECONDS = 45.0
HEALTH_TIMEOUT_SECONDS = 3.0


@dataclass
class Completion:
    ok: bool
    text: str = ""
    error: str | None = None
    duration_ms: int = 0
    model: str = ""


class LLMClient:
    """Talks to Ollama. Never raises for an operational failure."""

    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.model = model or settings.llm_model

    async def available(self) -> bool:
        """Is the server up and does it have the model we need?"""
        try:
            async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT_SECONDS) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                names = {m.get("name", "") for m in response.json().get("models", [])}
        except Exception as exc:
            log.info("llm_unavailable", error=type(exc).__name__)
            return False
        # Ollama reports "llama3.2:1b"; accept a bare family name too.
        return any(n == self.model or n.split(":")[0] == self.model.split(":")[0]
                   for n in names)

    async def complete(self, prompt: str, *, system: str = "",
                       temperature: float = 0.1) -> Completion:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "format": "json",
            "options": {"temperature": temperature, "num_predict": 400},
        }
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.post(f"{self.base_url}/api/generate", json=payload)
                response.raise_for_status()
                body = response.json()
        except Exception as exc:
            return Completion(ok=False, error=f"{type(exc).__name__}: {exc}",
                              model=self.model)

        return Completion(
            ok=True,
            text=body.get("response", ""),
            duration_ms=int(body.get("total_duration", 0) / 1_000_000),
            model=self.model,
        )


def extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of a model response.

    Models wrap JSON in fences, prefix it with commentary, or append an
    explanation however firmly they were told not to. Salvaging the object is
    cheaper than a retry, and returning None is always an acceptable answer.
    """
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        text = text.removeprefix("json").strip()

    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, char in enumerate(text[start:], start=start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


__all__ = ["Completion", "LLMClient", "extract_json"]

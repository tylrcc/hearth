"""Tiny, dependency-free client for a local Ollama server.

Everything here talks to ``http://localhost:11434`` (or ``$OLLAMA_HOST``) using
only the standard library, so hearth never reaches the public internet.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_CHAT_MODEL = os.environ.get("HEARTH_CHAT_MODEL", "qwen3.5:9b")
DEFAULT_EMBED_MODEL = os.environ.get("HEARTH_EMBED_MODEL", "nomic-embed-text")

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class OllamaError(RuntimeError):
    """Raised when the local Ollama server is unreachable or returns an error."""


@dataclass
class Ollama:
    host: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    timeout: float = 120.0

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.host.rstrip('/')}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:  # connection refused, DNS, timeout
            raise OllamaError(
                f"Could not reach Ollama at {self.host}. "
                "Is it running? Start it with `ollama serve`."
            ) from exc

    def is_up(self) -> bool:
        try:
            url = f"{self.host.rstrip('/')}/api/tags"
            with urllib.request.urlopen(url, timeout=5):
                return True
        except urllib.error.URLError:
            return False

    def models(self) -> list[str]:
        url = f"{self.host.rstrip('/')}/api/tags"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise OllamaError(f"Could not reach Ollama at {self.host}.") from exc
        return [m["name"] for m in body.get("models", [])]

    def generate(
        self,
        prompt: str,
        *,
        model: str = DEFAULT_CHAT_MODEL,
        system: str | None = None,
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> str:
        """Return a single completion. Thinking traces are stripped out."""
        payload: dict = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"
        body = self._post("/api/generate", payload)
        return _THINK_RE.sub("", body.get("response", "")).strip()

    def embed(
        self, texts: list[str], *, model: str = DEFAULT_EMBED_MODEL
    ) -> list[list[float]]:
        """Return one embedding vector per input string."""
        if not texts:
            return []
        body = self._post("/api/embed", {"model": model, "input": texts})
        vectors = body.get("embeddings")
        if not vectors:  # older servers expose /api/embeddings (singular)
            vectors = [
                self._post("/api/embeddings", {"model": model, "prompt": t})[
                    "embedding"
                ]
                for t in texts
            ]
        return vectors

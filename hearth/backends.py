"""Pluggable local-inference backends.

hearth speaks to whatever local runtime you already have:

* **Ollama** — its native API (the default).
* **llama.cpp** (``llama-server``), **MLX** (``mlx_lm.server``), **LM Studio**,
  **vLLM**, and anything else exposing an **OpenAI-compatible** ``/v1`` API.

Both backends present the same tiny surface — ``is_up``, ``models``,
``generate``, ``embed`` — so the rest of hearth never cares which one is in use.
Everything still targets a local host; no traffic leaves your machine.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .ollama import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_EMBED_MODEL,
    Ollama,
    OllamaError,
    _THINK_RE,
)

# A shared alias: backend-agnostic code can catch this name.
BackendError = OllamaError

# OpenAI-compatible servers people run locally and their usual base URLs.
OPENAI_COMPAT_ALIASES = {
    "llamacpp": ("llama.cpp", "http://localhost:8080/v1"),
    "llama.cpp": ("llama.cpp", "http://localhost:8080/v1"),
    "llama-cpp": ("llama.cpp", "http://localhost:8080/v1"),
    "mlx": ("MLX", "http://localhost:8080/v1"),
    "lmstudio": ("LM Studio", "http://localhost:1234/v1"),
    "vllm": ("vLLM", "http://localhost:8000/v1"),
    "openai": ("OpenAI-compatible", "http://localhost:8080/v1"),
    "openai-compat": ("OpenAI-compatible", "http://localhost:8080/v1"),
}


@dataclass
class OpenAICompatBackend:
    """Talks to any server implementing the OpenAI ``/v1`` chat + embeddings API."""

    base_url: str = "http://localhost:8080/v1"
    kind: str = "openai"
    label: str = "OpenAI-compatible"
    api_key: str = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", "-"))
    # Generous: local reasoning models can take minutes over the /v1 API, since
    # (unlike Ollama's native API) there is no way to switch thinking off.
    timeout: float = 300.0

    @property
    def endpoint(self) -> str:
        return self.base_url

    @property
    def start_hint(self) -> str:
        return (f"Start your {self.label} server (expected at {self.base_url}). "
                "e.g. `llama-server -m model.gguf --port 8080` or "
                "`mlx_lm.server --port 8080`.")

    def _request(self, path: str, payload: dict | None, timeout: float) -> dict:
        url = f"{self.base_url.rstrip('/')}{path}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if payload is None:
            req = urllib.request.Request(url, headers=headers)  # GET
        else:
            headers["Content-Type"] = "application/json"
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode("utf-8"), headers=headers
            )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")[:300]
            raise BackendError(f"{self.label} server returned {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise BackendError(
                f"Could not reach {self.label} at {self.base_url}. {self.start_hint}"
            ) from exc

    def is_up(self) -> bool:
        try:
            self._request("/models", None, timeout=5)
            return True
        except BackendError:
            return False

    def models(self) -> list[str]:
        body = self._request("/models", None, timeout=5)
        return [m.get("id", "?") for m in body.get("data", [])]

    def generate(self, prompt: str, *, model: str = DEFAULT_CHAT_MODEL,
                 system: str | None = None, temperature: float = 0.0,
                 json_mode: bool = False) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
            # Generous ceiling: normal models stop early; reasoning models
            # (which can't be told `think:false` over the OpenAI API) need room
            # to finish thinking before emitting their answer.
            "max_tokens": 4096,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        body = self._request("/chat/completions", payload, self.timeout)
        return parse_chat_content(body)

    def embed(self, texts: list[str], *, model: str = DEFAULT_EMBED_MODEL) -> list[list[float]]:
        if not texts:
            return []
        body = self._request("/embeddings", {"model": model, "input": texts}, self.timeout)
        return parse_embeddings(body)


# Pure parsers (unit-tested without a server) -------------------------------- #
def parse_chat_content(body: dict) -> str:
    choices = body.get("choices") or []
    if not choices:
        raise BackendError("server returned no choices")
    content = (choices[0].get("message") or {}).get("content", "") or ""
    return _THINK_RE.sub("", content).strip()


def parse_embeddings(body: dict) -> list[list[float]]:
    data = body.get("data") or []
    # Preserve request order if the server provides an index.
    ordered = sorted(data, key=lambda d: d.get("index", 0))
    return [d["embedding"] for d in ordered]


# Factory -------------------------------------------------------------------- #
def get_backend(name: str | None = None, base_url: str | None = None):
    """Return a backend by name. Falls back to ``$HEARTH_BACKEND`` then Ollama."""
    name = (name or os.environ.get("HEARTH_BACKEND") or "ollama").strip().lower()
    if name in ("ollama", ""):
        host = base_url or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        return Ollama(host=host)
    if name in OPENAI_COMPAT_ALIASES:
        label, default_url = OPENAI_COMPAT_ALIASES[name]
        url = base_url or os.environ.get("HEARTH_BASE_URL") or default_url
        return OpenAICompatBackend(base_url=url, kind=name, label=label)
    raise BackendError(
        f"Unknown backend '{name}'. Choose: ollama, llamacpp, mlx, lmstudio, "
        "vllm, or openai (with --url)."
    )


BACKEND_CHOICES = ["ollama", "llamacpp", "mlx", "lmstudio", "vllm", "openai"]

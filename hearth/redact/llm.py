"""Optional local-LLM pass that catches PII regex cannot: names, street
addresses, organisations, and other free-text identifiers.

The model is asked to return verbatim substrings; we then locate those
substrings in the source text ourselves. We never trust character offsets from
the model, which keeps redaction reliable even with small models.
"""

from __future__ import annotations

import json

from ..ollama import Ollama, OllamaError
from .detectors import Match

_SYSTEM = (
    "You are a strict PII scanner. You will be given text. Return ONLY personal "
    "identifiers that appear verbatim in it: full person names, street "
    "addresses, and organisation names. Do not return emails, IPs, numbers, or "
    "secrets (those are handled elsewhere). Respond with a JSON object of the "
    'form {"items": [{"text": "<verbatim substring>", "label": "NAME|ADDRESS|ORG"}]}. '
    "If there is no such PII, return {\"items\": []}. Output JSON only."
)


def llm_detect(text: str, *, model: str, client: Ollama | None = None) -> list[Match]:
    client = client or Ollama()
    try:
        raw = client.generate(
            text, model=model, system=_SYSTEM, json_mode=True, temperature=0.0
        )
    except OllamaError:
        raise
    try:
        items = json.loads(raw).get("items", [])
    except (json.JSONDecodeError, AttributeError):
        return []

    matches: list[Match] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        needle = (item.get("text") or "").strip()
        label = (item.get("label") or "PII").strip().upper()
        if len(needle) < 2:
            continue
        start = 0
        while True:  # redact every occurrence the model flagged
            idx = text.find(needle, start)
            if idx == -1:
                break
            matches.append(Match(idx, idx + len(needle), label, needle))
            start = idx + len(needle)
    return matches

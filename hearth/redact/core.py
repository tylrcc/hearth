"""Redaction orchestration: detect spans, swap them for stable placeholders,
and keep a reversible map so model replies can be un-redacted later.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field

from ..ollama import Ollama
from .detectors import Match, detect
from .llm import llm_detect


@dataclass
class RedactionResult:
    text: str
    # placeholder -> original value, e.g. {"<EMAIL_1>": "a@b.com"}
    mapping: dict[str, str] = field(default_factory=dict)
    # label -> count, e.g. {"EMAIL": 2}
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def _merge(spans: list[Match]) -> list[Match]:
    """Resolve overlaps across regex + LLM spans (leftmost-longest wins)."""
    spans = sorted(spans, key=lambda m: (m.start, -(m.end - m.start)))
    out: list[Match] = []
    occupied_until = -1
    for m in spans:
        if m.start >= occupied_until:
            out.append(m)
            occupied_until = m.end
    return out


def redact(
    text: str,
    *,
    use_llm: bool = False,
    model: str | None = None,
    client: Ollama | None = None,
    only: set[str] | None = None,
) -> RedactionResult:
    """Return ``text`` with secrets/PII replaced by ``<LABEL_N>`` placeholders."""
    spans = detect(text, only=only)
    if use_llm:
        client = client or Ollama()
        spans = _merge(spans + llm_detect(text, model=model, client=client))
    else:
        spans = _merge(spans)

    # Assign stable, deduplicated placeholders. Identical values reuse one token.
    value_to_token: dict[tuple[str, str], str] = {}
    per_label: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    mapping: dict[str, str] = {}

    # Walk left-to-right so token numbering matches reading order.
    for m in sorted(spans, key=lambda s: s.start):
        key = (m.label, m.text)
        if key not in value_to_token:
            per_label[m.label] += 1
            token = f"<{m.label}_{per_label[m.label]}>"
            value_to_token[key] = token
            mapping[token] = m.text
        counts[m.label] += 1

    # Rebuild the string with replacements (right-to-left preserves offsets).
    chars = list(text)
    for m in sorted(spans, key=lambda s: s.start, reverse=True):
        token = value_to_token[(m.label, m.text)]
        chars[m.start : m.end] = token
    return RedactionResult("".join(chars), dict(mapping), dict(counts))


def restore(text: str, mapping: dict[str, str]) -> str:
    """Inverse of :func:`redact` — swap placeholders back to originals."""
    # Replace longer tokens first so e.g. <EMAIL_10> isn't clobbered by <EMAIL_1>.
    for token in sorted(mapping, key=len, reverse=True):
        text = text.replace(token, mapping[token])
    return text


def save_map(path: str, mapping: dict[str, str]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(mapping, fh, indent=2, ensure_ascii=False)


def load_map(path: str) -> dict[str, str]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)

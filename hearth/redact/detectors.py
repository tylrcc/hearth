"""High-precision regex detectors for secrets and PII.

Each detector yields ``Match`` spans. Order matters: the engine resolves
overlaps by preferring earlier, longer matches, so the most specific patterns
(provider API keys) are listed before the generic ones (high-entropy tokens).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(frozen=True)
class Match:
    start: int
    end: int
    label: str  # e.g. "EMAIL", "AWS_KEY"
    text: str


@dataclass(frozen=True)
class Detector:
    label: str
    pattern: re.Pattern
    validate: Callable[[str], bool] | None = None

    def find(self, text: str) -> Iterable[Match]:
        for m in self.pattern.finditer(text):
            value = m.group(0)
            if self.validate and not self.validate(value):
                continue
            yield Match(m.start(), m.end(), self.label, value)


def _luhn_ok(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    if len(digits) < 13:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


# Ordered most-specific -> least-specific.
DETECTORS: list[Detector] = [
    Detector("PRIVATE_KEY", re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----.*?"
        r"-----END (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----",
        re.DOTALL,
    )),
    Detector("AWS_KEY", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    Detector("GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b")),
    Detector("SLACK_TOKEN", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,72}\b")),
    Detector("STRIPE_KEY", re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    Detector("OPENAI_KEY", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    Detector("GOOGLE_API_KEY", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    Detector("JWT", re.compile(
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
    )),
    Detector("CREDIT_CARD", re.compile(r"\b\d(?:[ -]?\d){12,18}\b"), _luhn_ok),
    Detector("SSN", re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")),
    Detector("EMAIL", re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    )),
    Detector("IPV6", re.compile(
        r"\b(?:[A-Fa-f0-9]{1,4}:){2,7}[A-Fa-f0-9]{1,4}\b"
    )),
    Detector("IPV4", re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
    )),
    Detector("MAC", re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b")),
    Detector("PHONE", re.compile(
        r"(?<![\w.])(?:\+?\d{1,3}[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]\d{3}[ .-]\d{4}(?![\w])"
    )),
    # Generic "KEY = value" / "token: value" secret assignments.
    Detector("SECRET_ASSIGNMENT", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|pwd|access[_-]?key)"
        r"\b\s*[:=]\s*[\"']?([A-Za-z0-9/_+\-.=]{8,})[\"']?"
    )),
]


def detect(text: str, *, only: set[str] | None = None) -> list[Match]:
    """Find all secret/PII spans, longest-and-leftmost wins on overlap."""
    raw: list[Match] = []
    for det in DETECTORS:
        if only and det.label not in only:
            continue
        raw.extend(det.find(text))

    # Resolve overlaps deterministically.
    raw.sort(key=lambda m: (m.start, -(m.end - m.start)))
    chosen: list[Match] = []
    occupied_until = -1
    for m in raw:
        if m.start >= occupied_until:
            chosen.append(m)
            occupied_until = m.end
    return chosen

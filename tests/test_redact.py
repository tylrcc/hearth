"""Redaction tests. These run fully offline — no Ollama required."""

from hearth.redact import redact, restore
from hearth.redact.detectors import detect


def test_detects_common_secrets():
    text = (
        "email me at jane.doe@example.com from 10.0.0.42, "
        "aws key AKIAIOSFODNN7EXAMPLE, "
        "stripe sk_live_abcdef0123456789ABCD, "
        "token ghp_1234567890abcdefghijklmnopqrstuvwxyz."
    )
    labels = {m.label for m in detect(text)}
    assert {"EMAIL", "IPV4", "AWS_KEY", "STRIPE_KEY", "GITHUB_TOKEN"} <= labels


def test_redaction_is_reversible():
    text = "Contact admin@corp.io or 192.168.1.1 for access."
    result = redact(text)
    assert "admin@corp.io" not in result.text
    assert "192.168.1.1" not in result.text
    assert "<EMAIL_1>" in result.text
    assert restore(result.text, result.mapping) == text


def test_identical_values_share_one_placeholder():
    text = "from a@b.com to a@b.com"
    result = redact(text)
    assert result.text.count("<EMAIL_1>") == 2
    assert result.counts["EMAIL"] == 2
    assert len(result.mapping) == 1


def test_credit_card_requires_valid_luhn():
    valid = "card 4242424242424242 on file"        # passes Luhn
    invalid = "ticket 1234567890123456 reference"   # fails Luhn
    assert any(m.label == "CREDIT_CARD" for m in detect(valid))
    assert not any(m.label == "CREDIT_CARD" for m in detect(invalid))


def test_no_false_positive_on_clean_text():
    text = "The quick brown fox jumps over the lazy dog."
    result = redact(text)
    assert result.total == 0
    assert result.text == text


def test_overlapping_spans_never_overlap():
    # A JWT contains substrings that could match other patterns; ensure the
    # engine returns disjoint spans regardless.
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NQ.SflKxwRJSMeKKF2QT4"
    text = f"authorization: Bearer {jwt} for admin@x.io"
    spans = sorted(detect(text), key=lambda m: m.start)
    for a, b in zip(spans, spans[1:]):
        assert a.end <= b.start

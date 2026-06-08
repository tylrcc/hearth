"""Backend factory and OpenAI-compatible parsing tests (no server required)."""

import pytest

from hearth.backends import (
    BackendError,
    OpenAICompatBackend,
    get_backend,
    parse_chat_content,
    parse_embeddings,
)
from hearth.ollama import Ollama


def test_get_backend_defaults_to_ollama(monkeypatch):
    monkeypatch.delenv("HEARTH_BACKEND", raising=False)
    assert isinstance(get_backend(), Ollama)
    assert isinstance(get_backend("ollama"), Ollama)


def test_get_backend_openai_aliases():
    for name, host in [("llamacpp", ":8080"), ("mlx", ":8080"),
                       ("lmstudio", ":1234"), ("vllm", ":8000")]:
        b = get_backend(name)
        assert isinstance(b, OpenAICompatBackend)
        assert host in b.base_url
        assert b.kind == name


def test_get_backend_respects_explicit_url():
    b = get_backend("llamacpp", "http://box.local:9000/v1")
    assert b.base_url == "http://box.local:9000/v1"


def test_get_backend_reads_env(monkeypatch):
    monkeypatch.setenv("HEARTH_BACKEND", "mlx")
    assert isinstance(get_backend(), OpenAICompatBackend)


def test_get_backend_rejects_unknown():
    with pytest.raises(BackendError):
        get_backend("definitely-not-a-backend")


def test_parse_chat_strips_thinking():
    body = {"choices": [{"message": {"content": "<think>hmm</think>  hello "}}]}
    assert parse_chat_content(body) == "hello"


def test_parse_chat_without_choices_raises():
    with pytest.raises(BackendError):
        parse_chat_content({"choices": []})


def test_parse_embeddings_orders_by_index():
    body = {"data": [
        {"index": 1, "embedding": [0.2]},
        {"index": 0, "embedding": [0.1]},
    ]}
    assert parse_embeddings(body) == [[0.1], [0.2]]


def test_backends_share_the_interface():
    # Both must expose the same surface used across hearth.
    for b in (Ollama(), OpenAICompatBackend()):
        for attr in ("is_up", "models", "generate", "embed",
                     "endpoint", "label", "kind", "start_hint"):
            assert hasattr(b, attr)

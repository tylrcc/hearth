"""Query a built index and optionally explain matches with a local LLM."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..ollama import Ollama
from .store import Chunk, VectorStore

_EXPLAIN_SYSTEM = (
    "You explain why a code snippet matches a developer's search query. "
    "Answer in ONE short sentence (max 20 words). No preamble, no code blocks."
)


@dataclass
class Hit:
    score: float
    chunk: Chunk
    explanation: str | None = None


def search(
    root: str,
    query: str,
    *,
    k: int = 5,
    explain: bool = False,
    chat_model: str | None = None,
    client: Ollama | None = None,
) -> list[Hit]:
    client = client or Ollama()
    store = VectorStore(root)
    if not store.exists():
        raise FileNotFoundError(
            f"No index found under {root!r}. Run `hearth index` first."
        )
    store.load()

    query_vec = np.array(client.embed([query], model=store.model)[0], dtype=np.float32)
    results = store.search(query_vec, k)

    hits = [Hit(score, chunk) for score, chunk in results]
    if explain:
        for hit in hits:
            prompt = (
                f"Query: {query}\n\n"
                f"Snippet ({hit.chunk.path}:{hit.chunk.start_line}):\n{hit.chunk.text}"
            )
            try:
                hit.explanation = client.generate(
                    prompt, model=chat_model, system=_EXPLAIN_SYSTEM
                )
            except Exception:  # explanation is best-effort, never fatal
                hit.explanation = None
    return hits

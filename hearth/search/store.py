"""A tiny on-disk vector store backed by NumPy.

No external database: vectors live in ``.hearth/index.npz`` and chunk metadata in
``.hearth/index.json`` inside the indexed project. Plenty fast for codebases up
to tens of thousands of chunks, and trivial to inspect or delete.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

import numpy as np

INDEX_DIR = ".hearth"


@dataclass
class Chunk:
    path: str          # repo-relative file path
    start_line: int
    end_line: int
    text: str


class VectorStore:
    def __init__(self, root: str):
        self.root = root
        self.dir = os.path.join(root, INDEX_DIR)
        self.vectors: np.ndarray | None = None
        self.chunks: list[Chunk] = []
        self.model: str = ""

    @property
    def npz_path(self) -> str:
        return os.path.join(self.dir, "index.npz")

    @property
    def meta_path(self) -> str:
        return os.path.join(self.dir, "index.json")

    def exists(self) -> bool:
        return os.path.exists(self.npz_path) and os.path.exists(self.meta_path)

    def save(self, vectors: np.ndarray, chunks: list[Chunk], model: str) -> None:
        os.makedirs(self.dir, exist_ok=True)
        # Normalise once at write time so queries are a single dot product.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        np.savez_compressed(self.npz_path, vectors=(vectors / norms).astype(np.float32))
        meta = {"model": model, "chunks": [asdict(c) for c in chunks]}
        with open(self.meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh)
        self.vectors, self.chunks, self.model = vectors, chunks, model

    def load(self) -> None:
        self.vectors = np.load(self.npz_path)["vectors"]
        with open(self.meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
        self.model = meta["model"]
        self.chunks = [Chunk(**c) for c in meta["chunks"]]

    def search(self, query_vec: np.ndarray, k: int) -> list[tuple[float, Chunk]]:
        assert self.vectors is not None, "call load() first"
        q = query_vec / (np.linalg.norm(query_vec) or 1.0)
        scores = self.vectors @ q
        k = min(k, len(scores))
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        return [(float(scores[i]), self.chunks[i]) for i in top]

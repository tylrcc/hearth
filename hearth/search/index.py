"""Walk a project, chunk source files, and embed them with a local model."""

from __future__ import annotations

import fnmatch
import os
from typing import Iterator

import numpy as np

from ..ollama import Ollama
from .store import Chunk, VectorStore

# Extensions worth indexing. Keep it broad but skip binaries/lockfiles.
CODE_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".rb",
    ".php", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".swift", ".scala", ".sh",
    ".sql", ".md", ".rst", ".txt", ".toml", ".yaml", ".yml", ".json", ".vue",
}
SKIP_DIRS = {
    ".git", ".hearth", "node_modules", ".venv", "venv", "__pycache__", "dist",
    "build", ".next", "target", ".mypy_cache", ".pytest_cache", "vendor",
}
MAX_FILE_BYTES = 1_000_000
CHUNK_LINES = 40
CHUNK_OVERLAP = 10


def _gitignore_globs(root: str) -> list[str]:
    path = os.path.join(root, ".gitignore")
    globs: list[str] = []
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    globs.append(line.rstrip("/"))
    return globs


def iter_files(root: str) -> Iterator[str]:
    ignored = _gitignore_globs(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS
            and not any(fnmatch.fnmatch(d, g) for g in ignored)
        ]
        for name in filenames:
            if os.path.splitext(name)[1].lower() not in CODE_EXTS:
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            if any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(name, g) for g in ignored):
                continue
            full = os.path.join(dirpath, name)
            try:
                if os.path.getsize(full) > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield full


def chunk_file(path: str, root: str) -> list[Chunk]:
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    rel = os.path.relpath(path, root)
    chunks: list[Chunk] = []
    step = CHUNK_LINES - CHUNK_OVERLAP
    for start in range(0, max(len(lines), 1), step):
        window = lines[start : start + CHUNK_LINES]
        body = "".join(window).strip()
        if not body:
            continue
        chunks.append(Chunk(rel, start + 1, start + len(window), body))
        if start + CHUNK_LINES >= len(lines):
            break
    return chunks


def build_index(
    root: str,
    *,
    model: str,
    client: Ollama | None = None,
    batch_size: int = 64,
    progress=None,
) -> VectorStore:
    """Index every supported file under ``root`` and persist the vectors."""
    client = client or Ollama()
    chunks: list[Chunk] = []
    for path in iter_files(root):
        chunks.extend(chunk_file(path, root))
    if not chunks:
        raise ValueError(f"No indexable source files found under {root!r}.")

    vectors: list[list[float]] = []
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        # Prefix with the file path so location is part of the semantic signal.
        payload = [f"{c.path}\n{c.text}" for c in batch]
        vectors.extend(client.embed(payload, model=model))
        if progress:
            progress(min(i + batch_size, len(chunks)), len(chunks))

    store = VectorStore(root)
    store.save(np.array(vectors, dtype=np.float32), chunks, model)
    return store

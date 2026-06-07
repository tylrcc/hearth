"""Search-layer tests. Embeddings are stubbed, so these run without Ollama."""

import numpy as np

from hearth.search.index import chunk_file, iter_files
from hearth.search.store import Chunk, VectorStore


def test_iter_files_skips_noise(tmp_path):
    (tmp_path / "app.py").write_text("print('hi')\n")
    (tmp_path / "README.md").write_text("# docs\n")
    junk = tmp_path / "node_modules"
    junk.mkdir()
    (junk / "lib.js").write_text("module.exports = {}\n")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n")

    found = {p.split("/")[-1] for p in iter_files(str(tmp_path))}
    assert "app.py" in found
    assert "README.md" in found
    assert "lib.js" not in found      # node_modules skipped
    assert "logo.png" not in found    # non-code extension skipped


def test_chunk_file_produces_overlapping_windows(tmp_path):
    f = tmp_path / "big.py"
    f.write_text("\n".join(f"line {i}" for i in range(100)) + "\n")
    chunks = chunk_file(str(f), str(tmp_path))
    assert len(chunks) > 1
    assert chunks[0].start_line == 1
    # Windows overlap, so chunk 2 starts before chunk 1 ends.
    assert chunks[1].start_line <= chunks[0].end_line


def test_vector_store_roundtrip_and_ranking(tmp_path):
    store = VectorStore(str(tmp_path))
    chunks = [
        Chunk("a.py", 1, 2, "alpha"),
        Chunk("b.py", 1, 2, "beta"),
        Chunk("c.py", 1, 2, "gamma"),
    ]
    vectors = np.array([[1, 0, 0], [0, 1, 0], [0.9, 0.1, 0]], dtype=np.float32)
    store.save(vectors, chunks, model="stub")

    reloaded = VectorStore(str(tmp_path))
    assert reloaded.exists()
    reloaded.load()
    assert reloaded.model == "stub"

    results = reloaded.search(np.array([1, 0, 0], dtype=np.float32), k=2)
    # Closest to [1,0,0] is a.py, then c.py.
    assert [c.path for _, c in results] == ["a.py", "c.py"]
    assert results[0][0] >= results[1][0]

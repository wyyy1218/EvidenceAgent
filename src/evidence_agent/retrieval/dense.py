"""Dense embeddings + FAISS IndexFlatIP (normalized vectors)."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Protocol

import numpy as np


class Embedder(Protocol):
    def encode(self, texts: list[str], *, batch_size: int = 16) -> np.ndarray: ...

    @property
    def dim(self) -> int: ...

    @property
    def revision(self) -> str: ...


class HashEmbedder:
    """Deterministic fake dense embedder for tests (no model weights)."""

    def __init__(self, dim: int = 64, revision: str = "hash_embedder_v1"):
        self._dim = dim
        self._revision = revision

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def revision(self) -> str:
        return self._revision

    def encode(self, texts: list[str], *, batch_size: int = 16) -> np.ndarray:
        out = np.zeros((len(texts), self._dim), dtype=np.float32)
        for i, t in enumerate(texts):
            h = hashlib.sha256(t.encode("utf-8")).digest()
            rng = np.random.default_rng(int.from_bytes(h[:8], "little"))
            # Mix in token hashes for lexical signal
            v = rng.standard_normal(self._dim).astype(np.float32)
            for tok in t.lower().split():
                th = hashlib.md5(tok.encode("utf-8")).digest()
                idx = int.from_bytes(th[:4], "little") % self._dim
                v[idx] += 1.0
            n = np.linalg.norm(v) + 1e-12
            out[i] = v / n
        return out


class SentenceTransformerEmbedder:
    """BAAI/bge-m3 dense-only via sentence-transformers."""

    def __init__(self, model_path: str | Path, *, device: str = "cpu", threads: int = 8):
        os.environ.setdefault("OMP_NUM_THREADS", str(threads))
        os.environ.setdefault("MKL_NUM_THREADS", str(threads))
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(str(model_path), device=device)
        self._revision = Path(model_path).name
        # probe dim
        probe = self.encode(["dim_probe"], batch_size=1)
        self._dim = int(probe.shape[1])

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def revision(self) -> str:
        return self._revision

    def encode(self, texts: list[str], *, batch_size: int = 16) -> np.ndarray:
        vecs = self._model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        arr = np.asarray(vecs, dtype=np.float32)
        if not np.isfinite(arr).all():
            raise ValueError("non-finite embedding values")
        # ensure L2 normalized
        norms = np.linalg.norm(arr, axis=1, keepdims=True) + 1e-12
        return arr / norms


class FaissIPIndex:
    """FAISS IndexFlatIP over L2-normalized vectors."""

    def __init__(self, dim: int):
        import faiss

        self.dim = dim
        self.index = faiss.IndexFlatIP(dim)
        self.ids: list[str] = []

    def add(self, ids: list[str], vectors: np.ndarray) -> None:
        if vectors.dtype != np.float32:
            vectors = vectors.astype(np.float32)
        if vectors.shape[0] != len(ids):
            raise ValueError("ids/vectors length mismatch")
        if vectors.shape[1] != self.dim:
            raise ValueError(f"expected dim {self.dim}, got {vectors.shape[1]}")
        self.index.add(vectors)
        self.ids.extend(ids)

    def search(self, query_vec: np.ndarray, *, top_k: int = 20) -> list[tuple[str, float]]:
        if query_vec.ndim == 1:
            query_vec = query_vec.reshape(1, -1)
        if query_vec.dtype != np.float32:
            query_vec = query_vec.astype(np.float32)
        k = min(top_k, max(1, len(self.ids)))
        if len(self.ids) == 0:
            return []
        scores, idxs = self.index.search(query_vec, k)
        out: list[tuple[str, float]] = []
        for score, ix in zip(scores[0], idxs[0]):
            if ix < 0:
                continue
            out.append((self.ids[int(ix)], float(score)))
        return out

    def save(self, path: Path) -> None:
        import faiss

        path.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(path / "faiss.index"))
        (path / "ids.json").write_text(
            json.dumps(self.ids, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    @classmethod
    def load(cls, path: Path) -> "FaissIPIndex":
        import faiss

        index = faiss.read_index(str(path / "faiss.index"))
        ids = json.loads((path / "ids.json").read_text(encoding="utf-8"))
        obj = cls(index.d)
        obj.index = index
        obj.ids = ids
        return obj

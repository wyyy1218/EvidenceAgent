"""Cross-encoder reranker (bge-reranker-v2-m3) with fake fallback."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


class Reranker(Protocol):
    def score(self, query: str, documents: list[str]) -> list[float]: ...


class LexicalReranker:
    """Test-only reranker: overlap token count."""

    def score(self, query: str, documents: list[str]) -> list[float]:
        from evidence_agent.retrieval.tokenize import tokenize

        q = set(tokenize(query))
        out: list[float] = []
        for d in documents:
            dt = tokenize(d)
            if not dt:
                out.append(0.0)
                continue
            inter = sum(1 for t in dt if t in q)
            out.append(float(inter) / (len(set(dt)) ** 0.5))
        return out


class CrossEncoderReranker:
    def __init__(self, model_path: str | Path, *, device: str = "cpu", threads: int = 8):
        os.environ.setdefault("OMP_NUM_THREADS", str(threads))
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(str(model_path), device=device)

    def score(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        pairs = [(query, d) for d in documents]
        scores = self._model.predict(pairs, show_progress_bar=False)
        return [float(s) for s in scores]

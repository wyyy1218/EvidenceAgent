"""Okapi BM25 index (CPU)."""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from evidence_agent.retrieval.tokenize import tokenize


@dataclass
class BM25Index:
    doc_tokens: list[list[str]] = field(default_factory=list)
    doc_ids: list[str] = field(default_factory=list)
    doc_len: list[int] = field(default_factory=list)
    df: dict[str, int] = field(default_factory=dict)
    avgdl: float = 0.0
    N: int = 0
    k1: float = 1.5
    b: float = 0.75

    def add(self, doc_id: str, text: str) -> None:
        toks = tokenize(text)
        self.doc_ids.append(doc_id)
        self.doc_tokens.append(toks)
        self.doc_len.append(len(toks))
        seen: set[str] = set()
        for t in toks:
            if t not in seen:
                self.df[t] = self.df.get(t, 0) + 1
                seen.add(t)
        self.N = len(self.doc_ids)
        self.avgdl = sum(self.doc_len) / self.N if self.N else 0.0

    def build(self, items: list[tuple[str, str]]) -> None:
        self.doc_tokens.clear()
        self.doc_ids.clear()
        self.doc_len.clear()
        self.df.clear()
        for doc_id, text in items:
            self.add(doc_id, text)

    def _idf(self, term: str) -> float:
        n = self.df.get(term, 0)
        # BM25+ style smooth idf
        return math.log(1.0 + (self.N - n + 0.5) / (n + 0.5))

    def score(self, query: str, *, top_k: int = 20) -> list[tuple[str, float]]:
        q_terms = tokenize(query)
        if not q_terms or self.N == 0:
            return []
        scores = [0.0] * self.N
        q_tf = Counter(q_terms)
        for term, _qf in q_tf.items():
            if term not in self.df:
                continue
            idf = self._idf(term)
            for i, toks in enumerate(self.doc_tokens):
                tf = toks.count(term)
                if tf == 0:
                    continue
                dl = self.doc_len[i]
                denom = tf + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1.0))
                scores[i] += idf * (tf * (self.k1 + 1)) / denom
        ranked = sorted(
            ((self.doc_ids[i], scores[i]) for i in range(self.N) if scores[i] > 0),
            key=lambda x: x[1],
            reverse=True,
        )
        return ranked[:top_k]

    def to_state(self) -> dict[str, Any]:
        return {
            "doc_ids": self.doc_ids,
            "doc_tokens": self.doc_tokens,
            "doc_len": self.doc_len,
            "df": self.df,
            "avgdl": self.avgdl,
            "N": self.N,
            "k1": self.k1,
            "b": self.b,
        }

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> "BM25Index":
        idx = cls(
            doc_tokens=state["doc_tokens"],
            doc_ids=state["doc_ids"],
            doc_len=state["doc_len"],
            df={str(k): int(v) for k, v in state["df"].items()},
            avgdl=float(state["avgdl"]),
            N=int(state["N"]),
            k1=float(state.get("k1", 1.5)),
            b=float(state.get("b", 0.75)),
        )
        return idx

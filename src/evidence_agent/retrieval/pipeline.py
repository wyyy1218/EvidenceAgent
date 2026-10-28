"""S13 fixed hybrid retrieval: BM2520 + dense20 → dedupe → RRF → rerank12 → top6."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evidence_agent.ingestion.chunker import approx_qwen_tokens
from evidence_agent.retrieval.cache import RetrievalCache
from evidence_agent.retrieval.dense import Embedder, HashEmbedder
from evidence_agent.retrieval.index_store import load_index_bundle, load_project_config
from evidence_agent.retrieval.rerank import LexicalReranker, Reranker
from evidence_agent.retrieval.rrf import rrf_fuse


@dataclass
class SearchCandidate:
    candidate_id: str
    chunk_id: str
    source_version_id: str
    title: str | None
    page: int | None
    section: str | None
    start: int
    end: int
    preview: str
    score: float
    source: str = "local"

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "chunk_id": self.chunk_id,
            "source_version_id": self.source_version_id,
            "title": self.title,
            "page": self.page,
            "section": self.section,
            "start": self.start,
            "end": self.end,
            "preview": self.preview,
            "score": self.score,
            "source": self.source,
        }


@dataclass
class SearchResult:
    status: str  # ok | empty
    query: str
    candidates: list[SearchCandidate] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)
    cache: str = "cold"  # cold | hot

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "query": self.query,
            "candidates": [c.to_dict() for c in self.candidates],
            "debug": self.debug,
            "cache": self.cache,
        }


def preview_text(text: str, *, max_tokens: int = 72) -> str:
    """Truncate preview to ≤ max Qwen tokens; never treat as evidence."""
    if approx_qwen_tokens(text) <= max_tokens:
        return text
    # binary cut by chars
    lo, hi = 1, len(text)
    best = 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if approx_qwen_tokens(text[:mid]) <= max_tokens:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return text[:best].rstrip() + "…"


class HybridRetriever:
    def __init__(
        self,
        root: Path,
        project_id: str,
        *,
        embedder: Embedder | None = None,
        reranker: Reranker | None = None,
        cache: RetrievalCache | None = None,
    ):
        self.root = root
        self.project_id = project_id
        self.embedder = embedder or HashEmbedder()
        self.reranker = reranker or LexicalReranker()
        self.cache = cache or RetrievalCache()
        cfg = load_project_config(root)
        ret = cfg.get("retrieval") or {}
        self.bm25_top_k = int(ret.get("bm25_top_k", 20))
        self.dense_top_k = int(ret.get("dense_top_k", 20))
        self.rrf_k = int(ret.get("rrf_k", 60))
        self.rerank_top_k = int(ret.get("rerank_top_k", 12))
        self.return_top_k = int(ret.get("return_top_k", 6))
        self.preview_max = int(ret.get("preview_max_tokens", 72))
        self._bundle: dict[str, Any] | None = None

    def reload(self) -> bool:
        self._bundle = load_index_bundle(self.root, self.project_id)
        return self._bundle is not None

    @property
    def ready(self) -> bool:
        if self._bundle is None:
            self.reload()
        return self._bundle is not None and bool(self._bundle.get("chunks"))

    def search(self, query: str, *, use_cache: bool = True) -> SearchResult:
        query = (query or "").strip()
        if not query:
            return SearchResult(status="empty", query=query, debug={"reason": "empty_query"})

        if not self.ready:
            return SearchResult(status="empty", query=query, debug={"reason": "index_not_ready"})

        assert self._bundle is not None
        manifest = self._bundle["manifest"]
        vhash = manifest["version_set_hash"]
        chash = manifest.get("config_hash", "")
        cache_key = RetrievalCache.make_key(vhash, query, chash)
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                cached["cache"] = "hot"
                return SearchResult(
                    status=cached["status"],
                    query=query,
                    candidates=[SearchCandidate(**c) for c in cached["candidates"]],
                    debug=cached.get("debug") or {},
                    cache="hot",
                )

        bm25: Any = self._bundle["bm25"]
        faiss_idx: Any = self._bundle["faiss"]
        chunks: dict[str, dict[str, Any]] = self._bundle["chunks"]

        bm25_hits = bm25.score(query, top_k=self.bm25_top_k)
        qvec = self.embedder.encode([query], batch_size=1)[0]
        dense_raw = faiss_idx.search(qvec, top_k=self.dense_top_k)
        # Drop near-random dense hits (HashEmbedder / weak IP); keep meaningful similarity
        dense_hits = [(i, s) for i, s in dense_raw if s >= 0.12]

        bm25_ids = [doc_id for doc_id, _ in bm25_hits]
        dense_ids = [doc_id for doc_id, _ in dense_hits]

        if not bm25_ids and not dense_ids:
            result = SearchResult(
                status="empty",
                query=query,
                candidates=[],
                debug={
                    "bm25": [],
                    "dense": [{"id": i, "score": s} for i, s in dense_raw[:5]],
                    "fused": [],
                    "rerank": [],
                    "reason": "zero_results",
                },
                cache="cold",
            )
            if use_cache:
                self.cache.put(
                    cache_key,
                    {"status": result.status, "candidates": [], "debug": result.debug},
                )
            return result

        # Dedupe key: source_version_id + chunk_id (chunk_id already unique; still join)
        def dedupe_keep_order(ids: list[str]) -> list[str]:
            seen: set[str] = set()
            out: list[str] = []
            for cid in ids:
                ch = chunks.get(cid)
                if not ch:
                    continue
                key = f"{ch['source_version_id']}+{cid}"
                if key in seen:
                    continue
                seen.add(key)
                out.append(cid)
            return out

        bm25_ids = dedupe_keep_order(bm25_ids)
        dense_ids = dedupe_keep_order(dense_ids)

        fused = rrf_fuse([bm25_ids, dense_ids], k=self.rrf_k)
        fused_ids = [doc_id for doc_id, _ in fused]
        # re-dedupe after fuse
        fused_ids = dedupe_keep_order(fused_ids)

        rerank_pool = fused_ids[: self.rerank_top_k]
        if not rerank_pool:
            result = SearchResult(
                status="empty",
                query=query,
                candidates=[],
                debug={
                    "bm25": bm25_ids,
                    "dense": dense_ids,
                    "fused": [],
                    "rerank": [],
                    "reason": "zero_results",
                },
                cache="cold",
            )
            if use_cache:
                self.cache.put(
                    cache_key,
                    {
                        "status": result.status,
                        "candidates": [],
                        "debug": result.debug,
                    },
                )
            return result

        docs = [chunks[cid]["text"] for cid in rerank_pool]
        scores = self.reranker.score(query, docs)
        ranked = sorted(
            zip(rerank_pool, scores),
            key=lambda x: x[1],
            reverse=True,
        )[: self.return_top_k]
        # If lexical rerank finds no overlap and BM25 was empty, treat as zero (T07)
        if not bm25_ids and (not ranked or max(s for _, s in ranked) <= 0.0):
            result = SearchResult(
                status="empty",
                query=query,
                candidates=[],
                debug={
                    "bm25": [],
                    "dense": [{"id": i, "score": s} for i, s in dense_hits],
                    "fused_order": fused_ids[: self.rerank_top_k],
                    "rerank": [],
                    "reason": "zero_results_after_rerank",
                },
                cache="cold",
            )
            if use_cache:
                self.cache.put(
                    cache_key,
                    {"status": result.status, "candidates": [], "debug": result.debug},
                )
            return result

        candidates: list[SearchCandidate] = []
        for cid, sc in ranked:
            ch = chunks[cid]
            cand_id = f"cand_local_{cid}"
            candidates.append(
                SearchCandidate(
                    candidate_id=cand_id,
                    chunk_id=cid,
                    source_version_id=ch["source_version_id"],
                    title=ch.get("title") or ch.get("section"),
                    page=ch.get("page"),
                    section=ch.get("section"),
                    start=int(ch["start"]),
                    end=int(ch["end"]),
                    preview=preview_text(ch["text"], max_tokens=self.preview_max),
                    score=float(sc),
                    source="local",
                )
            )

        debug = {
            "bm25": [{"id": i, "score": s} for i, s in bm25_hits],
            "dense": [{"id": i, "score": s} for i, s in dense_hits],
            "fused_order": fused_ids[: self.rerank_top_k],
            "rerank_order": [cid for cid, _ in ranked],
            "version_set_hash": vhash,
            "note": "preview_is_not_evidence",
        }
        result = SearchResult(
            status="ok",
            query=query,
            candidates=candidates,
            debug=debug,
            cache="cold",
        )
        if use_cache:
            self.cache.put(
                cache_key,
                {
                    "status": result.status,
                    "candidates": [c.to_dict() for c in candidates],
                    "debug": debug,
                },
            )
        return result

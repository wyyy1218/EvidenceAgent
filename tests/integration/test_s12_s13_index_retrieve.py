"""S12 index build + S13 hybrid retrieval fixtures."""
from __future__ import annotations

import json
from pathlib import Path

from evidence_agent.ingestion.pipeline import ingest_upload
from evidence_agent.retrieval.dense import HashEmbedder
from evidence_agent.retrieval.index_store import build_project_index, load_index_bundle
from evidence_agent.retrieval.pipeline import HybridRetriever
from evidence_agent.retrieval.rerank import LexicalReranker
from evidence_agent.storage.db import connect
from evidence_agent.storage import repositories as repo

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _ingest_corpus(work_tmp):
    conn = connect(work_tmp)
    try:
        pid = repo.create_project(conn, "s12", "")
        data = (FIXTURES / "retrieval_corpus.md").read_bytes()
        result = ingest_upload(
            conn,
            root=work_tmp,
            project_id=pid,
            display_name="retrieval_corpus.md",
            data=data,
            content_type="text/markdown",
        )
        conn.commit()
        return pid, result["version_id"]
    finally:
        conn.close()


def test_s12_build_index_atomic_pointer(work_tmp):
    pid, _vid = _ingest_corpus(work_tmp)
    conn = connect(work_tmp)
    try:
        out = build_project_index(
            conn, root=work_tmp, project_id=pid, embedder=HashEmbedder(dim=32)
        )
        conn.commit()
    finally:
        conn.close()

    assert out["chunk_count"] > 0
    ptr = work_tmp / "data" / "indexes" / f"current_{pid}.json"
    assert ptr.is_file()
    pointer = json.loads(ptr.read_text(encoding="utf-8"))
    assert pointer["index_id"] == out["index_id"]
    bundle = load_index_bundle(work_tmp, pid)
    assert bundle is not None
    assert len(bundle["chunks"]) == out["chunk_count"]
    # index↔chunk 一一：faiss ids ⊆ chunks
    for cid in bundle["faiss"].ids:
        assert cid in bundle["chunks"]
    # empty index forbidden — we have chunks
    assert bundle["manifest"]["status"] == "ready"
    man = work_tmp / "data" / "manifests" / f"mf_index_{out['index_id']}.json"
    assert man.is_file()


def test_s13_hybrid_pipeline_and_expectations(work_tmp):
    pid, _vid = _ingest_corpus(work_tmp)
    conn = connect(work_tmp)
    try:
        build_project_index(conn, root=work_tmp, project_id=pid, embedder=HashEmbedder(dim=32))
        conn.commit()
    finally:
        conn.close()

    expectations = json.loads((FIXTURES / "s13_expectations.json").read_text(encoding="utf-8"))
    retriever = HybridRetriever(
        work_tmp,
        pid,
        embedder=HashEmbedder(dim=32),
        reranker=LexicalReranker(),
    )
    assert retriever.ready

    for fx in expectations["fixtures"]:
        result = retriever.search(fx["query"])
        if fx.get("expect_empty"):
            assert result.status == "empty" or len(result.candidates) == 0
            continue
        assert result.status == "ok", fx["id"]
        assert result.candidates, fx["id"]
        # expected substring must appear in some candidate full chunk (not only preview)
        blob = " ".join(
            retriever._bundle["chunks"][c.chunk_id]["text"] for c in result.candidates  # noqa: SLF001
        )
        assert fx["expect_substring"] in blob, fx["id"]
        if "expect_also" in fx:
            assert fx["expect_also"] in blob, fx["id"]
        # preview bounded; not evidence
        for c in result.candidates:
            assert c.candidate_id.startswith("cand_local_")
            assert "preview" in c.to_dict()

    # algorithm order recorded
    r = retriever.search("NebulaGate")
    assert "bm25" in r.debug and "dense" in r.debug
    assert "fused_order" in r.debug and "rerank_order" in r.debug

    # cache hot/cold (fresh query not used in fixtures above)
    r1 = retriever.search("ListSourceVersions rate limit")
    r2 = retriever.search("ListSourceVersions rate limit")
    assert r1.cache == "cold"
    assert r2.cache == "hot"


def test_s13_t07_zero_results_no_fabrication(work_tmp):
    pid, _ = _ingest_corpus(work_tmp)
    conn = connect(work_tmp)
    try:
        build_project_index(conn, root=work_tmp, project_id=pid, embedder=HashEmbedder(dim=32))
        conn.commit()
    finally:
        conn.close()
    retriever = HybridRetriever(work_tmp, pid, embedder=HashEmbedder(dim=32), reranker=LexicalReranker())
    result = retriever.search("火星土豆协议ZZZQQQXXX999888")
    assert result.candidates == [] or result.status == "empty"

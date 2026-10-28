"""S16: evidence ledger, verify-by-id, scoped conflicts, no snippet upgrade."""
from __future__ import annotations

import json
from pathlib import Path

from evidence_agent.evidence.claims import link_claim_evidence, register_claim
from evidence_agent.evidence.conflict import assess_scopes
from evidence_agent.evidence.ledger import register_from_read, reject_non_body
from evidence_agent.evidence.verify import verify_evidence
from evidence_agent.ingestion.pipeline import ingest_upload
from evidence_agent.retrieval.dense import HashEmbedder
from evidence_agent.retrieval.index_store import build_project_index
from evidence_agent.retrieval.pipeline import HybridRetriever
from evidence_agent.retrieval.rerank import LexicalReranker
from evidence_agent.storage.db import connect
from evidence_agent.storage import repositories as repo
from evidence_agent.tools.candidates import CandidateRegistry
from evidence_agent.tools.local_search import local_search
from evidence_agent.tools.read_evidence import read_evidence
from evidence_agent.tools.types import ToolResult, ToolStatus

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _project_with_corpus(work_tmp):
    conn = connect(work_tmp)
    try:
        pid = repo.create_project(conn, "s16", "")
        data = (FIXTURES / "retrieval_corpus.md").read_bytes()
        ingest_upload(
            conn,
            root=work_tmp,
            project_id=pid,
            display_name="retrieval_corpus.md",
            data=data,
            content_type="text/markdown",
        )
        build_project_index(conn, root=work_tmp, project_id=pid, embedder=HashEmbedder(dim=32))
        versions = repo.list_project_version_ids(conn, pid)
        run_id, _ = repo.create_run(
            conn,
            project_id=pid,
            question="What is NebulaGate?",
            allow_web=False,
            budget_profile="standard",
            budget={"tool_calls": 8},
            idempotency_key=None,
            request_hash=None,
            version_set=versions,
        )
        conn.commit()
        return pid, run_id, versions
    finally:
        conn.close()


def test_reject_failure_and_snippet(work_tmp):
    fail = ToolResult(
        tool="read_evidence",
        status=ToolStatus.INACCESSIBLE,
        error_code="fetch_failed",
        error_message="x",
    )
    assert reject_non_body(fail) is not None
    empty = ToolResult(tool="web_search", status=ToolStatus.EMPTY, data={"candidates": []})
    assert reject_non_body(empty) is not None
    snippet = ToolResult(
        tool="web_search",
        status=ToolStatus.OK,
        data={"evidence": {"quote": "preview", "is_search_snippet": True}},
    )
    assert reject_non_body(snippet) == "search_snippet_rejected"


def test_register_and_verbatim_verify(work_tmp):
    pid, run_id, versions = _project_with_corpus(work_tmp)
    reg = CandidateRegistry()
    retriever = HybridRetriever(
        work_tmp, pid, embedder=HashEmbedder(dim=32), reranker=LexicalReranker()
    )
    search = local_search(
        root=work_tmp,
        project_id=pid,
        run_id=run_id,
        query="NebulaGate",
        retriever=retriever,
        registry=reg,
    )
    assert search.status == ToolStatus.OK
    cid = search.data["candidates"][0]["candidate_id"]
    read = read_evidence(
        candidate_id=cid,
        run_id=run_id,
        project_id=pid,
        root=work_tmp,
        registry=reg,
        authorized_version_ids=versions,
    )
    assert read.status == ToolStatus.OK
    quote = read.data["evidence"]["quote"]
    assert "NebulaGate" in quote

    conn = connect(work_tmp)
    try:
        rec = register_from_read(
            conn,
            root=work_tmp,
            run_id=run_id,
            project_id=pid,
            tool_result=read,
            read_action_id="act_test",
            requirement_ids=["req_main"],
            authorized_version_ids=versions,
        )
        conn.commit()
        assert rec.quote == quote
        assert rec.content_hash
        assert rec.context_text

        vr = verify_evidence(
            conn,
            root=work_tmp,
            run_id=run_id,
            evidence_id=rec.evidence_id,
            authorized_version_ids=versions,
            project_id=pid,
        )
        assert vr.ok, vr.errors
        assert vr.checks["quote_equals_span"]

        # Truncate model-context simulation: clear nothing on disk; ledger still verifies
        row = repo.get_evidence(conn, run_id, rec.evidence_id)
        assert row["quote"] == quote
    finally:
        conn.close()


def test_t20_cross_project_and_unknown_id(work_tmp):
    pid, run_id, versions = _project_with_corpus(work_tmp)
    conn = connect(work_tmp)
    try:
        other = repo.create_project(conn, "other", "")
        # Foreign evidence id
        vr = verify_evidence(
            conn,
            root=work_tmp,
            run_id=run_id,
            evidence_id="ev_does_not_exist",
            authorized_version_ids=versions,
            project_id=pid,
        )
        assert not vr.ok
        assert "evidence_not_found" in vr.errors

        # Register then verify with wrong project
        reg = CandidateRegistry()
        retriever = HybridRetriever(
            work_tmp, pid, embedder=HashEmbedder(dim=32), reranker=LexicalReranker()
        )
        search = local_search(
            root=work_tmp, project_id=pid, run_id=run_id, query="NebulaGate",
            retriever=retriever, registry=reg,
        )
        cid = search.data["candidates"][0]["candidate_id"]
        read = read_evidence(
            candidate_id=cid, run_id=run_id, project_id=pid, root=work_tmp,
            registry=reg, authorized_version_ids=versions,
        )
        rec = register_from_read(
            conn, root=work_tmp, run_id=run_id, project_id=pid,
            tool_result=read, authorized_version_ids=versions,
        )
        conn.commit()
        vr2 = verify_evidence(
            conn, root=work_tmp, run_id=run_id, evidence_id=rec.evidence_id,
            authorized_version_ids=versions, project_id=other,
        )
        assert not vr2.ok
        assert "cross_project" in vr2.errors
    finally:
        conn.close()


def test_t06_old_evidence_after_reindex(work_tmp):
    """Updating index must not break previously registered evidence against original version."""
    pid, run_id, versions = _project_with_corpus(work_tmp)
    reg = CandidateRegistry()
    retriever = HybridRetriever(
        work_tmp, pid, embedder=HashEmbedder(dim=32), reranker=LexicalReranker()
    )
    search = local_search(
        root=work_tmp, project_id=pid, run_id=run_id, query="NebulaGate",
        retriever=retriever, registry=reg,
    )
    cid = search.data["candidates"][0]["candidate_id"]
    read = read_evidence(
        candidate_id=cid, run_id=run_id, project_id=pid, root=work_tmp,
        registry=reg, authorized_version_ids=versions,
    )
    conn = connect(work_tmp)
    try:
        rec = register_from_read(
            conn, root=work_tmp, run_id=run_id, project_id=pid,
            tool_result=read, authorized_version_ids=versions,
        )
        # Rebuild index (new index id) — normalized source version unchanged
        build_project_index(conn, root=work_tmp, project_id=pid, embedder=HashEmbedder(dim=32))
        conn.commit()
        vr = verify_evidence(
            conn, root=work_tmp, run_id=run_id, evidence_id=rec.evidence_id,
            authorized_version_ids=versions, project_id=pid,
        )
        assert vr.ok, vr.errors
    finally:
        conn.close()


def test_scoped_difference_not_auto_conflict():
    a = {"text": "Limit is 10", "scope": {"version": "v1", "condition": "offline"}}
    b = {"text": "Limit is 100", "scope": {"version": "v2", "condition": "online"}}
    r = assess_scopes(a, b)
    assert r.status == "scoped_difference"

    c = {"text": "Limit is 10", "scope": {"version": "v1", "condition": "offline"}}
    d = {"text": "Limit is 100", "scope": {"version": "v1", "condition": "offline"}}
    r2 = assess_scopes(c, d)
    assert r2.status == "conflicting"

    e = {"text": "A", "scope": {}}
    f = {"text": "B", "scope": {}}
    r3 = assess_scopes(e, f)
    assert r3.status == "unresolved"


def test_claim_links_full_evidence_set(work_tmp):
    pid, run_id, versions = _project_with_corpus(work_tmp)
    reg = CandidateRegistry()
    retriever = HybridRetriever(
        work_tmp, pid, embedder=HashEmbedder(dim=32), reranker=LexicalReranker()
    )
    search = local_search(
        root=work_tmp, project_id=pid, run_id=run_id, query="NebulaGate",
        retriever=retriever, registry=reg,
    )
    cid = search.data["candidates"][0]["candidate_id"]
    read = read_evidence(
        candidate_id=cid, run_id=run_id, project_id=pid, root=work_tmp,
        registry=reg, authorized_version_ids=versions,
    )
    conn = connect(work_tmp)
    try:
        rec = register_from_read(
            conn, root=work_tmp, run_id=run_id, project_id=pid,
            tool_result=read, authorized_version_ids=versions,
        )
        claim = register_claim(
            conn,
            run_id=run_id,
            text="NebulaGate supports offline mode",
            requirement_id="req1",
            scope={"condition": "offline"},
            evidence_ids=[rec.evidence_id],
        )
        conn.commit()
        assert rec.evidence_id in claim.evidence_ids
        link_claim_evidence(conn, claim_id=claim.claim_id, evidence_id=rec.evidence_id)
    finally:
        conn.close()


def test_migration_0002_applied(work_tmp):
    conn = connect(work_tmp)
    try:
        cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(evidence)").fetchall()
        }
        assert "context_text" in cols
        assert "content_hash" in cols
        assert "requirement_ids_json" in cols
    finally:
        conn.close()

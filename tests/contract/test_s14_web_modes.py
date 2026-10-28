"""S14: off / replay / live discovery vs read separation."""
from __future__ import annotations

import json
from pathlib import Path

from evidence_agent.tools.candidates import CandidateRegistry
from evidence_agent.tools.read_evidence import read_evidence
from evidence_agent.tools.types import ToolStatus
from evidence_agent.tools.web_search import ReplayCorpus, WebSearchBudget, web_search

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_off_mode_zero_external_calls(work_tmp):
    reg = CandidateRegistry()
    r = web_search(
        query="NebulaGate",
        mode="off",
        project_id="p1",
        run_id="run1",
        root=work_tmp,
        allow_web=False,
        registry=reg,
    )
    assert r.status == ToolStatus.OK
    assert r.data["external_calls"] == 0
    assert r.data["candidates"] == []
    assert r.meta["external_calls"] == 0


def test_replay_repeatable_and_not_evidence(work_tmp):
    corpus = ReplayCorpus.load(FIXTURES / "replay_corpus.json")
    # install under data/snapshots for path-based load too
    dest = work_tmp / "data" / "snapshots"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "replay_corpus.json").write_text(
        (FIXTURES / "replay_corpus.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    reg = CandidateRegistry()
    a = web_search(
        query="NebulaGate CreateEvidenceSession",
        mode="replay",
        project_id="p1",
        run_id="run1",
        root=work_tmp,
        allow_web=True,
        registry=reg,
        replay_corpus=corpus,
    )
    b = web_search(
        query="NebulaGate CreateEvidenceSession",
        mode="replay",
        project_id="p1",
        run_id="run1",
        root=work_tmp,
        allow_web=True,
        registry=reg,
        replay_corpus=corpus,
    )
    assert a.status == ToolStatus.OK
    assert b.status == ToolStatus.OK
    assert [c["url"] for c in a.data["candidates"]] == [c["url"] for c in b.data["candidates"]]
    assert a.meta.get("note", "").startswith("replay_is_not_live")
    for c in a.data["candidates"]:
        assert c["snippet_is_not_evidence"] is True


def test_live_without_key_marked_unavailable(work_tmp, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    reg = CandidateRegistry()
    budget = WebSearchBudget(max_live=3)
    r = web_search(
        query="test",
        mode="live",
        project_id="p1",
        run_id="run1",
        root=work_tmp,
        allow_web=True,
        registry=reg,
        budget=budget,
        tavily_api_key=None,
    )
    assert r.status == ToolStatus.INACCESSIBLE
    assert r.error_code == "tavily_key_missing"
    assert r.meta.get("live_available") is False


def test_summary_fetch_fail_not_evidence(work_tmp):
    """T09: snippet has answer but fetch fails → no evidence upgrade."""
    reg = CandidateRegistry()
    corpus = ReplayCorpus(
        entries=[
            {
                "url": "http://127.0.0.1:9/secret",  # will be SSRF-blocked on read
                "title": "answer inside snippet",
                "snippet": "THE_SECRET_ANSWER_42",
                "text": "THE_SECRET_ANSWER_42",
            }
        ]
    )
    search = web_search(
        query="SECRET_ANSWER",
        mode="replay",
        project_id="p1",
        run_id="run1",
        root=work_tmp,
        allow_web=True,
        registry=reg,
        replay_corpus=corpus,
    )
    assert search.status == ToolStatus.OK
    cid = search.data["candidates"][0]["candidate_id"]
    read = read_evidence(
        candidate_id=cid,
        run_id="run1",
        project_id="p1",
        root=work_tmp,
        registry=reg,
        allow_web_fetch=True,
    )
    assert read.is_failure
    assert read.data.get("evidence") is None
    assert "snippet" in (read.error_message or "").lower() or read.meta.get("snippet_discarded")

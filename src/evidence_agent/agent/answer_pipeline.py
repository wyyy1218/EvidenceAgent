"""Shared answer path: citation check → Writer → Verifier → status (used by B0 and agent)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from evidence_agent.agent.llm import LLMClient
from evidence_agent.agent.requirements import extract_requirements
from evidence_agent.agent.result import RunResult, decide_status
from evidence_agent.agent.verifier import apply_verification_to_claims, run_verifier
from evidence_agent.agent.writer import citation_integrity_check, run_writer


def produce_answer(
    client: LLMClient,
    *,
    conn,
    root: Path,
    run_id: str,
    project_id: str,
    question: str,
    evidence_cards: list[dict[str, Any]],
    authorized_version_ids: set[str] | list[str] | None,
    user_constraints: list[str] | None = None,
    usage_acc: dict[str, Any] | None = None,
) -> RunResult:
    reqs = [r.to_dict() for r in extract_requirements(question, user_constraints=user_constraints)]
    usage_acc = usage_acc if usage_acc is not None else {
        "input_tokens": 0,
        "output_tokens": 0,
        "tool_calls": 0,
    }

    writer_out, w_usage = run_writer(
        client,
        question=question,
        requirements=reqs,
        evidence_cards=evidence_cards,
    )
    usage_acc["input_tokens"] = usage_acc.get("input_tokens", 0) + w_usage.input_tokens
    usage_acc["output_tokens"] = usage_acc.get("output_tokens", 0) + w_usage.output_tokens

    claims = writer_out["claims"]
    unresolved = list(writer_out["unresolved"])

    ok_claims, cite_unresolved = citation_integrity_check(
        conn,
        root=root,
        run_id=run_id,
        claims=claims,
        authorized_version_ids=authorized_version_ids,
        project_id=project_id,
    )
    unresolved.extend(cite_unresolved)

    evidence_by_id = {
        (c.get("evidence_id") or c.get("id")): c for c in evidence_cards
    }
    verification: list[dict[str, Any]] = []
    if ok_claims:
        verification, v_usage = run_verifier(
            client, claims=ok_claims, evidence_by_id=evidence_by_id
        )
        usage_acc["input_tokens"] = usage_acc.get("input_tokens", 0) + v_usage.input_tokens
        usage_acc["output_tokens"] = usage_acc.get("output_tokens", 0) + v_usage.output_tokens
        ok_claims, v_unresolved = apply_verification_to_claims(ok_claims, verification)
        unresolved.extend(v_unresolved)

    status = decide_status(
        claims=ok_claims, unresolved=unresolved, verification=verification
    )
    # Prefer writer answer; if insufficient, keep semantic note
    answer = writer_out.get("answer")
    if status == "insufficient_evidence" and not ok_claims:
        answer = "当前资料与已执行搜索不足以支持主要结论（未找到不等于不存在）。"

    return RunResult(
        status=status,
        answer=answer,
        claims=ok_claims,
        unresolved=unresolved,
        evidence_ids=[c.get("evidence_id") or c.get("id") for c in evidence_cards],
        verification=verification,
        usage=usage_acc,
        route=writer_out.get("route") or "base",
    )

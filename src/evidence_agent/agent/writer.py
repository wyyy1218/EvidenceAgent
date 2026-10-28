"""Fixed Writer — base model only, structured claims + template answer."""
from __future__ import annotations

import json
from typing import Any

from evidence_agent.agent.llm import LLMClient, load_prompt, parse_json_object
from evidence_agent.agent.tokens import truncate_to_tokens
from evidence_agent.evidence.verify import verify_evidence


WRITER_EVIDENCE_MAX = 6
WRITER_QUOTE_MAX_TOKENS = 512
WRITER_COMPLETION_MAX = 768


def _select_evidence(cards: list[dict[str, Any]], limit: int = WRITER_EVIDENCE_MAX) -> list[dict[str, Any]]:
    return list(cards)[:limit]


def _prepare_evidence_payload(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for c in _select_evidence(cards):
        quote = truncate_to_tokens(c.get("quote") or "", WRITER_QUOTE_MAX_TOKENS)
        out.append(
            {
                "evidence_id": c.get("evidence_id") or c.get("id"),
                "source_version_id": c.get("source_version_id"),
                "page": c.get("page"),
                "title": c.get("title"),
                "quote": quote,
                "scope": c.get("scope") or {},
            }
        )
    return out


def render_answer(claims: list[dict[str, Any]], unresolved: list[str], status_hint: str | None) -> str:
    lines: list[str] = []
    for c in claims:
        text = (c.get("text") or "").strip()
        if not text:
            continue
        scope = c.get("scope") or {}
        scope_bits = [f"{k}={v}" for k, v in scope.items() if v not in (None, "")]
        eids = c.get("evidence_ids") or []
        suffix = ""
        if scope_bits:
            suffix += f"（范围: {', '.join(scope_bits)}）"
        if eids:
            suffix += f" [{', '.join(eids)}]"
        lines.append(f"- {text}{suffix}")
    if unresolved:
        lines.append("未解决：" + "；".join(unresolved))
    if not lines:
        if status_hint == "insufficient_evidence":
            return "当前资料不足以支持主要结论（未找到不等于不存在）。"
        return "无可用结论。"
    return "\n".join(lines)


def run_writer(
    client: LLMClient,
    *,
    question: str,
    requirements: list[dict[str, Any]],
    evidence_cards: list[dict[str, Any]],
    max_tokens: int = WRITER_COMPLETION_MAX,
) -> tuple[dict[str, Any], Any]:
    system = load_prompt("writer")
    payload = {
        "question": question,
        "requirements": requirements,
        "evidence": _prepare_evidence_payload(evidence_cards),
        "output_schema": {
            "status_hint": "answered|partial|insufficient_evidence|conflicting_evidence",
            "claims": [
                {
                    "claim_id": "cl_…",
                    "requirement_id": "req_…",
                    "text": "…",
                    "evidence_ids": ["ev_…"],
                    "scope": {},
                    "status": "draft",
                }
            ],
            "unresolved": ["…"],
        },
    }
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False),
        },
    ]
    # Writer must use base route — never pass adapter_id
    resp = client.chat(messages, max_tokens=max_tokens, temperature=0.0, adapter_id=None)
    try:
        obj = parse_json_object(resp.content)
    except ValueError:
        obj = {
            "status_hint": "insufficient_evidence",
            "claims": [],
            "unresolved": ["writer_parse_failed"],
        }
    claims = obj.get("claims") or []
    raw_unresolved = obj.get("unresolved") or []
    if isinstance(raw_unresolved, dict):
        unresolved = [f"{k}:{v}" for k, v in raw_unresolved.items()]
    elif isinstance(raw_unresolved, list):
        unresolved = [str(x) for x in raw_unresolved]
    elif raw_unresolved:
        unresolved = [str(raw_unresolved)]
    else:
        unresolved = []
    # Drop claims that cite unknown evidence ids
    known = {c.get("evidence_id") or c.get("id") for c in evidence_cards}
    cleaned = []
    for cl in claims:
        if not isinstance(cl, dict):
            continue
        eids = [e for e in (cl.get("evidence_ids") or []) if e in known]
        if not eids and known:
            unresolved.append(f"claim_without_valid_evidence:{str(cl.get('text', ''))[:40]}")
            continue
        cl = dict(cl)
        cl["evidence_ids"] = eids
        cleaned.append(cl)
    status_hint = obj.get("status_hint") or "partial"
    answer = render_answer(cleaned, unresolved, status_hint)
    return {
        "status_hint": status_hint,
        "claims": cleaned,
        "unresolved": unresolved,
        "answer": answer,
        "route": getattr(resp.usage, "route", "base"),
    }, resp.usage


def citation_integrity_check(
    conn,
    *,
    root,
    run_id: str,
    claims: list[dict[str, Any]],
    authorized_version_ids: set[str] | list[str] | None,
    project_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Code check before model verifier. Returns (ok_claims, unresolved_msgs)."""
    ok_claims: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for cl in claims:
        eids = cl.get("evidence_ids") or []
        if not eids:
            unresolved.append(f"missing_citation:{cl.get('text', '')[:60]}")
            continue
        all_ok = True
        for eid in eids:
            vr = verify_evidence(
                conn,
                root=root,
                run_id=run_id,
                evidence_id=eid,
                authorized_version_ids=authorized_version_ids,
                project_id=project_id,
            )
            if not vr.ok:
                all_ok = False
                unresolved.append(f"citation_failed:{eid}:{','.join(vr.errors)}")
        if all_ok:
            ok_claims.append(cl)
    return ok_claims, unresolved

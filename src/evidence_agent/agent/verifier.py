"""Fixed Verifier — model judgment, not human ground truth."""
from __future__ import annotations

import json
from typing import Any

from evidence_agent.agent.llm import LLMClient, load_prompt, parse_json_object

VERIFIER_COMPLETION_MAX = 768
VALID_LABELS = frozenset({"supported", "unsupported", "conflicting", "uncertain"})


def run_verifier(
    client: LLMClient,
    *,
    claims: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    max_tokens: int = VERIFIER_COMPLETION_MAX,
) -> tuple[list[dict[str, Any]], Any]:
    system = load_prompt("verifier")
    items = []
    for cl in claims:
        eids = cl.get("evidence_ids") or []
        evidence = []
        for eid in eids:
            ev = evidence_by_id.get(eid) or {}
            evidence.append(
                {
                    "evidence_id": eid,
                    "quote": ev.get("quote"),
                    "scope": ev.get("scope") or {},
                }
            )
        items.append(
            {
                "claim_id": cl.get("claim_id") or cl.get("id"),
                "text": cl.get("text"),
                "scope": cl.get("scope") or {},
                "evidence": evidence,
            }
        )
    payload = {
        "claims": items,
        "output_schema": {
            "results": [
                {
                    "claim_id": "…",
                    "label": "supported|unsupported|conflicting|uncertain",
                    "reason": "…",
                }
            ]
        },
    }
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    resp = client.chat(messages, max_tokens=max_tokens, temperature=0.0, adapter_id=None)
    try:
        obj = parse_json_object(resp.content)
        results = obj.get("results") or obj.get("verdicts") or []
    except ValueError:
        results = [
            {
                "claim_id": cl.get("claim_id") or cl.get("id"),
                "label": "uncertain",
                "reason": "verifier_parse_failed",
            }
            for cl in claims
        ]

    cleaned: list[dict[str, Any]] = []
    for r in results:
        label = r.get("label") or "uncertain"
        if label not in VALID_LABELS:
            label = "uncertain"
        cleaned.append(
            {
                "claim_id": r.get("claim_id"),
                "label": label,
                "reason": r.get("reason") or "",
                "model_judgment_not_ground_truth": True,
            }
        )
    return cleaned, resp.usage


def apply_verification_to_claims(
    claims: list[dict[str, Any]],
    verification: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Downgrade unsupported/uncertain; no infinite rewrite."""
    by_id = {v["claim_id"]: v for v in verification if v.get("claim_id")}
    updated: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for cl in claims:
        cid = cl.get("claim_id") or cl.get("id")
        v = by_id.get(cid)
        cl = dict(cl)
        if not v:
            cl["status"] = "uncertain"
            unresolved.append(f"unverified:{cid}")
            updated.append(cl)
            continue
        label = v["label"]
        cl["verification_status"] = label
        if label == "supported":
            cl["status"] = "supported"
            updated.append(cl)
        elif label == "conflicting":
            cl["status"] = "conflicting"
            updated.append(cl)
        else:
            cl["status"] = "uncertain"
            unresolved.append(f"{label}:{cl.get('text', '')[:60]}")
            # Keep claim but marked uncertain — do not invent facts
            updated.append(cl)
    return updated, unresolved

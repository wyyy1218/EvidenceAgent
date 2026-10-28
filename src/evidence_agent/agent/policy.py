"""Policy node — short JSON action; one repair attempt max."""
from __future__ import annotations

import json
from typing import Any

from evidence_agent.agent.actions import (
    ActionValidationError,
    coerce_policy_action,
    validate_action,
)
from evidence_agent.agent.llm import LLMClient, parse_json_object
from evidence_agent.agent.packer import PackedPrompt

# Matches S07/S33 vLLM guided_json probe schema (four fields, five actions).
ACTION_GUIDED_JSON: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["local_search", "web_search", "read_evidence", "finish", "abstain"],
        },
        "query": {"type": ["string", "null"]},
        "candidate_id": {"type": ["string", "null"]},
        "reason_code": {"type": ["string", "null"]},
    },
    "required": ["action", "query", "candidate_id", "reason_code"],
    "additionalProperties": False,
}


def run_policy(
    client: LLMClient,
    packed: PackedPrompt,
    *,
    allow_web: bool,
    known_candidate_ids: set[str],
    budget,
    usage_ledger,
    conn,
    run_id: str,
    repair_budget: int = 1,
    policy_adapter_id: str | None = None,
    temperature: float = 0.0,
    seed: int | None = None,
) -> tuple[dict[str, Any] | None, str | None, list[dict[str, Any]]]:
    """
    Returns (action|None, failure_code|None, raw_attempts).
    On second invalid → failed_policy.
    """
    attempts: list[dict[str, Any]] = []
    messages = list(packed.messages)

    for attempt in range(repair_budget + 1):
        ok, reason = budget.can_call_model(
            max_input=packed.prompt_tokens + 64,
            max_output=packed.completion_budget,
            is_final_writer_or_verifier=False,
        )
        if not ok:
            return None, reason or "budget", attempts

        resp = client.chat(
            messages,
            max_tokens=packed.completion_budget,
            temperature=float(temperature),
            adapter_id=policy_adapter_id,
            seed=seed if seed is None else int(seed) + attempt,
            guided_json=ACTION_GUIDED_JSON,
        )
        budget.record_tokens(input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens)
        usage_ledger.add(
            conn,
            kind="policy",
            model=resp.usage.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            billing_status="n/a",
            meta={"attempt": attempt, "route": resp.usage.route},
        )
        raw = resp.content
        try:
            obj = parse_json_object(raw)
            coerced = coerce_policy_action(
                obj, allow_web=allow_web, known_candidate_ids=known_candidate_ids
            )
            action = validate_action(
                coerced, allow_web=allow_web, known_candidate_ids=known_candidate_ids
            )
            attempts.append(
                {
                    "raw": raw,
                    "ok": True,
                    "action": action,
                    "coerced": coerced != obj,
                }
            )
            return action, None, attempts
        except (ValueError, ActionValidationError, json.JSONDecodeError) as exc:
            code = getattr(exc, "code", type(exc).__name__)
            attempts.append({"raw": raw, "ok": False, "error": str(exc), "code": code})
            if attempt >= repair_budget:
                return None, "failed_policy", attempts
            known_list = sorted(known_candidate_ids)[:12]
            repair_hint = (
                "If candidates is empty, choose local_search (or web_search if allowed), "
                "not read_evidence. "
                if not known_candidate_ids
                else f"Registered candidate_ids: {known_list}. "
            )
            messages = list(packed.messages) + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        "Previous output was invalid ("
                        + str(exc)
                        + "). "
                        + repair_hint
                        + "Reply with only one JSON object with fields "
                        "action, query, candidate_id, reason_code. "
                        "For search/read: reason_code must be null. "
                        "For finish/abstain: query=null, candidate_id=null, "
                        "reason_code one of evidence_sufficient|missing_source|"
                        "conflicting_sources|low_information_gain|budget_exhausted|"
                        "tool_unavailable. Example finish: "
                        '{"action":"finish","query":null,"candidate_id":null,'
                        '"reason_code":"evidence_sufficient"}'
                    ),
                },
            ]

    return None, "failed_policy", attempts

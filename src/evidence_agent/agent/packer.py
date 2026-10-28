"""Deterministic visible-state packer for policy prompts (S18)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from evidence_agent.agent.llm import load_prompt
from evidence_agent.agent.state import VisibleState, assert_no_gold
from evidence_agent.agent.tokens import count_tokens

POLICY_PROMPT_MAX = 2880
POLICY_COMPLETION_MAX = 192
TRAIN_TOTAL_MAX = 3072  # prompt + completion


class PackRejectError(ValueError):
    """Question too long to retain required constraints — refuse at entry."""


@dataclass
class PackedPrompt:
    messages: list[dict[str, str]]
    prompt_tokens: int
    completion_budget: int
    truncated: bool
    state_hash: str
    kept: dict[str, int]
    dropped_ids: dict[str, list[str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "messages": self.messages,
            "prompt_tokens": self.prompt_tokens,
            "completion_budget": self.completion_budget,
            "truncated": self.truncated,
            "state_hash": self.state_hash,
            "kept": self.kept,
            "dropped_ids": self.dropped_ids,
        }


_NEGATION = re.compile(r"(不|非|未|禁止|不要|不得|without|not\s+|no\s+)", re.I)


ABLATION_NONE = None
ABLATION_NO_SOURCE_ANCHOR = "no_source_anchor"
ABLATION_HIDE_VISIBLE_BUDGET = "hide_visible_budget"
_VALID_ABLATIONS = {ABLATION_NO_SOURCE_ANCHOR, ABLATION_HIDE_VISIBLE_BUDGET}


def _card_compact(
    card: dict[str, Any],
    *,
    kind: str,
    ablation_variant: str | None = None,
) -> dict[str, Any]:
    """Keep IDs and precise fields; ablation may strip policy-visible anchors."""
    if ablation_variant == ABLATION_NO_SOURCE_ANCHOR:
        # Summary-only: no IDs / page / source_version for re-read.
        if kind == "evidence":
            quote = card.get("quote") or card.get("preview") or ""
            return {
                "title": card.get("title"),
                "summary": (quote[:240] if isinstance(quote, str) else str(quote)[:240]),
                "anchor_removed": True,
            }
        if kind == "candidate":
            preview = card.get("preview") or card.get("snippet") or ""
            return {
                "title": card.get("title"),
                "preview": (preview[:240] if isinstance(preview, str) else str(preview)[:240]),
                "anchor_removed": True,
            }
    if kind == "evidence":
        return {
            "evidence_id": card.get("evidence_id") or card.get("id"),
            "source_version_id": card.get("source_version_id"),
            "page": card.get("page"),
            "title": card.get("title"),
            "quote": card.get("quote"),
            "scope": card.get("scope") or {},
        }
    if kind == "candidate":
        return {
            "candidate_id": card.get("candidate_id") or card.get("id"),
            "title": card.get("title"),
            "preview": card.get("preview") or card.get("snippet"),
            "source_version_id": card.get("source_version_id"),
        }
    return dict(card)


def pack_visible_state(
    state: VisibleState,
    *,
    system_prompt: str | None = None,
    prompt_max: int = POLICY_PROMPT_MAX,
    completion_max: int = POLICY_COMPLETION_MAX,
    ablation_variant: str | None = None,
) -> PackedPrompt:
    if ablation_variant is not None and ablation_variant not in _VALID_ABLATIONS:
        raise ValueError(f"unknown_ablation_variant:{ablation_variant}")
    assert_no_gold(state.visible_dict())
    system = system_prompt if system_prompt is not None else load_prompt("controller")
    hide_budget = ablation_variant == ABLATION_HIDE_VISIBLE_BUDGET

    # Guard: question itself must fit with system + budget skeleton
    core: dict[str, Any] = {
        "question": state.question,
        "requirements": state.requirements,
        "project_id": state.project_id,
        "snapshot_set_id": state.snapshot_set_id,
    }
    if not hide_budget:
        core["budget"] = state.budget
    core_msgs_budget = (
        count_tokens(system)
        + count_tokens(json.dumps(core, ensure_ascii=False, sort_keys=True))
        + 32
    )
    if core_msgs_budget > prompt_max:
        # If question has negation/constraints that cannot be kept, reject
        if _NEGATION.search(state.question) or len(state.requirements) > 1:
            raise PackRejectError(
                "question_too_long_to_retain_constraints: shrink scope or shorten question"
            )
        raise PackRejectError("question_exceeds_prompt_budget")

    evidence = [
        _card_compact(c, kind="evidence", ablation_variant=ablation_variant)
        for c in state.evidence_cards
    ]
    candidates = [
        _card_compact(c, kind="candidate", ablation_variant=ablation_variant)
        for c in state.candidates
    ]
    actions = list(state.recent_actions)
    gaps = list(state.open_gaps)
    failures = list(state.source_failures)

    dropped: dict[str, list[str]] = {
        "evidence_ids": [],
        "candidate_ids": [],
        "action_ids": [],
    }
    truncated = False

    def build_user(ev, cand, acts, gp, fail) -> str:
        body: dict[str, Any] = {
            "question": state.question,
            "requirements": state.requirements,
            "project_id": state.project_id,
            "snapshot_set_id": state.snapshot_set_id,
            "evidence_cards": ev,
            "candidates": cand,
            "recent_actions": acts,
            "open_gaps": gp,
            "open_gaps_is_suggestion_not_truth": True,
            "source_failures": fail,
            "no_new_evidence_streak": state.no_new_evidence_streak,
            "truncated": truncated,
            "action_schema": {
                "action": "local_search|web_search|read_evidence|finish|abstain",
                "query": "string|null",
                "candidate_id": "string|null",
                "reason_code": "null for search/read; enum only for finish/abstain",
                "notes": [
                    "local_search/web_search: query required; candidate_id=null; reason_code=null",
                    "read_evidence: candidate_id must be in candidates; query=null; reason_code=null",
                    "if candidates empty: do not read_evidence",
                ],
            },
        }
        if not hide_budget:
            body["budget"] = state.budget
        else:
            body["budget_hidden"] = True
        if ablation_variant == ABLATION_NO_SOURCE_ANCHOR:
            body["ablation"] = ABLATION_NO_SOURCE_ANCHOR
            body["action_schema"]["notes"] = [
                "local_search/web_search: query required; candidate_id=null; reason_code=null",
                "read_evidence is disabled in this ablation (no policy-visible anchors)",
                "finish/abstain as usual",
            ]
        return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def prompt_tokens(user: str) -> int:
        return count_tokens(system) + count_tokens(user)

    user = build_user(evidence, candidates, actions, gaps, failures)
    # Shrink by dropping lowest-priority first: old actions → candidates → evidence cards
    # Always retain IDs of dropped items for re-read.
    # Safety: never loop forever if token estimate does not drop
    prev_tokens = prompt_tokens(user)
    guard = 0
    while prompt_tokens(user) > prompt_max and guard < 500:
        guard += 1
        truncated = True
        if len(actions) > 0:
            drop = actions.pop(0)
            dropped["action_ids"].append(str(drop.get("step_no") or drop.get("action") or "act"))
        elif candidates:
            drop = candidates.pop()
            dropped["candidate_ids"].append(str(drop.get("candidate_id")))
        elif evidence:
            drop = evidence.pop()
            eid = str(drop.get("evidence_id"))
            dropped["evidence_ids"].append(eid)
        elif gaps:
            gaps.pop()
        elif failures:
            failures.pop()
        else:
            if _NEGATION.search(state.question):
                raise PackRejectError("cannot_pack_without_dropping_constraints")
            break
        user = build_user(evidence, candidates, actions, gaps, failures)
        now = prompt_tokens(user)
        if now >= prev_tokens and not (actions or candidates or evidence or gaps or failures):
            break
        prev_tokens = now

    # Retain dropped evidence ids as re-read stubs (compact) if budget allows a few.
    # Ablation no_source_anchor removes re-read capability — skip stubs.
    if dropped["evidence_ids"] and ablation_variant != ABLATION_NO_SOURCE_ANCHOR:
        stubs = [
            {"evidence_id": eid, "re_read": True}
            for eid in dropped["evidence_ids"][:8]
        ]
        trial = build_user(evidence + stubs, candidates, actions, gaps, failures)
        if prompt_tokens(trial) <= prompt_max:
            evidence = evidence + stubs
            user = trial

    # Ensure JSON is intact (rebuild from structures — never mid-string cut)
    json.loads(user)

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    pt = prompt_tokens(user)
    if pt + completion_max > TRAIN_TOTAL_MAX:
        # Cap completion budget so total train length holds
        completion_max = max(32, TRAIN_TOTAL_MAX - pt)

    state.truncated = truncated
    return PackedPrompt(
        messages=messages,
        prompt_tokens=pt,
        completion_budget=completion_max,
        truncated=truncated,
        state_hash=state.state_hash(),
        kept={
            "evidence": len(evidence),
            "candidates": len(candidates),
            "actions": len(actions),
        },
        dropped_ids=dropped,
    )

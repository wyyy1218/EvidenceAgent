"""Unit checks for E0 free-text reason_code coercion."""
from __future__ import annotations

from evidence_agent.agent.actions import coerce_policy_action, validate_action


def test_coerce_strips_prose_reason_on_local_search():
    raw = {
        "action": "local_search",
        "query": "gr.State session",
        "candidate_id": None,
        "reason_code": "需要确认官方文档中的功能描述",
    }
    coerced = coerce_policy_action(raw)
    assert coerced["reason_code"] is None
    action = validate_action(coerced)
    assert action["action"] == "local_search"
    assert action["query"] == "gr.State session"


def test_coerce_keeps_enum_reason_for_validator_on_search():
    raw = {
        "action": "local_search",
        "query": "q",
        "candidate_id": None,
        "reason_code": "evidence_sufficient",
    }
    coerced = coerce_policy_action(raw)
    assert coerced["reason_code"] == "evidence_sufficient"


def test_coerce_strips_query_on_read():
    raw = {
        "action": "read_evidence",
        "query": "please read this",
        "candidate_id": "cand_1",
        "reason_code": "because we need the body",
    }
    coerced = coerce_policy_action(raw)
    assert coerced["query"] is None
    assert coerced["reason_code"] is None
    action = validate_action(coerced, known_candidate_ids={"cand_1"})
    assert action["candidate_id"] == "cand_1"


def test_coerce_maps_finish_alias_and_clears_fields():
    raw = {
        "action": "finish",
        "query": None,
        "candidate_id": "cand_local_1",
        "reason_code": "finish",
    }
    coerced = coerce_policy_action(raw)
    assert coerced["candidate_id"] is None
    assert coerced["reason_code"] == "evidence_sufficient"
    action = validate_action(coerced)
    assert action["action"] == "finish"


def test_coerce_defaults_null_finish_reason():
    raw = {
        "action": "finish",
        "query": None,
        "candidate_id": None,
        "reason_code": None,
    }
    coerced = coerce_policy_action(raw)
    assert coerced["reason_code"] == "evidence_sufficient"
    validate_action(coerced)

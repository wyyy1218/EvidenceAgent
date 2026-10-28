"""S24 near-duplicate thresholds (frozen)."""
from evidence_agent.data.near_dup import (
    NEAR_DUP_JACCARD,
    SHORT_Q_JACCARD,
    is_near_duplicate,
    normalize_question,
    support_title_conflict,
)


def test_thresholds_frozen():
    assert NEAR_DUP_JACCARD == 0.85
    assert SHORT_Q_JACCARD == 0.75


def test_near_dup_similar():
    a = "Who founded the company that owns Acme?"
    b = "Who founded the company that owns Acme?"
    dup, score, short = is_near_duplicate(a, b)
    assert dup and score >= 0.85


def test_near_dup_different():
    a = "What is the capital of France?"
    b = "How many moons does Jupiter have according to the corpus?"
    dup, score, _ = is_near_duplicate(a, b)
    assert not dup
    assert score < 0.85


def test_support_title_conflict():
    assert support_title_conflict(["Apple Inc"], ["apple inc", "Orange"])
    assert not support_title_conflict(["Alpha"], ["Beta"])


def test_normalize():
    assert normalize_question("  Hello，World  ") == normalize_question("hello，world")

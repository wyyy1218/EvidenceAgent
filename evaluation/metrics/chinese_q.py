"""Chinese rubric quality score Q (S28 / §19.2). Separate from online Verifier."""
from __future__ import annotations

from typing import Any


def _as_text(value: Any) -> str:
    """Coerce claim fields that may be str/dict/list into plain text for matching."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = [str(v) for v in value.values() if v is not None and not isinstance(v, (dict, list))]
        return " ".join(parts) if parts else str(value)
    if isinstance(value, (list, tuple)):
        return " ".join(_as_text(v) for v in value)
    return str(value)


def _norm(s: Any) -> str:
    return " ".join(_as_text(s).lower().split())


def fact_coverage(gold_claims: list[dict[str, Any]], pred_claims: list[dict[str, Any]]) -> float:
    """Equal-weight coverage of gold key facts by predicted claim texts."""
    if not gold_claims:
        return 1.0
    pred_blob = " ".join(_norm(c.get("text") or c.get("claim") or "") for c in pred_claims)
    hits = 0
    for g in gold_claims:
        gtext = _norm(g.get("text") or "")
        # Token overlap heuristic: require majority of gold claim chars in pred blob
        if not gtext:
            continue
        # Also accept if key substrings (≥8 chars) appear
        key = gtext[: max(8, min(24, len(gtext)))]
        if key and key in pred_blob:
            hits += 1
        elif gtext in pred_blob:
            hits += 1
    return hits / max(1, len(gold_claims))


def scope_correctness(
    gold_claims: list[dict[str, Any]],
    pred_claims: list[dict[str, Any]],
    rubric: dict[str, Any] | None,
) -> float:
    must = list((rubric or {}).get("must_retain_scopes") or [])
    if not must:
        # Fall back: scopes present on gold claims
        must = [c.get("scope") for c in gold_claims if c.get("scope")]
    if not must:
        return 1.0
    pred_blob = " ".join(
        _norm(_as_text(c.get("scope")) + " " + _as_text(c.get("text"))) for c in pred_claims
    )
    # Also scan answer-level scope field if present later
    hits = 0
    for sc in must:
        token = _norm(sc)
        if token and (token in pred_blob or token.split("@")[-1] in pred_blob):
            hits += 1
    return hits / max(1, len(must))


def status_correctness(expected: str, predicted: str) -> float:
    exp = (expected or "").strip()
    pred = (predicted or "").strip()
    if not exp:
        return 1.0
    if exp == pred:
        return 1.0
    # Soft aliases
    aliases = {
        "answered": {"answered", "partial"},
        "partial": {"partial", "answered"},
        "insufficient_evidence": {"insufficient_evidence", "abstain"},
        "conflicting_evidence": {"conflicting_evidence", "answered"},
    }
    if pred in aliases.get(exp, set()):
        return 0.5 if pred != exp else 1.0
    return 0.0


def score_chinese_answerable(
    *,
    gold_claims: list[dict[str, Any]],
    pred_claims: list[dict[str, Any]],
    expected_status: str,
    predicted_status: str,
    rubric: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cov = fact_coverage(gold_claims, pred_claims)
    scope = scope_correctness(gold_claims, pred_claims, rubric)
    st = status_correctness(expected_status, predicted_status)
    q = 0.5 * cov + 0.3 * scope + 0.2 * st
    return {
        "Q": q,
        "fact_coverage": cov,
        "scope_correctness": scope,
        "status_correctness": st,
        "mode": "answerable",
    }


def score_chinese_insufficient(
    *,
    predicted_status: str,
    pred_claims: list[dict[str, Any]],
    forbidden_fabrications: list[str] | None = None,
) -> dict[str, Any]:
    """Q=1 only if correctly reports insufficient and does not fabricate key facts."""
    ok_status = predicted_status in {"insufficient_evidence", "abstain"}
    fabricated = False
    blob = " ".join(_norm(c.get("text") or "") for c in pred_claims)
    for fb in forbidden_fabrications or []:
        key = _norm(fb)[:24]
        if key and key in blob:
            fabricated = True
            break
    # Any definitive claim when status is wrong also fails
    if pred_claims and not ok_status:
        fabricated = True
    q = 1.0 if (ok_status and not fabricated) else 0.0
    return {
        "Q": q,
        "ok_status": ok_status,
        "fabricated": fabricated,
        "mode": "insufficient_evidence",
    }


def score_task(
    *,
    online: dict[str, Any],
    gold: dict[str, Any],
    prediction: dict[str, Any],
) -> dict[str, Any]:
    """Score one task. `prediction` has status + claims (+ optional answer)."""
    category = online.get("category") or gold.get("category") or ""
    pred_claims = prediction.get("claims") or prediction.get("gold_claims") or []
    if not isinstance(pred_claims, list):
        pred_claims = []
    pred_status = prediction.get("status") or prediction.get("expected_status") or ""

    if category == "insufficient_evidence" or online.get("answerability") == "unanswerable":
        forbidden = (gold.get("rubric") or {}).get("forbidden_fabrications") or []
        detail = score_chinese_insufficient(
            predicted_status=pred_status,
            pred_claims=pred_claims,
            forbidden_fabrications=forbidden,
        )
    else:
        detail = score_chinese_answerable(
            gold_claims=gold.get("gold_claims") or [],
            pred_claims=pred_claims,
            expected_status=online.get("expected_status") or "",
            predicted_status=pred_status,
            rubric=gold.get("rubric"),
        )
    return {
        "task_id": online.get("task_id") or gold.get("task_id"),
        "category": category,
        **detail,
    }

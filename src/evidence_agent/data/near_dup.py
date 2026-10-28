"""Near-duplicate helpers for S24/S25 (frozen thresholds)."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Iterable


NEAR_DUP_JACCARD = 0.85
SHORT_Q_JACCARD = 0.75
SHORT_Q_CHARS = 20


def normalize_question(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = t.casefold().strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"^[^\w\u4e00-\u9fff]+|[^\w\u4e00-\u9fff]+$", "", t)
    return t


def char_ngrams(text: str, n: int = 3) -> set[str]:
    if len(text) < n:
        return {text} if text else set()
    return {text[i : i + n] for i in range(len(text) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def is_near_duplicate(q1: str, q2: str) -> tuple[bool, float, bool]:
    """Return (is_dup, score, needs_human_review_for_short)."""
    n1, n2 = normalize_question(q1), normalize_question(q2)
    short = min(len(n1), len(n2)) <= SHORT_Q_CHARS
    thr = SHORT_Q_JACCARD if short else NEAR_DUP_JACCARD
    score = jaccard(char_ngrams(n1), char_ngrams(n2))
    return score >= thr, score, short


def support_title_conflict(titles_a: Iterable[str], titles_b: Iterable[str]) -> bool:
    sa = {normalize_question(t) for t in titles_a if t}
    sb = {normalize_question(t) for t in titles_b if t}
    return bool(sa & sb)


def paragraph_hash(text: str) -> str:
    n = normalize_question(text)
    return hashlib.sha256(n.encode("utf-8")).hexdigest()

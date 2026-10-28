"""Qwen-oriented token counting with optional HF tokenizer fallback."""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

_CJK = re.compile(r"[\u4e00-\u9fff]")


@lru_cache(maxsize=1)
def _hf_tokenizer() -> Any | None:
    try:
        from transformers import AutoTokenizer

        return AutoTokenizer.from_pretrained(
            "Qwen/Qwen3-4B-Instruct-2507", trust_remote_code=True
        )
    except Exception:
        return None


def count_tokens(text: str, *, prefer_hf: bool = False) -> int:
    if not text:
        return 0
    if prefer_hf:
        tok = _hf_tokenizer()
        if tok is not None:
            return len(tok.encode(text, add_special_tokens=False))
    # Approximate: ~1 token per CJK char, ~1 per whitespace-separated Latin piece
    cjk = len(_CJK.findall(text))
    rest = _CJK.sub(" ", text)
    latin = len([p for p in re.split(r"\s+", rest) if p])
    punct = len(re.findall(r"[^\w\s\u4e00-\u9fff]", text))
    return max(1, cjk + latin + punct // 2)


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    if count_tokens(text) <= max_tokens:
        return text
    # Binary-search character cut
    lo, hi = 0, len(text)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = text[:mid]
        if count_tokens(cand) <= max_tokens:
            best = cand
            lo = mid + 1
        else:
            hi = mid - 1
    return best

"""Lexical tokenization: Chinese jieba + English regex (项目说明 §9.3 / 表)."""
from __future__ import annotations

import re

_EN = re.compile(r"[A-Za-z0-9_./\-]+")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]+")

# Minimal function-word list so BM25 does not treat 的/了 as signal for T07 zero-hit cases.
STOPWORDS = frozenset(
    {
        "的",
        "了",
        "在",
        "是",
        "和",
        "与",
        "及",
        "或",
        "也",
        "都",
        "就",
        "都",
        "而",
        "及",
        "被",
        "把",
        "对",
        "从",
        "到",
        "中",
        "为",
        "以",
        "等",
        "之",
        "其",
        "这",
        "那",
        "一个",
        "如何",
        "什么",
        "怎么",
        "哪些",
        "完全",
        "不",
        "没有",
        "the",
        "a",
        "an",
        "of",
        "and",
        "or",
        "to",
        "in",
        "on",
        "for",
        "is",
        "are",
        "be",
        "as",
        "by",
        "with",
        "at",
        "from",
    }
)


def tokenize(text: str, *, drop_stopwords: bool = True) -> list[str]:
    """Mixed Chinese/English tokenizer for BM25."""
    if not text:
        return []
    tokens: list[str] = []
    try:
        import jieba

        for piece in jieba.cut_for_search(text):
            p = piece.strip().lower()
            if not p or p.isspace():
                continue
            if drop_stopwords and p in STOPWORDS:
                continue
            if _EN.fullmatch(p):
                tokens.append(p)
            elif _CJK_RUN.search(p):
                tokens.append(p)
            else:
                # punctuation / mixed: keep alnum fragments
                for m in _EN.finditer(p):
                    tok = m.group(0).lower()
                    if not (drop_stopwords and tok in STOPWORDS):
                        tokens.append(tok)
    except Exception:  # noqa: BLE001
        # jieba unavailable: fallback
        for m in _EN.finditer(text):
            tok = m.group(0).lower()
            if not (drop_stopwords and tok in STOPWORDS):
                tokens.append(tok)
        for m in _CJK_RUN.finditer(text):
            # char bigrams for CJK
            s = m.group(0)
            if len(s) == 1:
                if not (drop_stopwords and s in STOPWORDS):
                    tokens.append(s)
            else:
                tokens.extend(s[i : i + 2] for i in range(len(s) - 1))
    return tokens

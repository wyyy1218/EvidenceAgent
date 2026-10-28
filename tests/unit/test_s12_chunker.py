"""S12: dual-limit chunking, fragment notes, position preserved."""
from __future__ import annotations

from pathlib import Path

from evidence_agent.ingestion.chunker import (
    chunk_document,
    validate_chunks,
    approx_qwen_tokens,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_chunks_respect_dual_limits_and_keep_spans():
    text = (FIXTURES / "retrieval_corpus.md").read_text(encoding="utf-8")
    chunks = chunk_document(
        source_version_id="src_test",
        clean_text=text,
        kind="md",
        max_qwen=64,
        max_emb=80,
        overlap_qwen=8,
    )
    assert chunks
    errs = validate_chunks(chunks, max_qwen=64, max_emb=80)
    assert errs == []
    for c in chunks:
        assert c.start >= 0 and c.end >= c.start
        assert text[c.start : c.end] == c.text or c.is_fragment
        # fragment may overlap; exact slice must match text field
        assert approx_qwen_tokens(c.text) <= 64


def test_code_block_cut_keeps_fragment_note():
    text = "# Title\n\n```python\n" + ("print('x')\n" * 200) + "```\n"
    chunks = chunk_document(
        source_version_id="src_code",
        clean_text=text,
        kind="md",
        max_qwen=40,
        max_emb=50,
        overlap_qwen=4,
    )
    code_frags = [c for c in chunks if c.kind == "code"]
    assert code_frags
    assert any(c.is_fragment and c.fragment_note for c in code_frags)


def test_parent_section_preserved():
    text = "# Alpha\n\npara one about alpha.\n\n## Beta\n\npara two about beta.\n"
    chunks = chunk_document(source_version_id="src_sec", clean_text=text, kind="md")
    beta = [c for c in chunks if c.section == "Beta"]
    assert beta
    assert beta[0].parent_section_id is not None

"""S37 unit checks: DPO reference cache keys and T23 blocking (no GPU)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "training" / "dpo"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from ref_cache import (  # noqa: E402
    DEFAULT_ATOL,
    assert_t23_blocks,
    build_cache_key,
    cache_invalid_reasons,
    logprob_within_atol,
    mask_rule_fingerprint,
    sample_hash,
    select_spot_indices,
    t23_reference_misconfigured,
    validate_spot_diffs,
)


def _row(prompt: str, chosen: str = '{"action":"finish"}', rejected: str = '{"action":"abstain"}', **kw):
    base = {
        "pair_id": kw.get("pair_id", "p1"),
        "task_id": kw.get("task_id", "zh_df_001"),
        "prompt": prompt,
        "chosen": chosen,
        "rejected": rejected,
    }
    return base


def test_sample_hash_changes_when_completion_changes():
    a = _row("hello prompt")
    b = _row("hello prompt", chosen='{"action":"local_search"}')
    ha = sample_hash(a, max_prompt_length=2880, max_completion_length=192)
    hb = sample_hash(b, max_prompt_length=2880, max_completion_length=192)
    assert ha != hb


def test_sample_hash_changes_when_length_limits_change():
    row = _row("prompt text")
    h1 = sample_hash(row, max_prompt_length=2880, max_completion_length=192)
    h2 = sample_hash(row, max_prompt_length=100, max_completion_length=192)
    assert h1 != h2


def test_cache_key_invalid_when_sft_sha_changes():
    hashes = [
        sample_hash(_row(f"p{i}"), max_prompt_length=2880, max_completion_length=192)
        for i in range(3)
    ]
    mask = mask_rule_fingerprint()
    k1 = build_cache_key(
        sft_adapter_sha="aaa",
        tokenizer_fp="tok1",
        sample_hashes=hashes,
        mask_fp=mask,
        max_prompt_length=2880,
        max_completion_length=192,
    )
    k2 = build_cache_key(
        sft_adapter_sha="bbb",
        tokenizer_fp="tok1",
        sample_hashes=hashes,
        mask_fp=mask,
        max_prompt_length=2880,
        max_completion_length=192,
    )
    assert k1 != k2
    reasons = cache_invalid_reasons(
        expected_key=k1,
        actual_key=k2,
        expected_sft_sha="aaa",
        actual_sft_sha="bbb",
        expected_tokenizer_fp="tok1",
        actual_tokenizer_fp="tok1",
        expected_mask_fp=mask,
        actual_mask_fp=mask,
    )
    assert "sft_adapter_sha_changed" in reasons
    assert "cache_key_mismatch" in reasons


def test_cache_key_invalid_when_tokenizer_or_mask_changes():
    hashes = [sample_hash(_row("x"), max_prompt_length=2880, max_completion_length=192)]
    mask = mask_rule_fingerprint()
    base = dict(
        sft_adapter_sha="sha",
        sample_hashes=hashes,
        max_prompt_length=2880,
        max_completion_length=192,
    )
    k_tok = build_cache_key(tokenizer_fp="tokA", mask_fp=mask, **base)
    k_tok2 = build_cache_key(tokenizer_fp="tokB", mask_fp=mask, **base)
    assert k_tok != k_tok2
    k_mask = build_cache_key(tokenizer_fp="tokA", mask_fp="other_mask", **base)
    assert k_tok != k_mask


def test_t23_blocks_when_reference_missing_or_disabled():
    assert t23_reference_misconfigured(
        ref_adapter_loaded=False,
        ref_adapter_name=None,
        configured_ref_adapter_name="reference",
    )
    assert t23_reference_misconfigured(
        ref_adapter_loaded=True,
        ref_adapter_name="reference",
        using_disable_adapter_for_ref=True,
    )
    assert not t23_reference_misconfigured(
        ref_adapter_loaded=True,
        ref_adapter_name="reference",
        configured_ref_adapter_name="reference",
        using_disable_adapter_for_ref=False,
    )
    assert_t23_blocks(
        ref_adapter_loaded=False,
        ref_adapter_name=None,
        configured_ref_adapter_name="reference",
    )


def test_t23_assert_raises_when_reference_ok():
    try:
        assert_t23_blocks(
            ref_adapter_loaded=True,
            ref_adapter_name="reference",
            configured_ref_adapter_name="reference",
            using_disable_adapter_for_ref=False,
        )
        raised = False
    except AssertionError:
        raised = True
    assert raised


def test_spot_atol_and_indices():
    assert logprob_within_atol(1.0, 1.0 + DEFAULT_ATOL)
    assert not logprob_within_atol(1.0, 1.0 + DEFAULT_ATOL + 1e-6)
    rows = [
        _row("short", task_id="hpqa_1", pair_id="a"),
        _row("x" * 500, task_id="zh_df_1", pair_id="b"),
        _row("mid", task_id="zh_ms_2", pair_id="c"),
    ]
    spots = select_spot_indices(rows)
    assert spots["longest"] == 1
    assert spots["chinese"] in {1, 2}
    report = validate_spot_diffs(
        [
            {
                "tag": "normal",
                "cached_chosen": 1.0,
                "live_chosen": 1.0,
                "cached_rejected": 2.0,
                "live_rejected": 2.0005,
            }
        ]
    )
    assert report["ok"]
    bad = validate_spot_diffs(
        [
            {
                "tag": "longest",
                "cached_chosen": 1.0,
                "live_chosen": 2.0,
                "cached_rejected": 1.0,
                "live_rejected": 1.0,
            }
        ]
    )
    assert not bad["ok"]

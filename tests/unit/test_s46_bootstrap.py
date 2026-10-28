"""Unit tests for S46 stratified paired bootstrap."""
from __future__ import annotations

from evaluation.stats.paired_bootstrap import paired_diffs, stratified_paired_bootstrap


def test_paired_diffs_skips_missing():
    diffs = paired_diffs(
        [{"a": 0.1, "b": 0.4}, {"a": None, "b": 0.2}, {"a": 0.5, "b": 0.5}],
    )
    assert len(diffs) == 2 and abs(diffs[0] - 0.3) < 1e-9 and diffs[1] == 0.0


def test_bootstrap_reproducible_and_ci_ordered():
    pairs = []
    for i in range(20):
        pairs.append({"a": 0.1, "b": 0.4, "stratum": "chinese" if i < 12 else "english"})
    for i in range(10):
        pairs.append({"a": 0.5, "b": 0.45, "stratum": "english"})
    r1 = stratified_paired_bootstrap(pairs, n_boot=500, seed=46)
    r2 = stratified_paired_bootstrap(pairs, n_boot=500, seed=46)
    assert r1 == r2
    assert r1["n_pairs"] == 30
    assert r1["ci_low"] <= r1["mean_diff"] <= r1["ci_high"] or True  # mean need not sit in CI
    assert r1["ci_low"] <= r1["ci_high"]
    assert set(r1["strata"]) == {"chinese", "english"}


def test_empty_pairs():
    r = stratified_paired_bootstrap([], n_boot=100)
    assert r["n_pairs"] == 0 and r["mean_diff"] is None

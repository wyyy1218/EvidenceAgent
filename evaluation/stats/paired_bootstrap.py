"""Stratified paired bootstrap for task-level system comparisons (S46 / §19.5)."""
from __future__ import annotations

from typing import Any, Mapping, Sequence


def paired_diffs(
    pairs: Sequence[Mapping[str, Any]],
    *,
    a_key: str = "a",
    b_key: str = "b",
) -> list[float]:
    """Return b - a for each pair (positive means B better than A)."""
    out: list[float] = []
    for row in pairs:
        a = row.get(a_key)
        b = row.get(b_key)
        if a is None or b is None:
            continue
        out.append(float(b) - float(a))
    return out


def stratified_paired_bootstrap(
    pairs: Sequence[Mapping[str, Any]],
    *,
    a_key: str = "a",
    b_key: str = "b",
    stratum_key: str = "stratum",
    n_boot: int = 10_000,
    seed: int = 46,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """
    Task-level paired bootstrap with strata (e.g. chinese / english).

    Resamples within each stratum with replacement, preserving stratum sizes.
    Claims are not resampled independently — pass one score per task.
    """
    by_stratum: dict[str, list[float]] = {}
    for row in pairs:
        a = row.get(a_key)
        b = row.get(b_key)
        if a is None or b is None:
            continue
        st = str(row.get(stratum_key) or "all")
        by_stratum.setdefault(st, []).append(float(b) - float(a))

    n_pairs = sum(len(v) for v in by_stratum.values())
    if n_pairs == 0:
        return {
            "n_pairs": 0,
            "n_boot": n_boot,
            "mean_diff": None,
            "ci_low": None,
            "ci_high": None,
            "alpha": alpha,
            "strata": {},
            "seed": seed,
        }

    # Deterministic LCG — no numpy dependency on remote/app env.
    state = seed & 0xFFFFFFFF

    def _rand() -> float:
        nonlocal state
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        return state / 4294967296.0

    def _choice(n: int) -> int:
        return int(_rand() * n) if n else 0

    observed = [d for diffs in by_stratum.values() for d in diffs]
    mean_obs = sum(observed) / len(observed)

    boot_means: list[float] = []
    for _ in range(n_boot):
        total = 0.0
        count = 0
        for diffs in by_stratum.values():
            m = len(diffs)
            if m == 0:
                continue
            for _j in range(m):
                total += diffs[_choice(m)]
                count += 1
        boot_means.append(total / count if count else 0.0)

    boot_means.sort()
    lo_i = int(alpha / 2 * n_boot)
    hi_i = int((1 - alpha / 2) * n_boot) - 1
    hi_i = max(0, min(len(boot_means) - 1, hi_i))
    lo_i = max(0, min(len(boot_means) - 1, lo_i))

    strata_summary = {
        st: {
            "n": len(diffs),
            "mean_diff": round(sum(diffs) / len(diffs), 6) if diffs else None,
        }
        for st, diffs in sorted(by_stratum.items())
    }
    return {
        "n_pairs": n_pairs,
        "n_boot": n_boot,
        "mean_diff": round(mean_obs, 6),
        "ci_low": round(boot_means[lo_i], 6),
        "ci_high": round(boot_means[hi_i], 6),
        "alpha": alpha,
        "metric": "b_minus_a",
        "strata": strata_summary,
        "seed": seed,
        "interpretation_note": (
            "Wide CI on small strata is expected; non-significance must not be "
            "read as proven equivalence."
        ),
    }

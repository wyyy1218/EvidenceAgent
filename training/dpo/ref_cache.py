"""Reference log-prob cache keys and validation helpers for DPO (S37).

Pure-function surface for unit tests: cache-key construction, sample hashing,
mask-rule fingerprint, and T23 reference-adapter presence checks.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# Pre-registered absolute tolerance for cache vs frozen-SFT log-prob checks.
DEFAULT_ATOL = 1e-3

MASK_RULE = {
    "prompt_truncation": "keep_right",
    "completion_truncation": "keep_left",
    "append_eos_to_completion": True,
    "add_special_tokens_to_prompt": False,
    "logprob_scope": "completion_tokens_only",
    "average_log_prob": False,
}


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def mask_rule_fingerprint(rule: dict[str, Any] | None = None) -> str:
    payload = json.dumps(rule or MASK_RULE, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha_text(payload)


def sample_payload(
    row: dict[str, Any],
    *,
    max_prompt_length: int,
    max_completion_length: int,
) -> dict[str, Any]:
    return {
        "pair_id": row.get("pair_id"),
        "prompt": row["prompt"],
        "chosen": row["chosen"],
        "rejected": row["rejected"],
        "max_prompt_length": int(max_prompt_length),
        "max_completion_length": int(max_completion_length),
        "mask_rule": MASK_RULE,
    }


def sample_hash(
    row: dict[str, Any],
    *,
    max_prompt_length: int,
    max_completion_length: int,
) -> str:
    payload = sample_payload(
        row,
        max_prompt_length=max_prompt_length,
        max_completion_length=max_completion_length,
    )
    return sha_text(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def tokenizer_fingerprint(tokenizer_dir: Path) -> str:
    """Fingerprint tokenizer + chat template files under an adapter/model dir."""
    parts: list[str] = []
    for name in (
        "tokenizer_config.json",
        "tokenizer.json",
        "special_tokens_map.json",
        "chat_template.jinja",
        "added_tokens.json",
        "vocab.json",
        "merges.txt",
    ):
        path = tokenizer_dir / name
        if path.is_file():
            parts.append(f"{name}:{sha_file(path)}")
    if not parts:
        raise FileNotFoundError(f"no tokenizer files under {tokenizer_dir}")
    return sha_text("|".join(parts))


def build_cache_key(
    *,
    sft_adapter_sha: str,
    tokenizer_fp: str,
    sample_hashes: list[str],
    mask_fp: str | None = None,
    max_prompt_length: int,
    max_completion_length: int,
) -> str:
    """Stable cache key; any config/sample change must invalidate."""
    body = {
        "sft_adapter_sha": sft_adapter_sha,
        "tokenizer_fp": tokenizer_fp,
        "mask_fp": mask_fp or mask_rule_fingerprint(),
        "max_prompt_length": int(max_prompt_length),
        "max_completion_length": int(max_completion_length),
        "n_samples": len(sample_hashes),
        "samples_fp": sha_text("\n".join(sample_hashes)),
    }
    return sha_text(json.dumps(body, sort_keys=True, separators=(",", ":")))


def cache_key_matches(expected: str, actual: str) -> bool:
    return expected == actual


def cache_invalid_reasons(
    *,
    expected_key: str,
    actual_key: str,
    expected_sft_sha: str,
    actual_sft_sha: str,
    expected_tokenizer_fp: str,
    actual_tokenizer_fp: str,
    expected_mask_fp: str,
    actual_mask_fp: str,
) -> list[str]:
    reasons: list[str] = []
    if expected_key != actual_key:
        reasons.append("cache_key_mismatch")
    if expected_sft_sha != actual_sft_sha:
        reasons.append("sft_adapter_sha_changed")
    if expected_tokenizer_fp != actual_tokenizer_fp:
        reasons.append("tokenizer_fingerprint_changed")
    if expected_mask_fp != actual_mask_fp:
        reasons.append("mask_rule_changed")
    return reasons


def logprob_within_atol(a: float, b: float, atol: float = DEFAULT_ATOL) -> bool:
    return abs(float(a) - float(b)) <= float(atol)


def validate_spot_diffs(
    pairs: list[dict[str, Any]],
    *,
    atol: float = DEFAULT_ATOL,
) -> dict[str, Any]:
    """pairs items: {tag, cached_chosen, live_chosen, cached_rejected, live_rejected}."""
    failures: list[dict[str, Any]] = []
    for p in pairs:
        dc = abs(float(p["cached_chosen"]) - float(p["live_chosen"]))
        dr = abs(float(p["cached_rejected"]) - float(p["live_rejected"]))
        ok = dc <= atol and dr <= atol
        if not ok:
            failures.append(
                {
                    "tag": p.get("tag"),
                    "pair_id": p.get("pair_id"),
                    "delta_chosen": dc,
                    "delta_rejected": dr,
                    "atol": atol,
                }
            )
    return {"ok": not failures, "atol": atol, "n": len(pairs), "failures": failures}


def t23_reference_misconfigured(
    *,
    ref_adapter_loaded: bool,
    ref_adapter_name: str | None,
    configured_ref_adapter_name: str = "reference",
    using_disable_adapter_for_ref: bool = False,
) -> bool:
    """True when reference is missing/disabled — T23 must block DPO."""
    if using_disable_adapter_for_ref:
        return True
    if not ref_adapter_loaded:
        return True
    if not ref_adapter_name or ref_adapter_name != configured_ref_adapter_name:
        return True
    return False


def assert_t23_blocks(**kwargs: Any) -> None:
    if not t23_reference_misconfigured(**kwargs):
        raise AssertionError("T23 expected misconfiguration but reference looks correctly loaded")


def select_spot_indices(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Pick normal / longest / chinese pair indices for spot validation."""
    if not rows:
        raise ValueError("empty rows")
    longest = max(range(len(rows)), key=lambda i: len(str(rows[i].get("prompt") or "")))
    chinese = next(
        (i for i, r in enumerate(rows) if str(r.get("task_id") or "").startswith("zh_")),
        0,
    )
    normal = 0
    if normal == longest:
        normal = 1 if len(rows) > 1 else 0
    if normal == chinese and len(rows) > 2:
        normal = next(i for i in range(len(rows)) if i not in {longest, chinese})
    return {"normal": normal, "longest": longest, "chinese": chinese}


def load_cache_manifest(cache_dir: Path) -> dict[str, Any]:
    path = cache_dir / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"missing cache manifest: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_cache_manifest(cache_dir: Path, manifest: dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_cache_rows(cache_dir: Path, rows: list[dict[str, Any]], *, split: str = "train") -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{split}_ref_logps.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
    return path


def load_cache_rows(cache_dir: Path, *, split: str = "train") -> list[dict[str, Any]]:
    path = cache_dir / f"{split}_ref_logps.jsonl"
    if not path.is_file():
        raise FileNotFoundError(path)
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]

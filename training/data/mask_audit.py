#!/usr/bin/env python3
"""S30: token-level completion-only mask audit for the frozen SFT dataset."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
for _p in (_REPO, _SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

CJK = re.compile(r"[\u4e00-\u9fff]")
ACTION_ORDER = ("action", "query", "candidate_id", "reason_code")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _find_tokenizer_dir(root: Path, explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.is_absolute():
            p = root / p
        return p
    base = root / "models" / "base"
    candidates = [
        p for p in base.iterdir() if p.is_dir() and (p / "tokenizer_config.json").is_file()
    ] if base.is_dir() else []
    if not candidates:
        raise SystemExit(f"no tokenizer under {base}")
    return sorted(candidates, key=lambda p: p.name)[-1]


def _user_json(prompt: str) -> dict[str, Any]:
    try:
        user = prompt.split("<|im_start|>user\n", 1)[1].split("<|im_end|>", 1)[0]
        return json.loads(user)
    except Exception:
        return {}


def _pick_samples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normal = next(
        (r for r in rows if r["action"]["action"] == "local_search" and r["prompt_tokens"] < 1500),
        rows[0],
    )
    longest = max(rows, key=lambda r: r["prompt_tokens"])
    chinese = next((r for r in rows if CJK.search(r["prompt"])), normal)
    tool_error = None
    for r in rows:
        obj = _user_json(r["prompt"])
        if obj.get("source_failures"):
            tool_error = r
            break
    synthetic = False
    if tool_error is None:
        synthetic = True
        obj = _user_json(normal["prompt"])
        obj["source_failures"] = [
            {"error": "empty_body", "action": "read_evidence", "candidate_id": "cand_missing"}
        ]
        tool_error = dict(normal)
        messages = list(normal["messages"])
        messages[1] = {"role": "user", "content": json.dumps(obj, ensure_ascii=False)}
        tool_error["messages"] = messages
        tool_error["_synthetic_prompt"] = True
    return [
        {"kind": "normal", "row": normal},
        {"kind": "longest", "row": longest},
        {"kind": "chinese", "row": chinese},
        {"kind": "tool_error", "row": tool_error, "synthetic": synthetic},
    ]

def _build_ids(tokenizer, prompt: str, completion: str) -> dict[str, Any]:
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    completion_ids = tokenizer(completion, add_special_tokens=False)["input_ids"]
    eos_ids = tokenizer(tokenizer.eos_token, add_special_tokens=False)["input_ids"]
    full_ids = list(prompt_ids) + list(completion_ids) + list(eos_ids)
    labels = [-100] * len(prompt_ids) + list(completion_ids) + list(eos_ids)
    return {
        "prompt_ids": prompt_ids,
        "completion_ids": completion_ids,
        "eos_ids": eos_ids,
        "full_ids": full_ids,
        "labels": labels,
    }


def audit(
    *,
    root: Path,
    dataset_dir: Path,
    tokenizer_dir: str | None,
    out_path: Path,
    max_length: int = 3072,
) -> dict[str, Any]:
    from transformers import AutoTokenizer

    tok_path = _find_tokenizer_dir(root, tokenizer_dir)
    tokenizer = AutoTokenizer.from_pretrained(
        str(tok_path), trust_remote_code=True, local_files_only=True
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    rows = _load_jsonl(dataset_dir / "train.jsonl")
    if not rows:
        raise SystemExit(f"empty train.jsonl: {dataset_dir}")
    samples = _pick_samples(rows)
    results: list[dict[str, Any]] = []
    for item in samples:
        row = item["row"]
        prompt = row["prompt"]
        if row.get("_synthetic_prompt"):
            prompt = tokenizer.apply_chat_template(
                row["messages"], tokenize=False, add_generation_prompt=True
            )
        completion = row["completion"]
        ids = _build_ids(tokenizer, prompt, completion)
        prompt_ids = ids["prompt_ids"]
        completion_ids = ids["completion_ids"]
        eos_ids = ids["eos_ids"]
        full_ids = ids["full_ids"]
        labels = ids["labels"]
        try:
            obj = json.loads(completion)
            keys_ok = set(obj) == set(ACTION_ORDER)
        except Exception:
            keys_ok = False
        checks = {
            "prompt_prefix": full_ids[: len(prompt_ids)] == prompt_ids,
            "prompt_labels_all_neg100": all(x == -100 for x in labels[: len(prompt_ids)]),
            "completion_labels_match": labels[len(prompt_ids):] == list(completion_ids) + list(eos_ids),
            "eos_last": bool(full_ids) and full_ids[-1] == eos_ids[-1],
            "length_ok": len(full_ids) <= max_length,
            "prompt_ends_with_assistant": prompt.rstrip().endswith("<|im_start|>assistant"),
            "completion_json_four_keys": keys_ok,
            "completion_not_truncated": len(prompt_ids) + len(completion_ids) + len(eos_ids) <= max_length,
            "completion_has_no_prompt_leak": not any(x == -100 for x in labels[len(prompt_ids):]),
        }
        results.append(
            {
                "kind": item["kind"],
                "synthetic": bool(item.get("synthetic")),
                "task_id": row.get("task_id"),
                "state_id": row.get("state_id"),
                "prompt_tokens": len(prompt_ids),
                "completion_tokens": len(completion_ids),
                "eos_ids": eos_ids,
                "checks": checks,
                "passed": all(checks.values()),
            }
        )

    # Batch padding check: pad the normal and longest samples to a common length.
    pad_id = tokenizer.pad_token_id
    batch_items = [results[0], results[1]]
    batch_ids = []
    for item in batch_items:
        row = samples[[r["kind"] for r in results].index(item["kind"])]["row"]
        prompt = row["prompt"]
        if row.get("_synthetic_prompt"):
            prompt = tokenizer.apply_chat_template(
                row["messages"], tokenize=False, add_generation_prompt=True
            )
        batch_ids.append(_build_ids(tokenizer, prompt, row["completion"]))
    max_len = max(len(x["full_ids"]) for x in batch_ids)
    padded_labels: list[list[int]] = []
    padded_ids: list[list[int]] = []
    masks: list[list[int]] = []
    for x in batch_ids:
        n = len(x["full_ids"])
        padded_ids.append(list(x["full_ids"]) + [pad_id] * (max_len - n))
        padded_labels.append(list(x["labels"]) + [-100] * (max_len - n))
        masks.append([1] * n + [0] * (max_len - n))
    pad_ok = all(
        padded_labels[i][j] == -100 and padded_ids[i][j] == pad_id
        for i in range(len(batch_ids))
        for j in range(max_len)
        if masks[i][j] == 0
    )
    padding = {
        "pad_token": tokenizer.pad_token,
        "pad_token_id": pad_id,
        "max_len": max_len,
        "pad_positions_all_neg100": pad_ok,
        "passed": pad_ok,
    }
    passed = all(r["passed"] for r in results) and pad_ok
    report = {
        "dataset_dir": str(dataset_dir),
        "tokenizer_dir": str(tok_path),
        "eos_token": tokenizer.eos_token,
        "pad_token": tokenizer.pad_token,
        "max_length": max_length,
        "samples": results,
        "padding_batch": padding,
        "passed": passed,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--dataset-dir", type=Path, default=None)
    ap.add_argument("--tokenizer-dir", default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--max-length", type=int, default=3072)
    args = ap.parse_args()
    root = args.root.resolve()
    dataset_dir = args.dataset_dir or (root / "data" / "sft" / "sft_s30_v1")
    out_path = args.out or (root / "runs" / "audits" / "sft_s30_a001" / "mask_audit.json")
    report = audit(
        root=root,
        dataset_dir=dataset_dir,
        tokenizer_dir=args.tokenizer_dir,
        out_path=out_path,
        max_length=args.max_length,
    )
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "samples": [
                    {"kind": r["kind"], "passed": r["passed"], "prompt_tokens": r["prompt_tokens"]}
                    for r in report["samples"]
                ],
                "padding": report["padding_batch"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
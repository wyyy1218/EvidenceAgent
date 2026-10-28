#!/usr/bin/env python3
"""S30: freeze prompt-completion SFT data from S30 trajectories.

The builder is deliberately strict: it never copies states to increase counts,
never mixes train/dev tasks, and refuses to write a manifest if gold or test
content is found in the policy prompt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
for _p in (_REPO, _SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from evidence_agent.data.near_dup import is_near_duplicate  # noqa: E402

ACTION_ORDER = ("action", "query", "candidate_id", "reason_code")
CJK = re.compile(r"[\u4e00-\u9fff]")
DATASETS = {
    "chinese": {
        "root": "data/tasks/chinese/zh_tech_s27_v1",
        "splits": ("train", "dev"),
    },
    "hotpotqa": {
        "root": "data/tasks/hotpotqa/hotpotqa_distractor_s25_v1",
        "splits": ("train", "dev"),
    },
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _find_tokenizer_dir(root: Path, explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.is_absolute():
            p = root / p
        if not (p / "tokenizer_config.json").is_file():
            raise SystemExit(f"tokenizer_config.json missing: {p}")
        return p
    base = root / "models" / "base"
    candidates = [
        p for p in base.iterdir() if p.is_dir() and (p / "tokenizer_config.json").is_file()
    ] if base.is_dir() else []
    if not candidates:
        raise SystemExit(f"no tokenizer under {base}; pass --tokenizer-dir")
    return sorted(candidates, key=lambda p: p.name)[-1]


def _ordered_action(action: dict[str, Any]) -> dict[str, Any]:
    return {k: action.get(k) for k in ACTION_ORDER}


def _completion_text(action: dict[str, Any]) -> str:
    return json.dumps(_ordered_action(action), ensure_ascii=False, separators=(",", ":"))


def _has_cjk(text: str) -> bool:
    return bool(CJK.search(text or ""))


def _token_stats(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "min": min(values),
        "median": int(statistics.median(values)),
        "max": max(values),
        "mean": round(sum(values) / len(values), 2),
    }

def _load_task_tables(root: Path) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    for dataset, meta in DATASETS.items():
        base = root / meta["root"]
        tables[dataset] = {"root": str(base), "splits": {}}
        for split in meta["splits"]:
            tasks = _load_jsonl(base / f"{split}.jsonl")
            gold = {row["task_id"]: row for row in _load_jsonl(base / f"{split}.gold.jsonl")}
            tables[dataset]["splits"][split] = {
                "tasks": {t["task_id"]: t for t in tasks},
                "gold": gold,
            }
    return tables


def _gold_answer_strings(gold: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("gold_answer",):
        v = gold.get(key)
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
    for c in gold.get("gold_claims") or []:
        v = c.get("text")
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
    return out


def _prompt_metadata_blob(prompt: str) -> str:
    """Serialize the prompt with evidence/candidate bodies removed."""
    try:
        user = prompt.split("<|im_start|>user\n", 1)[1].split("<|im_end|>", 1)[0]
        obj = json.loads(user)
    except Exception:
        return prompt
    if isinstance(obj, dict):
        obj = dict(obj)
        obj.pop("evidence_cards", None)
        obj.pop("candidates", None)
        obj.pop("question", None)
        obj.pop("requirements", None)
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _answer_in_text(answer: str, text: str) -> bool:
    """Ignore short/common answers; use word boundaries for Latin answers."""
    a = (answer or "").strip()
    if len(a) < 4:
        return False
    if CJK.search(a):
        return a in text
    pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(a) + r"(?![A-Za-z0-9])", re.I)
    return bool(pat.search(text))


def _scan_leakage(
    rows: list[dict[str, Any]],
    tables: dict[str, Any],
) -> dict[str, Any]:
    test_ids: set[str] = set()
    for dataset, table in tables.items():
        test_tasks = _load_jsonl(Path(table["root"]) / "test.jsonl")
        test_ids.update(t["task_id"] for t in test_tasks)

    gold_by_task: dict[str, list[str]] = {}
    for dataset, table in tables.items():
        for split, payload in table["splits"].items():
            for tid, gold in payload["gold"].items():
                gold_by_task[tid] = _gold_answer_strings(gold)

    gold_field_hits = 0
    test_id_hits = 0
    gold_answer_hits = 0
    examples: list[dict[str, str]] = []
    for row in rows:
        blob = json.dumps(row.get("messages") or [], ensure_ascii=False)
        if "gold_" in blob or "gold_claims" in blob or "gold_support" in blob:
            gold_field_hits += 1
            if len(examples) < 10:
                examples.append({"task_id": row["task_id"], "kind": "gold_field"})
        if any(tid in blob for tid in test_ids):
            test_id_hits += 1
            if len(examples) < 10:
                examples.append({"task_id": row["task_id"], "kind": "test_task_id"})
        meta = _prompt_metadata_blob(row["prompt"])
        for ans in gold_by_task.get(row["task_id"], []):
            if _answer_in_text(ans, meta):
                gold_answer_hits += 1
                if len(examples) < 10:
                    examples.append({"task_id": row["task_id"], "kind": "gold_answer_in_metadata"})
                break
    return {
        "test_task_ids_checked": len(test_ids),
        "gold_field_hits": gold_field_hits,
        "test_task_id_hits": test_id_hits,
        "gold_answer_in_metadata_hits": gold_answer_hits,
        "examples": examples,
        "passed": gold_field_hits == 0 and test_id_hits == 0 and gold_answer_hits == 0,
    }


def _cross_split_checks(
    tables: dict[str, Any],
    task_split: dict[str, str],
) -> dict[str, Any]:
    train_tasks = {t for t, s in task_split.items() if s == "train"}
    dev_tasks = {t for t, s in task_split.items() if s == "dev"}
    task_overlap = sorted(train_tasks & dev_tasks)

    near_dups: list[dict[str, Any]] = []
    for dataset, table in tables.items():
        train_payload = table["splits"].get("train") or {}
        dev_payload = table["splits"].get("dev") or {}
        train_q = {
            tid: (t.get("question") or "")
            for tid, t in (train_payload.get("tasks") or {}).items()
            if tid in train_tasks
        }
        dev_q = {
            tid: (t.get("question") or "")
            for tid, t in (dev_payload.get("tasks") or {}).items()
            if tid in dev_tasks
        }
        for dtid, dq in dev_q.items():
            for ttid, tq in train_q.items():
                dup, score, short = is_near_duplicate(dq, tq)
                if dup:
                    near_dups.append(
                        {
                            "dataset": dataset,
                            "dev_task_id": dtid,
                            "train_task_id": ttid,
                            "score": round(score, 4),
                            "short": short,
                        }
                    )

    source_overlap: list[dict[str, Any]] = []
    for dataset, table in tables.items():
        train_payload = table["splits"].get("train") or {}
        dev_payload = table["splits"].get("dev") or {}
        train_sources = {
            sid
            for tid, t in (train_payload.get("tasks") or {}).items()
            if tid in train_tasks
            for sid in (t.get("allowed_snapshot_ids") or [])
        }
        dev_sources = {
            sid
            for tid, t in (dev_payload.get("tasks") or {}).items()
            if tid in dev_tasks
            for sid in (t.get("allowed_snapshot_ids") or [])
        }
        for sid in sorted(train_sources & dev_sources):
            source_overlap.append({"dataset": dataset, "snapshot_id": sid})

    return {
        "task_overlap": task_overlap,
        "near_duplicate_pairs": near_dups[:200],
        "near_duplicate_count": len(near_dups),
        "source_overlap": source_overlap,
    }

def build(
    *,
    root: Path,
    collection_id: str,
    dataset_id: str,
    tokenizer_dir: str | None,
    max_length: int,
    prompt_max: int,
    completion_max: int,
    out_dir: Path,
    audit_dir: Path,
) -> dict[str, Any]:
    from transformers import AutoTokenizer

    tok_path = _find_tokenizer_dir(root, tokenizer_dir)
    tokenizer = AutoTokenizer.from_pretrained(
        str(tok_path), trust_remote_code=True, local_files_only=True
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    eos_token = tokenizer.eos_token
    eos_ids = tokenizer(eos_token, add_special_tokens=False)["input_ids"]
    if len(eos_ids) != 1:
        raise SystemExit(f"eos_token must be one token, got {eos_ids}")
    chat_template = tokenizer.chat_template or ""
    chat_template_hash = _sha(chat_template)
    tokenizer_json = tok_path / "tokenizer.json"
    tokenizer_hash = _sha_file(tokenizer_json) if tokenizer_json.is_file() else _sha(str(tok_path))

    collection_dir = root / "runs" / "trajectories" / collection_id
    summary_path = collection_dir / "summary.json"
    if not summary_path.is_file():
        raise SystemExit(f"collection summary missing: {summary_path}")
    collection_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    pairs = _load_jsonl(collection_dir / "state_action_candidates.jsonl")
    if not pairs:
        raise SystemExit(f"no state-action candidates: {collection_dir}")
    source_manifest_hash = _sha(
        json.dumps(
            {
                "collection_id": collection_id,
                "summary": collection_summary,
                "tokenizer_dir": tok_path.name,
                "tokenizer_hash": tokenizer_hash,
                "chat_template_hash": chat_template_hash,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )

    tables = _load_task_tables(root)
    task_split: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    skipped = {
        "test_split": 0,
        "unknown_task": 0,
        "split_conflict": 0,
        "gold_field": 0,
        "duplicate_state": 0,
        "action_conflict": 0,
        "bad_messages": 0,
        "bad_action": 0,
        "over_length": 0,
    }
    examples: list[dict[str, Any]] = []

    for pair in pairs:
        task_id = pair.get("task_id")
        split = pair.get("split")
        state_hash = pair.get("state_hash")
        action = pair.get("action") or {}
        packed = pair.get("packed_state") or {}
        if split not in {"train", "dev"}:
            skipped["test_split"] += 1
            continue
        if not task_id or not state_hash:
            skipped["unknown_task"] += 1
            continue
        task_split.setdefault(str(task_id), str(split))
        if task_split[str(task_id)] != split:
            skipped["split_conflict"] += 1
            examples.append({"task_id": task_id, "kind": "split_conflict"})
            continue
        if state_hash in seen:
            skipped["duplicate_state"] += 1
            if seen[state_hash] != _completion_text(action):
                skipped["action_conflict"] += 1
                examples.append({"task_id": task_id, "kind": "action_conflict"})
            continue
        blob = json.dumps(packed, ensure_ascii=False)
        if "gold_" in blob or "gold_claims" in blob or "gold_support" in blob:
            skipped["gold_field"] += 1
            examples.append({"task_id": task_id, "kind": "gold_field"})
            continue
        messages = packed.get("messages")
        if not isinstance(messages, list) or len(messages) < 2:
            skipped["bad_messages"] += 1
            continue
        try:
            completion = _completion_text(action)
            obj = json.loads(completion)
            if set(obj) != set(ACTION_ORDER):
                raise ValueError("action_fields")
        except Exception:
            skipped["bad_action"] += 1
            continue
        prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
        completion_ids = tokenizer(completion, add_special_tokens=False)["input_ids"]
        if len(prompt_ids) > prompt_max:
            skipped["over_length"] += 1
            examples.append({"task_id": task_id, "kind": "prompt_over_length", "tokens": len(prompt_ids)})
            continue
        if len(completion_ids) > completion_max:
            skipped["over_length"] += 1
            examples.append({"task_id": task_id, "kind": "completion_over_length", "tokens": len(completion_ids)})
            continue
        if len(prompt_ids) + len(completion_ids) + len(eos_ids) > max_length:
            skipped["over_length"] += 1
            examples.append({"task_id": task_id, "kind": "total_over_length", "tokens": len(prompt_ids) + len(completion_ids) + len(eos_ids)})
            continue
        seen[state_hash] = completion
        rows.append(
            {
                "task_id": task_id,
                "state_id": f"st_{state_hash[:16]}",
                "split": split,
                "prompt": prompt,
                "completion": completion,
                "messages": messages,
                "state_hash": state_hash,
                "source_manifest_hash": source_manifest_hash,
                "collection_id": collection_id,
                "policy_version": pair.get("policy_version") or collection_summary.get("policy_version"),
                "dataset": pair.get("dataset"),
                "action": _ordered_action(action),
                "step": pair.get("step"),
                "prompt_tokens": len(prompt_ids),
                "completion_tokens": len(completion_ids),
                "eos_token": eos_token,
            }
        )

    cross = _cross_split_checks(tables, task_split)
    near_dup_dev = {p["dev_task_id"] for p in cross["near_duplicate_pairs"]}
    if near_dup_dev:
        before = len(rows)
        rows = [r for r in rows if not (r["split"] == "dev" and r["task_id"] in near_dup_dev)]
        cross["dropped_dev_rows_for_near_dup"] = before - len(rows)
    else:
        cross["dropped_dev_rows_for_near_dup"] = 0

    train_rows = [r for r in rows if r["split"] == "train"]
    dev_rows = [r for r in rows if r["split"] == "dev"]
    train_actions: dict[str, int] = {}
    dev_actions: dict[str, int] = {}
    for r in train_rows:
        a = r["action"]["action"]
        train_actions[a] = train_actions.get(a, 0) + 1
    for r in dev_rows:
        a = r["action"]["action"]
        dev_actions[a] = dev_actions.get(a, 0) + 1
    train_total = sum(train_actions.values())
    train_ratios = {k: round(v / train_total, 4) for k, v in train_actions.items()} if train_total else {}
    max_action_ratio = max(train_ratios.values()) if train_ratios else 0.0
    balance_ok = max_action_ratio <= 0.5 + 1e-9

    leakage = _scan_leakage(rows, tables)
    source_overlap = cross["source_overlap"]
    source_overlap_blocking = any(x["dataset"] == "chinese" for x in source_overlap)
    test_rows = sum(1 for r in rows if r["split"] == "test")
    scale_status = (
        "target_met"
        if len(train_rows) >= 4000 and len(dev_rows) >= 800
        else "minimum_met"
        if len(train_rows) >= 2000
        else "below_minimum"
    )
    passed = (
        len(train_rows) >= 2000
        and balance_ok
        and leakage["passed"]
        and not cross["task_overlap"]
        and not source_overlap_blocking
        and test_rows == 0
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)
    train_path = out_dir / "train.jsonl"
    dev_path = out_dir / "dev.jsonl"
    for path, data in ((train_path, train_rows), (dev_path, dev_rows)):
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in data) + ("\n" if data else ""),
            encoding="utf-8",
        )

    stats = {
        "dataset_id": dataset_id,
        "collection_id": collection_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tokenizer_dir": str(tok_path),
        "tokenizer_hash": tokenizer_hash,
        "chat_template_hash": chat_template_hash,
        "max_length": max_length,
        "prompt_max": prompt_max,
        "completion_max": completion_max,
        "train_count": len(train_rows),
        "dev_count": len(dev_rows),
        "total_count": len(rows),
        "train_actions": train_actions,
        "train_action_ratios": train_ratios,
        "dev_actions": dev_actions,
        "max_train_action_ratio": max_action_ratio,
        "balance_ok": balance_ok,
        "prompt_tokens": _token_stats([r["prompt_tokens"] for r in rows]),
        "completion_tokens": _token_stats([r["completion_tokens"] for r in rows]),
        "skipped": skipped,
        "skipped_examples": examples[:50],
        "cross_split": cross,
        "source_overlap_blocking": source_overlap_blocking,
        "scale_status": scale_status,
        "train_sha256": _sha_file(train_path),
        "dev_sha256": _sha_file(dev_path),
        "passed": passed,
    }
    (out_dir / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (audit_dir / "action_distribution.json").write_text(
        json.dumps(
            {
                "train": train_actions,
                "train_ratios": train_ratios,
                "dev": dev_actions,
                "max_train_action_ratio": max_action_ratio,
                "balance_ok": balance_ok,
                "suggestions_if_failed": [
                    "collect unanswerable/conflicting tasks for abstain/finish diversity",
                    "add a real second search/read scenario; never duplicate states",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (audit_dir / "split_isolation.json").write_text(
        json.dumps(cross, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (audit_dir / "leakage_scan.json").write_text(
        json.dumps(leakage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest = {
        "manifest_id": "mf_sft_s30_0001",
        "dataset_id": dataset_id,
        "version": "s30_v1",
        "created_at": stats["created_at"],
        "collection_id": collection_id,
        "policy_version": collection_summary.get("policy_version"),
        "source_manifest_hash": source_manifest_hash,
        "tokenizer_dir": str(tok_path),
        "tokenizer_hash": tokenizer_hash,
        "chat_template_hash": chat_template_hash,
        "max_length": max_length,
        "prompt_max": prompt_max,
        "completion_max": completion_max,
        "train_count": len(train_rows),
        "dev_count": len(dev_rows),
        "train_sha256": stats["train_sha256"],
        "dev_sha256": stats["dev_sha256"],
        "train_actions": train_actions,
        "train_action_ratios": train_ratios,
        "max_train_action_ratio": max_action_ratio,
        "balance_ok": balance_ok,
        "scale_status": scale_status,
        "leakage_passed": leakage["passed"],
        "split_isolation": {
            "task_overlap": cross["task_overlap"],
            "near_duplicate_count": cross["near_duplicate_count"],
            "source_overlap": source_overlap,
            "dropped_dev_rows_for_near_dup": cross["dropped_dev_rows_for_near_dup"],
        },
        "audit_paths": {
            "stats": str(out_dir / "stats.json"),
            "action_distribution": str(audit_dir / "action_distribution.json"),
            "split_isolation": str(audit_dir / "split_isolation.json"),
            "leakage_scan": str(audit_dir / "leakage_scan.json"),
            "mask_audit": str(audit_dir / "mask_audit.json"),
        },
        "passed": passed,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (root / "data" / "manifests" / "mf_sft_s30_0001.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"passed": passed, **{k: stats[k] for k in ("train_count", "dev_count", "train_actions", "max_train_action_ratio", "balance_ok", "scale_status", "skipped")}, "leakage": leakage}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--collection-id", default="traj_heuristic_s30_0001")
    ap.add_argument("--dataset-id", default="sft_s30_v1")
    ap.add_argument("--tokenizer-dir", default=None)
    ap.add_argument("--max-length", type=int, default=3072)
    ap.add_argument("--prompt-max", type=int, default=2880)
    ap.add_argument("--completion-max", type=int, default=192)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--audit-dir", type=Path, default=None)
    args = ap.parse_args()
    root = args.root.resolve()
    out_dir = args.out_dir or (root / "data" / "sft" / args.dataset_id)
    audit_dir = args.audit_dir or (root / "runs" / "audits" / "sft_s30_a001")
    result = build(
        root=root,
        collection_id=args.collection_id,
        dataset_id=args.dataset_id,
        tokenizer_dir=args.tokenizer_dir,
        max_length=args.max_length,
        prompt_max=args.prompt_max,
        completion_max=args.completion_max,
        out_dir=out_dir,
        audit_dir=audit_dir,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
#!/usr/bin/env python3
"""S33: state-level and end-to-end development evaluation.

Modes:
  state  - JSON validity / action confusion / stop accuracy on S30 dev states
  tasks  - 40-task screening or full 160-task dev confirmation
  select - apply the pre-registered candidate selection rule to 40-task results
  report - aggregate the full dev results
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
for _p in (_REPO, _SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from evidence_agent.agent.actions import ActionValidationError, validate_action  # noqa: E402
from evidence_agent.agent.budget import BudgetConfig  # noqa: E402
from evidence_agent.agent.llm import HttpLLMClient, parse_json_object  # noqa: E402

from dev_harness import (  # noqa: E402
    ACTION_ORDER,
    aggregate,
    load_cases,
    run_case,
    score_case,
)


def results_filename(
    system: str,
    *,
    tool_budget: int = 8,
    temperature: float = 0.0,
    seed: int | None = None,
    variant: str | None = None,
    web_mode: str = "replay",
) -> str:
    """Stable per-condition result file; defaults keep S42 `results_<system>.jsonl`."""
    parts = [f"results_{system}"]
    if int(tool_budget) != 8:
        parts.append(f"b{int(tool_budget)}")
    if float(temperature) != 0.0:
        parts.append(f"t{temperature}")
    if seed is not None:
        parts.append(f"seed{int(seed)}")
    if variant:
        parts.append(str(variant))
    if web_mode and web_mode not in {"replay", "off", "off_or_replay"}:
        parts.append(str(web_mode))
    return "_".join(parts) + ".jsonl"


def _record_condition_key(rec: dict[str, Any]) -> tuple:
    r = rec.get("result") or {}
    return (
        rec.get("task_id"),
        rec.get("system"),
        int(r.get("tool_budget") if r.get("tool_budget") is not None else 8),
        float(r.get("temperature") if r.get("temperature") is not None else 0.0),
        r.get("seed"),
        r.get("ablation_variant"),
        r.get("web_mode") or "replay",
    )

DEV_ROWS = "data/sft/sft_s30_v1/dev.jsonl"
CANDIDATE_KEYS = ("Q_mean", "G_gold_anchored_mean", "G_verifier_mean")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def system_adapter(system: str) -> str | None:
    s = system.lower()
    if s in {"e0", "base", "b0", "b1", "b2"}:
        return None
    if s in {"e1", "e1_final", "sft_e1"}:
        return "sft_e1"
    # E2 / DPO policy (vLLM --lora-modules name dpo_e2).
    if s in {"e2", "e2_final", "dpo_e2", "exp_dpo_0001"}:
        return "dpo_e2"
    # Pre-registered checkpoint aliases (vLLM --lora-modules names).
    if s in {"e1_ckpt_600", "e1_ckpt_616"}:
        return system
    return system


def _hash_rank(prefix: str, task_id: str) -> str:
    return hashlib.sha256(f"{prefix}:{task_id}".encode()).hexdigest()


def select_subset(root: Path, n: int = 40) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases = load_cases(root, datasets=["chinese", "hotpotqa"], split="dev")
    chinese = [c for c in cases if c.dataset == "chinese"]
    english = [c for c in cases if c.dataset == "hotpotqa"]
    by_cat: dict[str, list[Any]] = {}
    for c in chinese:
        by_cat.setdefault(str(c.task.get("category") or "unknown"), []).append(c)
    chosen: list[Any] = []
    rule: dict[str, Any] = {"chinese": {}, "hotpotqa": {}}
    for cat in ("direct_fact", "multi_source", "version_conflict", "insufficient_evidence"):
        bucket = sorted(by_cat.get(cat, []), key=lambda c: _hash_rank("s33_dev40", c.task_id))
        take = bucket[:6]
        chosen.extend(take)
        rule["chinese"][cat] = [c.task_id for c in take]
    by_diff: dict[str, list[Any]] = {}
    for c in english:
        by_diff.setdefault(str(c.task.get("difficulty") or "unknown"), []).append(c)
    quotas = {"easy": 5, "medium": 6, "hard": 5}
    for diff, quota in quotas.items():
        bucket = sorted(by_diff.get(diff, []), key=lambda c: _hash_rank("s33_dev40", c.task_id))
        take = bucket[:quota]
        chosen.extend(take)
        rule["hotpotqa"][diff] = [c.task_id for c in take]
    fallback: list[Any] = []
    if len(chosen) != n:
        # Deterministic fallback if a category/difficulty bucket is short.
        remaining = sorted(
            [c for c in cases if c.task_id not in {x.task_id for x in chosen}],
            key=lambda c: _hash_rank("s33_dev40", c.task_id),
        )
        fallback = remaining[: max(0, n - len(chosen))]
        chosen.extend(fallback)
    rule["fallback"] = [c.task_id for c in fallback]
    rule["actual"] = {
        "chinese": sum(1 for c in chosen if c.dataset == "chinese"),
        "hotpotqa": sum(1 for c in chosen if c.dataset == "hotpotqa"),
        "hotpotqa_difficulty": {
            str(d): sum(
                1
                for c in chosen
                if c.dataset == "hotpotqa" and str(c.task.get("difficulty")) == str(d)
            )
            for d in ("easy", "medium", "hard", "unknown")
        },
    }
    rule["n"] = len(chosen)
    rule["selection"] = (
        "24 Chinese (6 per category) + 16 HotpotQA; "
        "HotpotQA difficulty buckets are sparse, fallback is sha256-ranked"
    )
    return chosen, rule


def _state_rows(root: Path) -> list[dict[str, Any]]:
    return _load_jsonl(root / DEV_ROWS)


def _validate_prediction(obj: dict[str, Any], known: set[str]) -> tuple[bool, str | None]:
    try:
        validate_action(obj, allow_web=True, known_candidate_ids=known)
        return True, None
    except ActionValidationError as exc:
        return False, exc.code
    except Exception as exc:  # noqa: BLE001
        return False, type(exc).__name__


def state_eval(
    *,
    root: Path,
    systems: list[str],
    out_dir: Path,
    max_rows: int = 0,
) -> dict[str, Any]:
    rows = _state_rows(root)
    if max_rows:
        rows = rows[:max_rows]
    client = HttpLLMClient()
    summary: dict[str, Any] = {"rows": len(rows), "systems": {}}
    for system in systems:
        adapter = system_adapter(system)
        records: list[dict[str, Any]] = []
        confusion: dict[str, dict[str, int]] = {}
        valid = 0
        param_valid = 0
        stop_total = 0
        stop_correct = 0
        for row in rows:
            known: set[str] = set()
            try:
                user = json.loads(row["messages"][1]["content"])
                known = {
                    str(c["candidate_id"])
                    for c in (user.get("candidates") or [])
                    if c.get("candidate_id")
                }
            except Exception:
                pass
            ref = row["action"]
            try:
                resp = client.chat(
                    row["messages"],
                    max_tokens=192,
                    temperature=0.0,
                    adapter_id=adapter,
                )
                raw = resp.content
                obj = parse_json_object(raw)
                parse_ok = isinstance(obj, dict) and set(obj) == set(ACTION_ORDER)
                param_ok, err = (
                    _validate_prediction(obj, known) if parse_ok else (False, "schema")
                )
            except Exception as exc:  # noqa: BLE001
                raw = f"ERR {type(exc).__name__}: {exc}"
                obj = {}
                parse_ok, param_ok, err = False, False, "request_failed"
            pred_action = obj.get("action") if isinstance(obj, dict) else None
            ref_action = ref.get("action")
            valid += int(parse_ok)
            param_valid += int(param_ok)
            if ref_action in {"finish", "abstain"}:
                stop_total += 1
                stop_correct += int(pred_action == ref_action)
            confusion.setdefault(str(ref_action), {})
            confusion[str(ref_action)][str(pred_action)] = (
                confusion[str(ref_action)].get(str(pred_action), 0) + 1
            )
            records.append(
                {
                    "task_id": row.get("task_id"),
                    "state_id": row.get("state_id"),
                    "split": row.get("split"),
                    "reference": ref,
                    "predicted": obj,
                    "json_valid": parse_ok,
                    "param_valid": param_ok,
                    "error": err,
                    "raw": raw[:1000],
                }
            )
        n = max(1, len(rows))
        summary["systems"][system] = {
            "adapter": adapter,
            "rows": len(rows),
            "json_valid_rate": round(valid / n, 4),
            "param_valid_rate": round(param_valid / n, 4),
            "action_accuracy": round(
                sum(
                    1
                    for r in records
                    if isinstance(r["predicted"], dict)
                    and r["predicted"].get("action") == r["reference"].get("action")
                )
                / n,
                4,
            ),
            "stop_accuracy": round(stop_correct / stop_total, 4) if stop_total else None,
            "confusion": confusion,
            "records_path": str(out_dir / f"state_{system}.jsonl"),
        }
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"state_{system}.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
            encoding="utf-8",
        )
    _write_json(out_dir / "state_summary.json", summary)
    return summary

def _read_results(path: Path) -> list[dict[str, Any]]:
    return _load_jsonl(path)


def _aggregate_from_results(records: list[dict[str, Any]]) -> dict[str, Any]:
    return aggregate([r.get("score") or {} for r in records if r.get("score")])


def run_tasks(
    *,
    root: Path,
    systems: list[str],
    subset: str,
    out_dir: Path,
    max_tasks: int = 0,
    resume: bool = False,
    task_ids_file: Path | None = None,
    split: str = "dev",
    tool_budget: int = 8,
    temperature: float = 0.0,
    seed: int | None = None,
    variant: str | None = None,
    web_mode: str = "replay",
    datasets: list[str] | None = None,
) -> dict[str, Any]:
    from formal_systems import run_formal_case  # local import keeps unit path light

    ds = datasets or ["chinese", "hotpotqa"]
    if task_ids_file and task_ids_file.is_file():
        raw = json.loads(task_ids_file.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "task_ids" in raw:
            task_ids = set(raw["task_ids"])
        elif isinstance(raw, list):
            task_ids = set(raw)
        else:
            raise SystemExit(f"unsupported task-ids-file shape: {task_ids_file}")
        cases = load_cases(root, datasets=ds, split=split, task_ids=task_ids)
        rule = {"source": str(task_ids_file), "split": split, "n": len(cases)}
    elif subset == "40":
        if split != "dev":
            raise SystemExit("subset=40 is defined only for split=dev")
        cases, rule = select_subset(root, 40)
    else:
        cases = load_cases(root, datasets=ds, split=split)
        rule = {"source": f"all_{split}", "split": split, "n": len(cases)}
    if max_tasks:
        cases = cases[:max_tasks]
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        out_dir / "subset.json",
        {
            "rule": rule,
            "split": split,
            "task_ids": [c.task_id for c in cases],
            "tool_budget": tool_budget,
            "temperature": temperature,
            "seed": seed,
            "variant": variant,
            "web_mode": web_mode,
            "datasets": {
                "chinese": sum(1 for c in cases if c.dataset == "chinese"),
                "hotpotqa": sum(1 for c in cases if c.dataset == "hotpotqa"),
                "drbench": sum(1 for c in cases if c.dataset == "drbench"),
                "live": sum(1 for c in cases if c.dataset == "live"),
            },
        },
    )
    client = HttpLLMClient()
    budget_cfg = BudgetConfig(tool_calls=int(tool_budget))
    cond = {
        "tool_budget": int(tool_budget),
        "temperature": float(temperature),
        "seed": seed,
        "variant": variant,
        "web_mode": web_mode,
    }
    summary: dict[str, Any] = {
        "n_tasks": len(cases),
        "subset": subset,
        "split": split,
        "condition": cond,
        "systems": {},
    }
    for system in systems:
        adapter = system_adapter(system)
        fname = results_filename(
            system,
            tool_budget=tool_budget,
            temperature=temperature,
            seed=seed,
            variant=variant,
            web_mode=web_mode,
        )
        path = out_dir / fname
        subset_ids = {c.task_id for c in cases}
        existing = _read_results(path) if resume else []
        existing = [r for r in existing if r.get("task_id") in subset_ids]
        want_key_prefix = (
            int(tool_budget),
            float(temperature),
            seed,
            variant,
            web_mode if web_mode not in {"replay", "off", "off_or_replay"} else "replay",
        )
        done: set[str] = set()
        for r in existing:
            key = _record_condition_key(r)
            if key[0] in subset_ids and key[2:] == want_key_prefix:
                done.add(str(key[0]))
        # S42 default path: legacy rows may lack condition fields — treat as done by task_id.
        if (
            int(tool_budget) == 8
            and float(temperature) == 0.0
            and seed is None
            and not variant
            and web_mode in {"replay", "off", "off_or_replay"}
        ):
            done |= {str(r.get("task_id")) for r in existing if r.get("task_id") in subset_ids}
        records = list(existing)
        if not resume and path.exists():
            path.unlink()
            records = []
            done = set()
        for i, case in enumerate(cases):
            if case.task_id in done:
                continue
            try:
                result = run_formal_case(
                    root=root,
                    case=case,
                    client=client,
                    system=system,
                    policy_adapter_id=adapter,
                    budget_cfg=budget_cfg,
                    policy_temperature=float(temperature),
                    policy_seed=seed,
                    ablation_variant=variant,
                    web_mode=web_mode,
                )
                score = score_case(case, result)
            except Exception as exc:  # noqa: BLE001
                result = {
                    "task_id": case.task_id,
                    "dataset": case.dataset,
                    "system": system,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "usage": {},
                    "tool_budget": int(tool_budget),
                    "temperature": float(temperature),
                    "seed": seed,
                    "ablation_variant": variant,
                    "web_mode": web_mode,
                }
                score = {
                    "task_id": case.task_id,
                    "dataset": case.dataset,
                    "system": system,
                    "status": "failed",
                    "Q": 0.0,
                    "Q_em": 0.0,
                    "Q_f1": 0.0,
                    "G_verifier": None,
                    "G_gold_anchored": None,
                    "citation_anchor_rate": None,
                    "claims": 0,
                    "evidence": 0,
                    "answered_false": False,
                    "action_valid_rate": 0.0,
                    "stop_action": None,
                    "usage": {},
                    "wall_seconds": 0.0,
                    "error": result["error"],
                }
            records.append({"task_id": case.task_id, "system": system, "result": result, "score": score})
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(records[-1], ensure_ascii=False) + "\n")
            if (i + 1) % 5 == 0 or i + 1 == len(cases):
                print(
                    f"[{system}] {i + 1}/{len(cases)} {case.task_id} "
                    f"status={score.get('status')} Q={score.get('Q')}",
                    flush=True,
                )
        agg = _aggregate_from_results(records)
        summary_key = fname.replace("results_", "").replace(".jsonl", "")
        summary["systems"][summary_key] = {
            "adapter": adapter,
            "results_path": str(path),
            "condition": cond,
            **agg,
        }
        _write_json(out_dir / f"summary_{summary_key}.json", summary["systems"][summary_key])
    _write_json(out_dir / "summary.json", summary)
    return summary


def select_candidates(*, out_dir: Path, systems: list[str]) -> dict[str, Any]:
    table: list[dict[str, Any]] = []
    for system in systems:
        path = out_dir / f"summary_{system}.json"
        if path.is_file():
            s = json.loads(path.read_text(encoding="utf-8"))
        else:
            results = out_dir / f"results_{system}.jsonl"
            s = _aggregate_from_results(_read_results(results))
        table.append({"system": system, **s})
    candidates = [x for x in table if x["system"] not in {"e0", "base"}]
    if not candidates:
        raise SystemExit("no E1 candidates in results")
    best_q = max(float(x.get("Q_mean") or 0.0) for x in candidates)
    q_pool = [x for x in candidates if float(x.get("Q_mean") or 0.0) >= best_q - 0.01]
    g_key = "G_gold_anchored_mean"
    if all(x.get(g_key) is None for x in q_pool):
        g_key = "G_verifier_mean"
    best_g = max(float(x.get(g_key) or 0.0) for x in q_pool)
    g_pool = [x for x in q_pool if float(x.get(g_key) or 0.0) >= best_g - 0.01]
    g_pool.sort(
        key=lambda x: (
            float(x.get("avg_input_tokens") or 0) + float(x.get("avg_output_tokens") or 0),
            0 if x["system"] in {"e1", "e1_final"} else 1,
            x["system"],
        )
    )
    chosen = g_pool[0]
    report = {
        "rule": "max Q; within 0.01 max G (gold-anchored, else verifier); within 0.01 min tokens; tie prefer formal E1",
        "q_key": "Q_mean",
        "g_key": g_key,
        "candidates": table,
        "chosen_system": chosen["system"],
        "chosen_adapter": chosen.get("adapter"),
    }
    _write_json(out_dir / "selection.json", report)
    (out_dir / "selection.md").write_text(
        "# S33 candidate selection\n\n"
        + "\n".join(
            [
                f"- {x['system']}: Q={x.get('Q_mean')} G={x.get('G_gold_anchored_mean')} "
                f"tokens={float(x.get('avg_input_tokens') or 0) + float(x.get('avg_output_tokens') or 0):.1f}"
                for x in table
            ]
        )
        + f"\n\nChosen: **{chosen['system']}**\n",
        encoding="utf-8",
    )
    return report


def report_full(*, out_dir: Path, systems: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {"systems": {}}
    for system in systems:
        records = _read_results(out_dir / f"results_{system}.jsonl")
        summary["systems"][system] = _aggregate_from_results(records)
    _write_json(out_dir / "summary.json", summary)
    lines = ["# S33 full dev report", ""]
    for system, s in summary["systems"].items():
        lines.append(
            f"- {system}: n={s.get('n')} Q={s.get('Q_mean')} G_gold={s.get('G_gold_anchored_mean')} "
            f"G_verifier={s.get('G_verifier_mean')} false_answer={s.get('answered_false_rate')} "
            f"tokens={float(s.get('avg_input_tokens') or 0) + float(s.get('avg_output_tokens') or 0):.1f}"
        )
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--mode", choices=["state", "tasks", "select", "report"], required=True)
    ap.add_argument("--systems", default="e0,e1")
    ap.add_argument("--subset", choices=["40", "all"], default="40")
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-rows", type=int, default=0)
    ap.add_argument("--max-tasks", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--task-ids-file", type=Path, default=None)
    ap.add_argument("--tool-budget", type=int, default=8)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--variant", type=str, default=None)
    ap.add_argument("--web-mode", type=str, default="replay", choices=["off", "replay", "live"])
    ap.add_argument("--datasets", type=str, default="chinese,hotpotqa")
    args = ap.parse_args()
    root = args.root.resolve()
    out_dir = args.out
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    datasets = [s.strip() for s in args.datasets.split(",") if s.strip()]
    if args.mode == "state":
        result = state_eval(root=root, systems=systems, out_dir=out_dir, max_rows=args.max_rows)
    elif args.mode == "tasks":
        result = run_tasks(
            root=root,
            systems=systems,
            subset=args.subset,
            out_dir=out_dir,
            max_tasks=args.max_tasks,
            resume=args.resume,
            task_ids_file=args.task_ids_file,
            split=args.split,
            tool_budget=args.tool_budget,
            temperature=args.temperature,
            seed=args.seed,
            variant=args.variant,
            web_mode=args.web_mode,
            datasets=datasets,
        )
    elif args.mode == "select":
        result = select_candidates(out_dir=out_dir, systems=systems)
    else:
        result = report_full(out_dir=out_dir, systems=systems)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
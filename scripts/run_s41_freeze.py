#!/usr/bin/env python3
"""S41: freeze release strategy, test subsets, run plan, and manifests (no test scores)."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ZH_CATEGORIES = (
    "direct_fact",
    "multi_source",
    "version_conflict",
    "insufficient_evidence",
)

# Hash prefixes frozen before any formal test scoring.
PREFIX_ABLATION = "s41_ablation100"
PREFIX_BUDGET = "s41_budget_stability60"
PREFIX_BLIND = "s41_blind60"
PREFIX_DRBENCH = "s41_drbench12"
PREFIX_LIVE = "s41_live20"

ADAPTER_SHA = {
    "sft_e1": "4e8b60a07b8d65f7e66fb547a71d1658bfb94531d4e0c0156589e748fe6391ce",
    "dpo_e2": "011f3c14544ebb96762b6c77a818b5b6fd44d2ea670772630608836d8849ecbc",
}

MODEL_REVISIONS = {
    "base": {
        "repo_id": "Qwen/Qwen3-4B-Instruct-2507",
        "revision": "cdbee75f17c01a7cc42f958dc650907174af0554",
        "manifest": "mf_model_base_0001",
    },
    "embedding": {
        "repo_id": "BAAI/bge-m3",
        "revision": "5617a9f61b028005a4858fdac845db406aefb181",
        "manifest": "mf_model_embedding_0001",
    },
    "reranker": {
        "repo_id": "BAAI/bge-reranker-v2-m3",
        "revision": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
        "manifest": "mf_model_reranker_0001",
    },
    "judge": {
        "repo_id": "lytang/MiniCheck-Flan-T5-Large",
        "revision": "96eafd01cee2d16cf81aaa2fb226b14f422a37b3",
        "manifest": "mf_model_judge_0001",
    },
}


def _hash_rank(prefix: str, task_id: str) -> str:
    return hashlib.sha256(f"{prefix}:{task_id}".encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_text(path: Path) -> str:
    # PowerShell Set-Content often writes UTF-8 BOM.
    return path.read_text(encoding="utf-8-sig")


def _load_json(path: Path) -> Any:
    return json.loads(_read_text(path))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ln in _read_text(path).splitlines():
        ln = ln.strip()
        if not ln:
            continue
        rows.append(json.loads(ln))
    return rows


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import yaml  # type: ignore

        return yaml.safe_load(_read_text(path)) or {}
    except Exception:  # noqa: BLE001
        return {}


def _take_ranked(items: list[dict[str, Any]], prefix: str, n: int) -> list[str]:
    ranked = sorted(items, key=lambda r: (_hash_rank(prefix, str(r["task_id"])), str(r["task_id"])))
    return [str(r["task_id"]) for r in ranked[:n]]


def select_ablation100(chinese: list[dict[str, Any]], hotpotqa: list[dict[str, Any]]) -> dict[str, Any]:
    """40 Chinese (10/category) + 60 HotpotQA; no score access."""
    by_cat: dict[str, list[dict[str, Any]]] = {c: [] for c in ZH_CATEGORIES}
    for row in chinese:
        cat = str(row.get("category") or "unknown")
        by_cat.setdefault(cat, []).append(row)
    zh_ids: list[str] = []
    per_cat: dict[str, list[str]] = {}
    for cat in ZH_CATEGORIES:
        ids = _take_ranked(by_cat.get(cat, []), PREFIX_ABLATION, 10)
        per_cat[cat] = ids
        zh_ids.extend(ids)
    hp_ids = _take_ranked(hotpotqa, PREFIX_ABLATION, 60)
    task_ids = zh_ids + hp_ids
    return {
        "name": "ablation100",
        "prefix": PREFIX_ABLATION,
        "rule": "40 Chinese (10 per category) + 60 HotpotQA; sha256(prefix:task_id) ascending",
        "n": len(task_ids),
        "task_ids": task_ids,
        "chinese_by_category": per_cat,
        "hotpotqa": hp_ids,
        "counts": {"chinese": len(zh_ids), "hotpotqa": len(hp_ids)},
    }


def select_budget_stability60(
    chinese: list[dict[str, Any]], hotpotqa: list[dict[str, Any]]
) -> dict[str, Any]:
    """20 Chinese (5/category) + 40 HotpotQA; shared by budget curve and stability."""
    by_cat: dict[str, list[dict[str, Any]]] = {c: [] for c in ZH_CATEGORIES}
    for row in chinese:
        cat = str(row.get("category") or "unknown")
        by_cat.setdefault(cat, []).append(row)
    zh_ids: list[str] = []
    per_cat: dict[str, list[str]] = {}
    for cat in ZH_CATEGORIES:
        ids = _take_ranked(by_cat.get(cat, []), PREFIX_BUDGET, 5)
        per_cat[cat] = ids
        zh_ids.extend(ids)
    hp_ids = _take_ranked(hotpotqa, PREFIX_BUDGET, 40)
    task_ids = zh_ids + hp_ids
    return {
        "name": "budget_stability60",
        "prefix": PREFIX_BUDGET,
        "rule": "20 Chinese (5 per category) + 40 HotpotQA; same IDs for budget curve and stability",
        "n": len(task_ids),
        "task_ids": task_ids,
        "chinese_by_category": per_cat,
        "hotpotqa": hp_ids,
        "counts": {"chinese": len(zh_ids), "hotpotqa": len(hp_ids)},
        "reuse": {
            "budget8": "reuse main-experiment b8 rows for B1 and release system",
            "budget4_12": "new runs",
            "stability_seeds": [43, 44],
            "stability_temperature": 0.3,
            "main_temperature": 0.0,
        },
    }


def select_blind60(chinese: list[dict[str, Any]], hotpotqa: list[dict[str, Any]]) -> dict[str, Any]:
    """40 Chinese (10/category) + 20 English; human review only B1 vs release."""
    by_cat: dict[str, list[dict[str, Any]]] = {c: [] for c in ZH_CATEGORIES}
    for row in chinese:
        cat = str(row.get("category") or "unknown")
        by_cat.setdefault(cat, []).append(row)
    zh_ids: list[str] = []
    per_cat: dict[str, list[str]] = {}
    for cat in ZH_CATEGORIES:
        ids = _take_ranked(by_cat.get(cat, []), PREFIX_BLIND, 10)
        per_cat[cat] = ids
        zh_ids.extend(ids)
    en_ids = _take_ranked(hotpotqa, PREFIX_BLIND, 20)
    task_ids = zh_ids + en_ids
    return {
        "name": "blind60",
        "prefix": PREFIX_BLIND,
        "rule": "40 Chinese (10 per category) + 20 English; compare B1 vs release only",
        "n": len(task_ids),
        "task_ids": task_ids,
        "chinese_by_category": per_cat,
        "english": en_ids,
        "counts": {"chinese": len(zh_ids), "english": len(en_ids)},
        "systems": ["b1", "e0"],
        "outputs_expected": 120,
        "blinding": "shuffle system labels before review; single-author review must be labeled as such",
    }


def select_drbench12(question_ids: list[str] | None) -> dict[str, Any]:
    """Hash-select 12 public DRBench question IDs; catalog may be pending."""
    if not question_ids:
        return {
            "name": "drbench12",
            "prefix": PREFIX_DRBENCH,
            "status": "IDS_PENDING_CATALOG",
            "rule": (
                f"Once official public question IDs are registered under data/external/drbench/, "
                f"sort by sha256('{PREFIX_DRBENCH}:'+question_id) ascending and take first 12. "
                "Do not use system scores. Custom small subset; not an official full leaderboard."
            ),
            "n": 0,
            "question_ids": [],
            "systems": ["b1", "e0"],
            "runs": 24,
        }
    ranked = sorted(question_ids, key=lambda q: (_hash_rank(PREFIX_DRBENCH, q), q))
    chosen = ranked[:12]
    return {
        "name": "drbench12",
        "prefix": PREFIX_DRBENCH,
        "status": "IDS_FROZEN",
        "rule": f"sha256('{PREFIX_DRBENCH}:'+question_id) ascending; take 12",
        "n": len(chosen),
        "question_ids": chosen,
        "systems": ["b1", "e0"],
        "runs": 24,
    }


def freeze_live20_protocol() -> dict[str, Any]:
    """Register live task ID scheme and AB/BA pairing; bodies authored at S45."""
    slots = []
    for i in range(20):
        slot_id = f"live_s41_{i:02d}"
        # Deterministic AB/BA from hash bit.
        bit = int(_hash_rank(PREFIX_LIVE, slot_id)[-1], 16) & 1
        order = ("b1", "e0") if bit == 0 else ("e0", "b1")
        slots.append({"slot_id": slot_id, "run_order": list(order)})
    return {
        "name": "live20",
        "prefix": PREFIX_LIVE,
        "status": "PROTOCOL_FROZEN_TASKS_PENDING",
        "rule": (
            "Author 20 new live web tasks at S45 under data/tasks/live/live_s41_v1/; "
            f"slot_ids live_s41_00..19; adjacent AB/BA order from sha256('{PREFIX_LIVE}:'+slot_id). "
            "Not mixed into frozen main-experiment aggregates."
        ),
        "n_slots": 20,
        "slots": slots,
        "systems": ["b1", "e0"],
        "runs": 40,
        "web_mode": "live",
        "constraints": {
            "max_live_search_calls": 3,
            "included_in_tool_budget": True,
            "auto_payg": False,
            "search_depth": "basic",
        },
    }


def build_run_plan(
    *,
    release_system: str,
    ablation: dict[str, Any],
    budget60: dict[str, Any],
    blind: dict[str, Any],
    drbench: dict[str, Any],
    live: dict[str, Any],
) -> dict[str, Any]:
    main_systems = ["b0", "b1", "b2", "e0", "e1", "e2"]
    batches = [
        {
            "batch_id": "main_test300",
            "step": "S42",
            "systems": main_systems,
            "n_tasks": 300,
            "n_runs": 1800,
            "temperature": 0.0,
            "web_mode": "off_or_replay",
            "notes": "Six systems × full test300; failures remain in denominator",
        },
        {
            "batch_id": "ablation_no_source_anchor",
            "step": "S43",
            "systems": [release_system],
            "variant": "no_source_anchor",
            "n_tasks": ablation["n"],
            "n_runs": ablation["n"],
            "task_subset": "ablation100",
            "notes": "Server keeps real sources for audit/scoring; only policy-visible anchors removed",
        },
        {
            "batch_id": "ablation_hide_visible_budget",
            "step": "S43",
            "systems": [release_system],
            "variant": "hide_visible_budget",
            "n_tasks": ablation["n"],
            "n_runs": ablation["n"],
            "task_subset": "ablation100",
            "notes": "Hide budget fields in policy input; executor hard budget unchanged",
        },
        {
            "batch_id": "budget_curve_b4_b12",
            "step": "S44",
            "systems": ["b1", release_system],
            "budgets": [4, 12],
            "n_tasks": budget60["n"],
            "n_runs": 2 * 2 * budget60["n"],  # 240
            "task_subset": "budget_stability60",
            "reuse": "budget8 from main experiment",
        },
        {
            "batch_id": "stability_seed43_44",
            "step": "S44",
            "systems": ["b1", release_system],
            "seeds": [43, 44],
            "temperature": 0.3,
            "n_tasks": budget60["n"],
            "n_runs": 2 * 2 * budget60["n"],  # 240
            "task_subset": "budget_stability60",
            "notes": "Not same-distribution replicates of temperature-0 main rows",
        },
        {
            "batch_id": "drbench12",
            "step": "S45",
            "systems": ["b1", release_system],
            "n_tasks": 12,
            "n_runs": 24,
            "status": drbench.get("status"),
            "notes": "External custom subset; do not mix into main aggregates",
        },
        {
            "batch_id": "live20",
            "step": "S45",
            "systems": ["b1", release_system],
            "n_tasks": 20,
            "n_runs": 40,
            "status": live.get("status"),
            "notes": "Live web; AB/BA adjacent; not mixed into main aggregates",
        },
    ]
    planned = sum(int(b["n_runs"]) for b in batches)
    return {
        "planned_formal_runs": planned,
        "target": 2544,
        "matches_target": planned == 2544,
        "batches": batches,
        "excluded_from_2544": [
            "checkpoint screening",
            "DPO branch collection (≥2800 or more)",
            "pilot / probes",
            "dev evaluation (S33/S39)",
            "training runs",
            "infrastructure failure reruns (logged separately)",
        ],
        "blind_review": {
            "step": "S46",
            "subset": "blind60",
            "n_tasks": blind["n"],
            "systems": blind["systems"],
            "outputs": blind["outputs_expected"],
            "not_counted_in_2544": True,
            "reason": "human labeling, not system model runs in the 2544 plan table",
        },
        "failure_rerun_policy": {
            "valid_low_score": "do_not_rerun_for_better_score",
            "infrastructure_fault": "may_rerun_under_rule; keep original failure + extra cost",
            "system_timeout_or_tool_fail": "remain_in_denominator; not silently dropped",
            "missing_system_version": "report column incomplete; do not fill from other systems",
        },
    }


def collect_file_hashes(root: Path) -> dict[str, str]:
    rels = [
        "repo/configs/project.yaml",
        "repo/configs/paths.yaml",
        "repo/configs/prompts/controller.md",
        "repo/configs/prompts/writer.md",
        "repo/configs/prompts/verifier.md",
        "repo/locks/app.txt",
        "repo/locks/infer.txt",
        "repo/locks/train.txt",
        "repo/locks/judge.txt",
        "repo/docs/architecture/baseline_matrix.md",
        "repo/docs/evaluation/metric_definitions.md",
        "data/manifests/mf_model_base_0001.json",
        "data/manifests/mf_model_embedding_0001.json",
        "data/manifests/mf_model_reranker_0001.json",
        "data/manifests/mf_model_judge_0001.json",
        "data/manifests/mf_hotpotqa_s25_0001.json",
        "data/manifests/mf_chinese_tasks_s27_0001.json",
        "data/tasks/chinese/zh_tech_s27_v1/test.jsonl",
        "data/tasks/hotpotqa/hotpotqa_distractor_s25_v1/test.jsonl",
        "runs/steps/S40/a001/selection.json",
        "runs/steps/S40/a001/acceptance.json",
    ]
    out: dict[str, str] = {}
    for rel in rels:
        digest = _sha256_file(root / rel)
        if digest:
            out[rel.replace("\\", "/")] = digest
    return out


def build_system_matrix(release_system: str) -> dict[str, Any]:
    return {
        "main_systems": ["b0", "b1", "b2", "e0", "e1", "e2"],
        "release_system": release_system,
        "release_basis": "S40 unique selection on eval_dev160_s39_0001; looked_at_test=false",
        "curve_and_external_systems": ["b1", release_system],
        "ablation_base": release_system,
        "ablation_variants": ["no_source_anchor", "hide_visible_budget"],
        "e1": {
            "status": "research_only",
            "adapter_id": "sft_e1",
            "path": "artifacts/adapters/sft/exp_sft_0001/",
            "sha256": ADAPTER_SHA["sft_e1"],
            "still_runs_in_main": True,
        },
        "e2": {
            "status": "evaluated_not_released",
            "adapter_id": "dpo_e2",
            "path": "artifacts/adapters/dpo/exp_dpo_0001/",
            "sha256": ADAPTER_SHA["dpo_e2"],
            "still_runs_in_main": True,
            "meets_target_scale": False,
        },
        "e0": {
            "status": "release",
            "adapter_id": None,
            "writer_verifier": "base",
        },
        "shared_freeze": {
            "tools": ["local_search", "web_search", "read_evidence"],
            "writer_verifier_prompts": ["configs/prompts/writer.md", "configs/prompts/verifier.md"],
            "budget_profile": "standard",
            "online_temperature_main": 0.0,
        },
    }


def estimate_forecast(project: dict[str, Any], planned_runs: int) -> dict[str, Any]:
    cost = project.get("cost") or {}
    gpu_rate = 1.66  # last known; UNKNOWN if console price differs
    # Conservative wall estimate from S39 ~7.5–8s/task end-to-end harness.
    sec_per_run = 8.0
    gpu_hours = planned_runs * sec_per_run / 3600.0
    gpu_cny = gpu_hours * gpu_rate
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "step": "S41",
        "formal_planned_runs": planned_runs,
        "assumptions": {
            "gpu_cny_per_hour": gpu_rate,
            "gpu_price_status": "UNKNOWN_confirm_console",
            "sec_per_run_assumed": sec_per_run,
            "basis": "S39 harness pace ~7.5–8s/task; excludes infra reruns",
            "final_2544_excludes_prior_work": True,
        },
        "formal_2544": {
            "runs": planned_runs,
            "gpu_hours_est": round(gpu_hours, 2),
            "gpu_cny_est": round(gpu_cny, 2),
            "teacher_cny": "UNKNOWN_until_priced_or_local_fallback",
            "search_cny": "live40 may spend Tavily credits; replay/main avoid live",
        },
        "caps_cny": {
            "total": cost.get("total_cap", 1500),
            "gpu": cost.get("gpu_cap", 600),
            "teacher": cost.get("teacher_and_judge_cap", 300),
            "search": cost.get("search_cap", 100),
            "rework": cost.get("contingency", 400),
            "gpu_hours_cap": cost.get("gpu_hours_cap", 120),
        },
        "within_cap_projection": {
            "gpu_cny_ok": gpu_cny <= float(cost.get("gpu_cap", 600)),
            "gpu_hours_ok": gpu_hours <= float(cost.get("gpu_hours_cap", 120)),
            "note": "Stop long batches if remaining budget insufficient; do not drop failed main tasks",
        },
        "stop_order": [
            "no new live search when freeze/replay suffices",
            "stop extra sampling beyond targets",
            "end idle GPU / vLLM when idle",
            "do not drop required main tasks by performance",
            "pause incomplete long batches and record gaps",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--attempt", default="a001")
    ap.add_argument(
        "--drbench-ids",
        type=Path,
        default=None,
        help="Optional JSON/JSONL/TXT of public DRBench question IDs",
    )
    args = ap.parse_args()
    root = args.root.resolve()
    attempt = args.attempt
    now = datetime.now(timezone.utc).isoformat()

    zh_path = root / "data/tasks/chinese/zh_tech_s27_v1/test.jsonl"
    hp_path = root / "data/tasks/hotpotqa/hotpotqa_distractor_s25_v1/test.jsonl"
    chinese = _load_jsonl(zh_path)
    hotpotqa = _load_jsonl(hp_path)
    if len(chinese) != 100 or len(hotpotqa) != 200:
        raise SystemExit(
            f"expected test300 = 100 zh + 200 hpqa; got zh={len(chinese)} hpqa={len(hotpotqa)}"
        )

    s40: dict[str, Any] = {}
    s40_path = root / "runs/steps/S40/a001/acceptance.json"
    if s40_path.is_file():
        s40 = _load_json(s40_path)
    release_system = str(s40.get("chosen_system") or "e0").lower()
    if release_system not in {"e0", "e1", "e2", "e1_final", "e2_final"}:
        raise SystemExit(f"unexpected release system: {release_system}")
    # Normalize aliases to short ids used in run plan.
    if release_system in {"e1_final", "e1"}:
        release_system = "e1"
    elif release_system in {"e2_final", "e2"}:
        release_system = "e2"
    else:
        release_system = "e0"

    if s40.get("looked_at_test") is True:
        raise SystemExit("S40 looked_at_test=true — refuse freeze (selection contaminated)")

    drbench_ids: list[str] | None = None
    catalog = root / "data/external/drbench/question_ids.json"
    id_path = args.drbench_ids or catalog
    if id_path.is_file():
        raw = _read_text(id_path).strip()
        if id_path.suffix == ".json":
            payload = json.loads(raw)
            if isinstance(payload, list):
                drbench_ids = [str(x) for x in payload]
            elif isinstance(payload, dict):
                drbench_ids = [str(x) for x in (payload.get("question_ids") or [])]
        else:
            drbench_ids = [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.startswith("#")]

    ablation = select_ablation100(chinese, hotpotqa)
    budget60 = select_budget_stability60(chinese, hotpotqa)
    blind = select_blind60(chinese, hotpotqa)
    drbench = select_drbench12(drbench_ids)
    live = freeze_live20_protocol()
    matrix = build_system_matrix(release_system)
    run_plan = build_run_plan(
        release_system=release_system,
        ablation=ablation,
        budget60=budget60,
        blind=blind,
        drbench=drbench,
        live=live,
    )
    if not run_plan["matches_target"]:
        raise SystemExit(f"planned runs {run_plan['planned_formal_runs']} != 2544")

    project = _load_yaml(root / "repo/configs/project.yaml")
    file_hashes = collect_file_hashes(root)
    config_bundle_hash = _sha256_text(json.dumps(file_hashes, sort_keys=True, ensure_ascii=False))

    subsets = {
        "schema_version": "1.0",
        "step": "S41",
        "created_at": now,
        "looked_at_system_scores": False,
        "test300": {
            "chinese": 100,
            "hotpotqa": 200,
            "total": 300,
            "paths": {
                "chinese": "data/tasks/chinese/zh_tech_s27_v1/test.jsonl",
                "hotpotqa": "data/tasks/hotpotqa/hotpotqa_distractor_s25_v1/test.jsonl",
            },
        },
        "subsets": {
            "ablation100": ablation,
            "budget_stability60": budget60,
            "blind60": blind,
            "drbench12": drbench,
            "live20": live,
        },
        "overlap_policy": "Subsets may overlap; each batch keeps its own evaluation_id and denominator",
    }

    freeze_manifest = {
        "manifest_id": "mf_s41_freeze_0001",
        "step": "S41",
        "attempt": attempt,
        "created_at": now,
        "release_system": release_system,
        "looked_at_test_scores": False,
        "s40_acceptance": "runs/steps/S40/a001/acceptance.json",
        "models": MODEL_REVISIONS,
        "adapters": ADAPTER_SHA,
        "system_matrix": matrix,
        "config_bundle_hash": config_bundle_hash,
        "file_hashes": file_hashes,
        "run_plan_summary": {
            "planned_formal_runs": run_plan["planned_formal_runs"],
            "matches_target": run_plan["matches_target"],
        },
        "data_manifests": [
            "mf_hotpotqa_s25_0001",
            "mf_chinese_tasks_s27_0001",
            "mf_chinese_sources_s26_0001",
            "mf_sft_s30_0001",
            "mf_s22_baselines_0001",
            "mf_upstream_deepagents_0001",
        ],
        "upstream": {
            "deepagents": "0.7.32",
            "commit": "e85c6b98087861512d2c5240305e16cfac68a746",
        },
        "claims_forbidden": [
            "DPO/SFT selected for product release",
            "preference scale 600/100 completed",
            "DRBench full official leaderboard",
        ],
    }

    forecast = estimate_forecast(project, run_plan["planned_formal_runs"])

    # Output paths
    splits_dir = root / "data/splits"
    manifests_dir = root / "data/manifests"
    proto_dir = root / "repo/evaluation/protocols"
    step_dir = root / "runs/steps/S41" / attempt
    billing_dir = root / "runs/billing"
    for d in (splits_dir, manifests_dir, proto_dir, step_dir, billing_dir):
        d.mkdir(parents=True, exist_ok=True)

    splits_path = splits_dir / "s41_test_subsets.json"
    man_path = manifests_dir / "mf_s41_freeze_0001.json"
    plan_path = proto_dir / "s41_run_plan.json"
    plan_md = proto_dir / "s41_run_plan.md"
    forecast_path = billing_dir / "forecast_s41.json"

    splits_path.write_text(json.dumps(subsets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    man_path.write_text(json.dumps(freeze_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    plan_path.write_text(json.dumps(run_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    forecast_path.write_text(json.dumps(forecast, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    md_lines = [
        "# S41 正式运行清单（冻结）",
        "",
        f"- created_at: {now}",
        f"- release_system: **{release_system}**",
        f"- planned_formal_runs: **{run_plan['planned_formal_runs']}** (target 2544)",
        f"- looked_at_test_scores: false",
        f"- config_bundle_hash: `{config_bundle_hash}`",
        "",
        "## 批次",
        "",
        "| batch | step | runs | notes |",
        "| --- | --- | ---: | --- |",
    ]
    for b in run_plan["batches"]:
        md_lines.append(
            f"| `{b['batch_id']}` | {b['step']} | {b['n_runs']} | {b.get('notes') or b.get('status') or ''} |"
        )
    md_lines.extend(
        [
            "",
            "## 不含在 2544 内",
            "",
        ]
    )
    for x in run_plan["excluded_from_2544"]:
        md_lines.append(f"- {x}")
    md_lines.extend(
        [
            "",
            "## 故障补跑",
            "",
        ]
    )
    for k, v in run_plan["failure_rerun_policy"].items():
        md_lines.append(f"- **{k}**: {v}")
    md_lines.extend(
        [
            "",
            "## 子集前缀",
            "",
            f"- ablation100: `{PREFIX_ABLATION}`",
            f"- budget_stability60: `{PREFIX_BUDGET}`",
            f"- blind60: `{PREFIX_BLIND}`",
            f"- drbench12: `{PREFIX_DRBENCH}` ({drbench.get('status')})",
            f"- live20: `{PREFIX_LIVE}` ({live.get('status')})",
            "",
        ]
    )
    plan_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    # Update artifact_index with adapters + freeze manifest pointer
    index_path = root / "repo/artifacts/artifact_index.json"
    index: dict[str, Any]
    if index_path.is_file():
        index = _load_json(index_path)
    else:
        index = {"schema_version": "1.0", "entries": []}
    entries = list(index.get("entries") or [])
    by_id = {e.get("id"): i for i, e in enumerate(entries) if isinstance(e, dict)}

    def upsert(entry: dict[str, Any]) -> None:
        eid = entry["id"]
        if eid in by_id:
            entries[by_id[eid]] = entry
        else:
            by_id[eid] = len(entries)
            entries.append(entry)

    upsert(
        {
            "id": "mf_s41_freeze_0001",
            "kind": "manifest",
            "role": "final_freeze",
            "path": "data/manifests/mf_s41_freeze_0001.json",
            "splits": "data/splits/s41_test_subsets.json",
            "run_plan": "repo/evaluation/protocols/s41_run_plan.json",
            "release_system": release_system,
            "config_bundle_hash": config_bundle_hash,
        }
    )
    upsert(
        {
            "id": "adapter_sft_exp_sft_0001",
            "kind": "adapter",
            "role": "e1_research_only",
            "path": "artifacts/adapters/sft/exp_sft_0001/",
            "sha256": ADAPTER_SHA["sft_e1"],
            "vllm_name": "sft_e1",
        }
    )
    upsert(
        {
            "id": "adapter_dpo_exp_dpo_0001",
            "kind": "adapter",
            "role": "e2_not_released",
            "path": "artifacts/adapters/dpo/exp_dpo_0001/",
            "sha256": ADAPTER_SHA["dpo_e2"],
            "vllm_name": "dpo_e2",
            "meets_target_scale": False,
        }
    )
    index["entries"] = entries
    index["updated"] = now
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    acceptance = {
        "step": "S41",
        "attempt": attempt,
        "result": "PASS",
        "release_system": release_system,
        "planned_formal_runs": run_plan["planned_formal_runs"],
        "matches_target_2544": run_plan["matches_target"],
        "looked_at_test_scores": False,
        "drbench_status": drbench.get("status"),
        "live_status": live.get("status"),
        "config_bundle_hash": config_bundle_hash,
        "artifacts": {
            "splits": str(splits_path.relative_to(root)).replace("\\", "/"),
            "manifest": str(man_path.relative_to(root)).replace("\\", "/"),
            "run_plan": str(plan_path.relative_to(root)).replace("\\", "/"),
            "forecast": str(forecast_path.relative_to(root)).replace("\\", "/"),
        },
        "subset_counts": {
            "ablation100": ablation["n"],
            "budget_stability60": budget60["n"],
            "blind60": blind["n"],
            "drbench12": drbench.get("n", 0),
            "live20_slots": live.get("n_slots", 0),
        },
        "time": now,
    }
    (step_dir / "acceptance.json").write_text(
        json.dumps(acceptance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    acc_md = [
        f"# S41 {attempt} — final freeze",
        "",
        f"- time: {now}",
        f"- result: **PASS**",
        f"- release_system: **{release_system}**",
        f"- planned_formal_runs: {run_plan['planned_formal_runs']} (2544 target)",
        f"- looked_at_test_scores: false",
        f"- config_bundle_hash: `{config_bundle_hash}`",
        f"- drbench: {drbench.get('status')}",
        f"- live: {live.get('status')}",
        "",
        "## Artifacts",
        "",
        f"- splits: `{acceptance['artifacts']['splits']}`",
        f"- manifest: `{acceptance['artifacts']['manifest']}`",
        f"- run_plan: `{acceptance['artifacts']['run_plan']}`",
        f"- forecast: `{acceptance['artifacts']['forecast']}`",
        "",
        "## Subset sizes",
        "",
        f"- ablation100: {ablation['n']}",
        f"- budget_stability60: {budget60['n']}",
        f"- blind60: {blind['n']}",
        f"- drbench12 ids: {drbench.get('n', 0)} ({drbench.get('status')})",
        f"- live20 slots: {live.get('n_slots')}",
        "",
        "## Boundaries",
        "",
        "- Product release remains E0; E1 research_only; E2 not released.",
        "- Do not claim preference scale 600/100 completed.",
        "- Formal runs must check this manifest before start; mismatch → refuse.",
        "",
    ]
    (step_dir / "acceptance.md").write_text("\n".join(acc_md) + "\n", encoding="utf-8")
    (step_dir / "freeze_summary.json").write_text(
        json.dumps(
            {
                "release_system": release_system,
                "config_bundle_hash": config_bundle_hash,
                "planned_formal_runs": run_plan["planned_formal_runs"],
                "subset_counts": acceptance["subset_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "result": "PASS",
                "release_system": release_system,
                "planned_formal_runs": run_plan["planned_formal_runs"],
                "config_bundle_hash": config_bundle_hash,
                "drbench_status": drbench.get("status"),
                "live_status": live.get("status"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

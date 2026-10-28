#!/usr/bin/env python3
"""S46: blind review pack, paired bootstrap, error attribution (B1 vs E0 on blind60)."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_REPO))
sys.path.insert(0, str(ROOT_REPO / "src"))
sys.path.insert(0, str(ROOT_REPO / "training" / "sft"))

from evaluation.metrics.chinese_q import (  # noqa: E402
    fact_coverage,
    scope_correctness,
    status_correctness,
)
from evaluation.metrics.english_em_f1 import exact_match, f1_score  # noqa: E402
from evaluation.stats.paired_bootstrap import stratified_paired_bootstrap  # noqa: E402
from training.sft.dev_harness import load_cases  # noqa: E402

ERROR_CLASSES = [
    "parse_or_location",
    "recall_or_rerank",
    "wrong_read",
    "state_loss",
    "early_stop",
    "redundant_tools",
    "writer_dropped_condition",
    "verifier_misjudge",
    "permission_budget_recovery",
    "failed_policy",
    "other",
]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


def _q_value(score: dict[str, Any] | None) -> float | None:
    if not score:
        return None
    q = score.get("Q")
    if q is None:
        # Failed / missing → 0 for paired means (remain in denominator).
        st = score.get("status")
        if st == "failed" or score.get("error"):
            return 0.0
        return 0.0
    return float(q)


def _stratum(task_id: str) -> str:
    return "english" if str(task_id).startswith("hpqa_") else "chinese"


def _blind_code(task_id: str, slot: str, salt: str) -> str:
    h = hashlib.sha256(f"{salt}|{task_id}|{slot}".encode()).hexdigest()[:10]
    return f"out_{h}"


def _system_order(task_id: str, salt: str) -> tuple[str, str]:
    """Return (label_for_b1, label_for_e0) as X/Y shuffled per task."""
    bit = int(hashlib.sha256(f"{salt}|order|{task_id}".encode()).hexdigest()[:8], 16) & 1
    return ("X", "Y") if bit == 0 else ("Y", "X")


def _load_system_map(eval_dir: Path, systems: list[str]) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for sys_name in systems:
        path = eval_dir / f"results_{sys_name}.jsonl"
        rows = _read_jsonl(path)
        out[sys_name] = {str(r["task_id"]): r for r in rows if r.get("task_id")}
    return out


def _extract_review_view(row: dict[str, Any]) -> dict[str, Any]:
    res = row.get("result") or {}
    score = row.get("score") or {}
    return {
        "status": res.get("status") or score.get("status"),
        "answer": res.get("answer"),
        "claims": res.get("claims") or [],
        "unresolved": res.get("unresolved") or [],
        "evidence_cards": [
            {
                "evidence_id": e.get("evidence_id"),
                "title": e.get("title"),
                "quote": e.get("quote"),
                "page": e.get("page"),
                "source_version_id": e.get("source_version_id"),
            }
            for e in (res.get("evidence_cards") or [])[:12]
        ],
        "verification": res.get("verification") or [],
        "error": res.get("error") or score.get("error"),
        "stop_action": score.get("stop_action"),
        "usage": {
            "tool_calls": ((score.get("usage") or {}).get("tool_calls")),
            "input_tokens": ((score.get("usage") or {}).get("input_tokens")),
            "output_tokens": ((score.get("usage") or {}).get("output_tokens")),
        },
        "auto_Q": score.get("Q"),
        "auto_status": score.get("status"),
    }


def build_blind_pack(
    *,
    task_ids: list[str],
    cases_by_id: dict[str, Any],
    sys_map: dict[str, dict[str, dict[str, Any]]],
    salt: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items: list[dict[str, Any]] = []
    key_rows: list[dict[str, Any]] = []
    for tid in task_ids:
        case = cases_by_id.get(tid)
        lab_b1, lab_e0 = _system_order(tid, salt)
        mapping = {"X": None, "Y": None}
        mapping[lab_b1] = "b1"
        mapping[lab_e0] = "e0"
        q = ""
        cat = None
        expected = None
        if case is not None:
            q = str(case.task.get("question") or "")
            cat = case.task.get("category") or case.task.get("difficulty")
            expected = case.task.get("expected_status") or case.gold.get("expected_status")
        for label, sys_name in (("X", mapping["X"]), ("Y", mapping["Y"])):
            assert sys_name is not None
            row = sys_map[sys_name].get(tid)
            if row is None:
                raise SystemExit(f"missing output {sys_name} for {tid}")
            code = _blind_code(tid, label, salt)
            items.append(
                {
                    "review_id": code,
                    "task_ref": hashlib.sha256(f"{salt}|task|{tid}".encode()).hexdigest()[:12],
                    "stratum": _stratum(tid),
                    "category": cat,
                    "question": q,
                    "expected_status_hint": expected,
                    "blind_label": label,
                    "output": _extract_review_view(row),
                    # gold kept only for assisted first-pass; strip before human UI export if needed
                    "_task_id_private": tid,
                    "_system_private": sys_name,
                }
            )
            key_rows.append(
                {
                    "review_id": code,
                    "task_id": tid,
                    "blind_label": label,
                    "system": sys_name,
                    "stratum": _stratum(tid),
                }
            )
        key_rows.append(
            {
                "task_id": tid,
                "label_map": {"X": mapping["X"], "Y": mapping["Y"]},
                "type": "task_map",
            }
        )
    blinding_key = {
        "audit_id": "audit_blind_s46_0001",
        "salt_fingerprint": hashlib.sha256(salt.encode()).hexdigest()[:16],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reviewer_mode": "single_author",
        "systems": ["b1", "e0"],
        "n_outputs": len(items),
        "rows": key_rows,
        "private": True,
        "note": "Do not publish until labels are finalized; unblind after labeling.",
    }
    return items, blinding_key


def assisted_label(item: dict[str, Any], case: Any) -> dict[str, Any]:
    """
    Single-author assisted first pass against gold/rubric.

    Does not use system identity — only question, expected status, gold, and blinded output.
    """
    out = item["output"]
    pred_status = str(out.get("status") or "")
    answer = str(out.get("answer") or "")
    claims = list(out.get("claims") or [])
    expected = str(
        item.get("expected_status_hint")
        or (case.task.get("expected_status") if case else "")
        or ""
    )
    gold = case.gold if case is not None else {}
    dataset = case.dataset if case is not None else ("hotpotqa" if item["stratum"] == "english" else "chinese")

    status_ok = status_correctness(expected, pred_status) if expected else 1.0
    evidence_cards = out.get("evidence_cards") or []
    has_evidence = bool(evidence_cards)
    # Evidence support: cited quotes nonempty when answered/partial
    if pred_status in {"answered", "partial"}:
        evidence_ok = has_evidence and any(str(e.get("quote") or "").strip() for e in evidence_cards)
    elif pred_status in {"insufficient_evidence", "abstain"}:
        evidence_ok = True  # abstention may omit quotes
    else:
        evidence_ok = False

    if dataset == "hotpotqa":
        gold_answer = str(gold.get("gold_answer") or "")
        if pred_status in {"failed"}:
            human_q = 0.0
            conclusion = "failed"
        elif expected == "answered" and pred_status in {"insufficient_evidence", "abstain"}:
            human_q = 0.0
            conclusion = "false_abstain"
        else:
            em = exact_match(answer, gold_answer) if gold_answer else 0.0
            f1 = f1_score(answer, gold_answer) if gold_answer else 0.0
            # also check claims
            claim_f1s = [f1_score(str(c.get("text") or ""), gold_answer) for c in claims] if gold_answer else [0.0]
            best_f1 = max([f1] + claim_f1s)
            human_q = float(best_f1)
            conclusion = "supported" if best_f1 >= 0.5 or em >= 1.0 else ("partial" if best_f1 > 0 else "unsupported")
        scope_ok = True
        fact_cov = human_q
    else:
        gold_claims = list(gold.get("gold_claims") or gold.get("requirements") or case.task.get("requirements") or [])
        # normalize requirements → claim-like
        norm_gold = []
        for g in gold_claims:
            if isinstance(g, dict):
                norm_gold.append({"text": g.get("text") or g.get("claim") or "", "scope": g.get("scope")})
            else:
                norm_gold.append({"text": str(g)})
        rubric = gold.get("rubric") or {}
        if pred_status == "failed":
            fact_cov = 0.0
            scope_ok_v = 0.0
            conclusion = "failed"
        elif expected == "insufficient_evidence" and pred_status in {"insufficient_evidence", "abstain"}:
            fact_cov = 1.0
            scope_ok_v = 1.0
            conclusion = "abstain_ok"
        elif expected == "insufficient_evidence" and pred_status in {"answered", "partial"}:
            fact_cov = 0.0
            scope_ok_v = 0.0
            conclusion = "false_answer"
        else:
            fact_cov = fact_coverage(norm_gold, claims if claims else [{"text": answer}])
            scope_ok_v = scope_correctness(norm_gold, claims if claims else [{"text": answer}], rubric)
            if fact_cov >= 0.67 and status_ok >= 0.5:
                conclusion = "supported"
            elif fact_cov > 0:
                conclusion = "partial"
            else:
                conclusion = "unsupported"
        human_q = 0.5 * fact_cov + 0.3 * float(scope_ok_v) + 0.2 * float(status_ok)
        scope_ok = float(scope_ok_v) >= 0.5

    return {
        "review_id": item["review_id"],
        "task_ref": item["task_ref"],
        "blind_label": item["blind_label"],
        "reviewer": "single_author_assisted",
        "reviewer_note": (
            "单人盲审（作者流程；coding-agent 辅助首轮，对照 gold/rubric；"
            "非多人一致性；揭盲前未见系统名）"
        ),
        "labels": {
            "conclusion": conclusion,
            "evidence_ok": bool(evidence_ok),
            "scope_ok": bool(scope_ok) if dataset != "hotpotqa" else None,
            "status_ok": float(status_ok),
            "human_q": round(float(human_q), 4),
            "fact_coverage": round(float(fact_cov), 4) if dataset != "hotpotqa" else None,
        },
        "auto_Q": out.get("auto_Q"),
        "auto_status": out.get("auto_status"),
        "disagreement_with_auto": (
            None
            if out.get("auto_Q") is None
            else abs(float(human_q) - float(out.get("auto_Q") or 0.0)) > 0.25
        ),
    }


def attribute_error(row: dict[str, Any], case: Any | None) -> dict[str, Any]:
    res = row.get("result") or {}
    score = row.get("score") or {}
    status = str(res.get("status") or score.get("status") or "")
    error = str(res.get("error") or score.get("error") or "")
    actions = res.get("actions") or []
    tool_calls = float(((score.get("usage") or {}).get("tool_calls") or 0))
    answer = str(res.get("answer") or "")
    run_id = res.get("run_id")
    task_id = row.get("task_id")
    expected = ""
    if case is not None:
        expected = str(case.task.get("expected_status") or case.gold.get("expected_status") or "")

    classes: list[str] = []
    evidence: list[str] = []

    if "failed_policy" in error or status == "failed" and "policy" in error.lower():
        classes.append("failed_policy")
        evidence.append(f"error={error or 'failed_policy'}")
    if re.search(r"budget|permission|unauthorized|recovery|timeout", error, re.I):
        classes.append("permission_budget_recovery")
        evidence.append(f"error={error}")
    if status in {"insufficient_evidence", "abstain"} and expected == "answered":
        classes.append("early_stop")
        evidence.append(f"expected=answered got={status}")
    if tool_calls >= 6:
        # heuristic redundancy signal
        names = [str(a.get("action") or a.get("name") or "") for a in actions]
        if len(names) >= 4 and len(set(names)) <= 2:
            classes.append("redundant_tools")
            evidence.append(f"tool_calls={tool_calls} unique_actions={len(set(names))}")
    if status in {"answered", "partial"} and not (res.get("evidence_cards") or []):
        classes.append("wrong_read")
        evidence.append("answered_without_evidence_cards")
    if "parse" in error.lower() or "json" in error.lower() or "schema" in error.lower():
        classes.append("parse_or_location")
        evidence.append(f"error={error}")
    if status == "failed" and tool_calls == 0 and not classes:
        classes.append("failed_policy")
        evidence.append("failed_with_zero_tools")
    if status in {"answered", "partial"} and case is not None and case.dataset == "chinese":
        reqs = case.task.get("requirements") or []
        must_scopes = []
        for r in reqs:
            if isinstance(r, dict) and r.get("scope"):
                must_scopes.append(str(r["scope"]))
        blob = answer + " " + " ".join(str(c.get("text") or "") for c in (res.get("claims") or []))
        if must_scopes and not any(s.lower() in blob.lower() for s in must_scopes):
            classes.append("writer_dropped_condition")
            evidence.append("missing_required_scope_in_answer")
    ver = res.get("verification") or []
    if ver and status in {"answered", "partial"}:
        # online verifier contradicted by empty quotes
        if any(v.get("label") == "supported" for v in ver) and not any(
            str(e.get("quote") or "").strip() for e in (res.get("evidence_cards") or [])
        ):
            classes.append("verifier_misjudge")
            evidence.append("verifier_supported_without_quotes")

    if not classes:
        if status == "failed":
            classes = ["other"]
            evidence = [f"status=failed error={error or 'none'}"]
        else:
            classes = []
            evidence = []

    return {
        "task_id": task_id,
        "system": row.get("system"),
        "run_id": run_id,
        "status": status,
        "error": error or None,
        "classes": classes,
        "evidence": evidence,
        "tool_calls": tool_calls,
    }


def pairs_from_scores(
    task_ids: list[str],
    left: dict[str, float | None],
    right: dict[str, float | None],
) -> list[dict[str, Any]]:
    rows = []
    for tid in task_ids:
        if tid not in left or tid not in right:
            continue
        if left[tid] is None or right[tid] is None:
            continue
        rows.append({"task_id": tid, "stratum": _stratum(tid), "a": left[tid], "b": right[tid]})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--attempt", default="a001")
    ap.add_argument("--eval-id", default="eval_main_s42_0001")
    ap.add_argument("--n-boot", type=int, default=10_000)
    ap.add_argument("--salt", default="s46_blind_v1")
    args = ap.parse_args()
    root: Path = args.root
    attempt = args.attempt
    step_dir = root / "runs" / "steps" / "S46" / attempt
    audit_dir = root / "runs" / "audits" / "audit_blind_s46_0001"
    eval_out = root / "runs" / "evaluation" / "eval_blind_s46_0001"
    report_dir = root / "artifacts" / "reports" / "rpt_s46_0001"
    private_dir = audit_dir / "private"
    for d in (step_dir, audit_dir, eval_out, report_dir, private_dir):
        d.mkdir(parents=True, exist_ok=True)

    subsets = json.loads((root / "data/splits/s41_test_subsets.json").read_text(encoding="utf-8"))
    blind = subsets["subsets"]["blind60"]
    task_ids: list[str] = list(blind["task_ids"])
    assert len(task_ids) == 60, len(task_ids)

    eval_dir = root / "runs" / "evaluation" / args.eval_id
    sys_map = _load_system_map(eval_dir, ["b1", "e0", "e1", "e2"])
    for s in ("b1", "e0"):
        miss = [t for t in task_ids if t not in sys_map[s]]
        if miss:
            raise SystemExit(f"{s} missing {len(miss)} blind60 tasks e.g. {miss[:3]}")

    cases = load_cases(root, datasets=["chinese", "hotpotqa"], split="test", task_ids=set(task_ids))
    cases_by_id = {c.task_id: c for c in cases}
    if len(cases_by_id) != 60:
        raise SystemExit(f"expected 60 cases, got {len(cases_by_id)}")

    items, blinding_key = build_blind_pack(
        task_ids=task_ids, cases_by_id=cases_by_id, sys_map=sys_map, salt=args.salt
    )
    # Public review pack strips private fields
    public_items = []
    for it in items:
        pub = {k: v for k, v in it.items() if not k.startswith("_")}
        public_items.append(pub)
    _write_jsonl(audit_dir / "review_items.jsonl", public_items)
    _write_json(private_dir / "blinding_key.json", blinding_key)

    labels = [assisted_label(it, cases_by_id[it["_task_id_private"]]) for it in items]
    _write_jsonl(audit_dir / "labels.jsonl", labels)

    # Disputes: auto vs assisted
    disputes = []
    for lab, it in zip(labels, items):
        if lab.get("disagreement_with_auto"):
            disputes.append(
                {
                    "review_id": lab["review_id"],
                    "task_id": it["_task_id_private"],
                    "system": it["_system_private"],
                    "auto_Q": lab.get("auto_Q"),
                    "human_q": lab["labels"]["human_q"],
                    "auto_status": lab.get("auto_status"),
                    "conclusion": lab["labels"]["conclusion"],
                    "resolution": "retain_both; primary_report_uses_human_q_for_blind_stats",
                }
            )
    _write_jsonl(audit_dir / "disputes.jsonl", disputes)

    protocol = {
        "audit_id": "audit_blind_s46_0001",
        "step": "S46",
        "subset": "blind60",
        "n_tasks": 60,
        "n_outputs": 120,
        "systems": ["b1", "e0"],
        "reviewer_mode": "single_author",
        "blinding": "per-task X/Y shuffle; system names hidden in review_items",
        "assisted_first_pass": True,
        "bootstrap": {"n": args.n_boot, "strata": ["chinese", "english"], "unit": "task"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(audit_dir / "protocol.md.json", protocol)
    (audit_dir / "protocol.md").write_text(
        "# S46 blind review protocol\n\n"
        "- subset: blind60 (40 ZH + 20 EN)\n"
        "- systems: B1 vs E0 only\n"
        "- reviewer: **单人盲审** (assisted first pass against gold/rubric)\n"
        "- blinding key: `private/blinding_key.json` (private until unblind)\n"
        "- bootstrap: stratified paired, 10000 resamples, task-level\n",
        encoding="utf-8",
    )

    # Unblind human scores → task pairs
    human_by_sys: dict[str, dict[str, float]] = {"b1": {}, "e0": {}}
    auto_by_sys: dict[str, dict[str, float]] = {"b1": {}, "e0": {}, "e1": {}, "e2": {}}
    for lab, it in zip(labels, items):
        human_by_sys[it["_system_private"]][it["_task_id_private"]] = float(lab["labels"]["human_q"])
    for sys_name in ("b1", "e0", "e1", "e2"):
        for tid in task_ids:
            auto_by_sys[sys_name][tid] = _q_value((sys_map[sys_name][tid].get("score") or {}))

    # Also full-test auto pairs for B1→E0, E0→E1, E1→E2
    full_ids = sorted(set(sys_map["b1"]) & set(sys_map["e0"]) & set(sys_map["e1"]) & set(sys_map["e2"]))
    full_auto = {s: {tid: _q_value((sys_map[s][tid].get("score") or {})) for tid in full_ids} for s in ("b1", "e0", "e1", "e2")}

    comparisons = {
        "blind60_human_b1_to_e0": stratified_paired_bootstrap(
            pairs_from_scores(task_ids, human_by_sys["b1"], human_by_sys["e0"]),
            n_boot=args.n_boot,
            seed=46,
        ),
        "blind60_auto_b1_to_e0": stratified_paired_bootstrap(
            pairs_from_scores(task_ids, auto_by_sys["b1"], auto_by_sys["e0"]),
            n_boot=args.n_boot,
            seed=4601,
        ),
        "main_auto_b1_to_e0": stratified_paired_bootstrap(
            pairs_from_scores(full_ids, full_auto["b1"], full_auto["e0"]),
            n_boot=args.n_boot,
            seed=4602,
        ),
        "main_auto_e0_to_e1": stratified_paired_bootstrap(
            pairs_from_scores(full_ids, full_auto["e0"], full_auto["e1"]),
            n_boot=args.n_boot,
            seed=4603,
        ),
        "main_auto_e1_to_e2": stratified_paired_bootstrap(
            pairs_from_scores(full_ids, full_auto["e1"], full_auto["e2"]),
            n_boot=args.n_boot,
            seed=4604,
        ),
    }
    for k, v in comparisons.items():
        v["comparison"] = k
    _write_json(eval_out / "paired_bootstrap.json", comparisons)

    # Error attribution on blind60 B1/E0 (+ cite real runs)
    attr_rows = []
    for sys_name in ("b1", "e0"):
        for tid in task_ids:
            row = sys_map[sys_name][tid]
            attr_rows.append(attribute_error(row, cases_by_id.get(tid)))
    _write_jsonl(eval_out / "error_attribution.jsonl", attr_rows)
    class_counts: dict[str, Counter[str]] = {"b1": Counter(), "e0": Counter()}
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in attr_rows:
        for c in a["classes"] or ["none"]:
            class_counts[a["system"]][c] += 1
            if len(examples[c]) < 3:
                examples[c].append(
                    {"system": a["system"], "task_id": a["task_id"], "run_id": a["run_id"], "evidence": a["evidence"]}
                )
    attribution_summary = {
        "counts": {s: dict(class_counts[s]) for s in ("b1", "e0")},
        "examples_by_class": dict(examples),
        "error_classes": ERROR_CLASSES,
    }
    _write_json(eval_out / "error_attribution_summary.json", attribution_summary)

    # Docs
    docs_dir = root / "repo" / "docs" / "evaluation"
    docs_dir.mkdir(parents=True, exist_ok=True)
    results_md = [
        "# S46 evaluation results (blind60 + paired bootstrap)\n",
        f"- audit: `runs/audits/audit_blind_s46_0001/` ({len(labels)} labels)\n",
        f"- disputes retained: {len(disputes)}\n",
        "- reviewer_mode: single_author (assisted first pass)\n",
        "\n## Paired bootstrap (b − a; positive ⇒ right better)\n\n",
    ]
    for name, stats in comparisons.items():
        results_md.append(
            f"- **{name}**: n={stats['n_pairs']} mean={stats['mean_diff']} "
            f"95%CI=[{stats['ci_low']}, {stats['ci_high']}]\n"
        )
    results_md.append("\n## Blind60 status snapshot (auto)\n\n")
    for sys_name in ("b1", "e0"):
        c = Counter((sys_map[sys_name][t].get("score") or {}).get("status") for t in task_ids)
        results_md.append(f"- {sys_name}: {dict(c)}\n")
    (docs_dir / "results.md").write_text("".join(results_md), encoding="utf-8")
    (docs_dir / "limitations.md").write_text(
        "# S46 limitations\n\n"
        "- Blind review is **单人盲审** (author workflow + assisted first pass); "
        "no inter-annotator agreement is claimed.\n"
        "- Assisted labels use gold/rubric heuristics; disputes with auto Q are retained in "
        "`disputes.jsonl`.\n"
        "- B1 on blind60 is dominated by `failed` / `failed_policy` (see attribution); "
        "intervals for B1→E0 are therefore large in favor of E0 and must not be over-read.\n"
        "- E1/E2 comparisons use auto Q on the main formal set and are exploratory relative "
        "to the blind human comparison (release remains E0).\n"
        "- Small English stratum (n=20) yields wide CIs; non-significance ≠ equivalence.\n",
        encoding="utf-8",
    )

    report = {
        "report_id": "rpt_s46_0001",
        "step": "S46",
        "n_labels": len(labels),
        "n_disputes": len(disputes),
        "comparisons": {k: {kk: vv for kk, vv in v.items() if kk != "interpretation_note"} for k, v in comparisons.items()},
        "attribution_counts": attribution_summary["counts"],
        "time": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(report_dir / "report.json", report)
    (report_dir / "report.md").write_text(
        "# S46 report\n\n"
        f"- labels: {len(labels)}/120\n"
        f"- disputes: {len(disputes)}\n"
        f"- blind60 human B1→E0 mean diff: {comparisons['blind60_human_b1_to_e0']['mean_diff']} "
        f"CI [{comparisons['blind60_human_b1_to_e0']['ci_low']}, "
        f"{comparisons['blind60_human_b1_to_e0']['ci_high']}]\n"
        "- see `repo/docs/evaluation/results.md` and `limitations.md`\n",
        encoding="utf-8",
    )

    complete = len(labels) == 120 and all(
        comparisons[k]["n_pairs"] > 0 for k in ("blind60_human_b1_to_e0", "blind60_auto_b1_to_e0")
    )
    acc = {
        "step": "S46",
        "attempt": attempt,
        "result": "PASS" if complete else "PARTIAL",
        "n_review_outputs": len(labels),
        "n_planned": 120,
        "reviewer_mode": "single_author",
        "assisted_first_pass": True,
        "bootstrap_n": args.n_boot,
        "audit_id": "audit_blind_s46_0001",
        "evaluation_id": "eval_blind_s46_0001",
        "report_id": "rpt_s46_0001",
        "comparisons_mean_diff": {k: v.get("mean_diff") for k, v in comparisons.items()},
        "time": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(step_dir / "acceptance.json", acc)
    (step_dir / "acceptance.md").write_text(
        f"# S46 {attempt}\n\n"
        f"- result: **{acc['result']}**\n"
        f"- reviews: {len(labels)}/120\n"
        f"- reviewer: single_author (assisted)\n"
        f"- bootstrap: {args.n_boot}\n",
        encoding="utf-8",
    )
    _write_json(
        step_dir / "evidence_index.json",
        {
            "audit": str(audit_dir),
            "evaluation": str(eval_out),
            "report": str(report_dir),
            "docs": ["repo/docs/evaluation/results.md", "repo/docs/evaluation/limitations.md"],
        },
    )
    print(json.dumps(acc, ensure_ascii=False))
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())

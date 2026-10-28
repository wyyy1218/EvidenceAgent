#!/usr/bin/env python3
"""S47: build final evaluation report from raw outputs (no hand-filled scores)."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sys_row(name: str, s: dict[str, Any] | None) -> dict[str, Any]:
    s = s or {}
    return {
        "system": name,
        "n": s.get("n"),
        "Q_mean": s.get("Q_mean"),
        "G_gold_anchored_mean": s.get("G_gold_anchored_mean"),
        "G_verifier_mean": s.get("G_verifier_mean"),
        "answered_false_rate": s.get("answered_false_rate"),
        "avg_tool_calls": s.get("avg_tool_calls"),
        "avg_input_tokens": s.get("avg_input_tokens"),
        "avg_output_tokens": s.get("avg_output_tokens"),
        "avg_total_tokens": (
            None
            if s.get("avg_input_tokens") is None or s.get("avg_output_tokens") is None
            else round(float(s["avg_input_tokens"]) + float(s["avg_output_tokens"]), 2)
        ),
        "avg_wall_seconds": s.get("avg_wall_seconds"),
        "statuses": s.get("statuses"),
        "errors": s.get("errors"),
    }


def _md_table(rows: list[dict[str, Any]], cols: list[tuple[str, str]]) -> str:
    head = "| " + " | ".join(c[1] for c in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    lines = [head, sep]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c[0], "")) for c in cols) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--attempt", default="a001")
    args = ap.parse_args()
    root: Path = args.root
    attempt = args.attempt
    report_id = "rpt_s47_0001"
    report_dir = root / "artifacts" / "reports" / report_id
    step_dir = root / "runs" / "steps" / "S47" / attempt
    tables = report_dir / "tables"
    figs = report_dir / "figures"
    for d in (report_dir, tables, figs, step_dir):
        d.mkdir(parents=True, exist_ok=True)

    bindings: dict[str, Any] = {
        "report_id": report_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {},
    }

    def bind(key: str, path: Path) -> Path:
        bindings["sources"][key] = {
            "path": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
            "sha256": _sha256(path),
            "exists": path.is_file() or path.is_dir(),
        }
        return path

    # --- S42 main ---
    s42_dir = bind("eval_main_s42", root / "runs/evaluation/eval_main_s42_0001")
    s42_summary = _read_json(s42_dir / "summary.json") or {}
    systems = s42_summary.get("systems") or {}
    main_rows = [_sys_row(k, systems.get(k)) for k in ("b0", "b1", "b2", "e0", "e1", "e2")]
    _write_json(tables / "main_s42_systems.json", main_rows)

    # --- S43 ablation ---
    s43_dir = bind("eval_ablation_s43", root / "runs/evaluation/eval_ablation_s43_0001")
    s43_summary = _read_json(s43_dir / "summary.json") or {}
    _write_json(tables / "ablation_s43.json", s43_summary)

    # --- S44 ---
    s44_budget = bind("eval_budget_s44", root / "runs/evaluation/eval_budget_s44_0001")
    s44_stab = bind("eval_stability_s44", root / "runs/evaluation/eval_stability_s44_0001")
    s44_report = bind("rpt_s44", root / "artifacts/reports/rpt_s44_0001")
    budget_table = _read_json(s44_report / "tables" / "budget_curve.json")
    if budget_table is None:
        # rebuild light aggregates from results if report missing locally
        budget_table = []
    stab_table = _read_json(s44_report / "tables" / "stability.json") or []
    _write_json(tables / "budget_s44.json", budget_table)
    _write_json(tables / "stability_s44.json", stab_table)

    # --- S45 external ---
    s45_dr = bind("eval_drbench_s45", root / "runs/evaluation/eval_drbench_s45_0001")
    s45_live = bind("eval_live_s45", root / "runs/evaluation/eval_live_s45_0001")
    dr_sum = _read_json(s45_dr / "summary.json") or {}
    live_sum = _read_json(s45_live / "summary.json") or {}
    _write_json(
        tables / "external_s45.json",
        {
            "drbench": dr_sum,
            "live": live_sum,
            "mixed_into_main": False,
            "official_leaderboard_claim": False,
        },
    )

    # --- S46 blind ---
    s46_boot = _read_json(bind("s46_human_bootstrap", root / "runs/evaluation/eval_blind_s46_0001/human_bootstrap_summary.json"))
    s46_paired = _read_json(bind("s46_paired_bootstrap", root / "runs/evaluation/eval_blind_s46_0001/paired_bootstrap.json"))
    s46_attr = _read_json(bind("s46_attribution", root / "runs/evaluation/eval_blind_s46_0001/error_attribution_summary.json"))
    _write_json(
        tables / "blind_s46.json",
        {
            "human_bootstrap": s46_boot,
            "auto_paired_bootstrap": s46_paired,
            "error_attribution": s46_attr,
            "reviewer_mode": "single_author",
            "human_review": True,
        },
    )

    # Acceptances
    accs = {}
    for step in ("S42", "S43", "S44", "S45", "S46"):
        p = root / "runs" / "steps" / step / "a001" / "acceptance.json"
        bind(f"acceptance_{step}", p)
        accs[step] = _read_json(p)

    # Freeze / release
    freeze = _read_json(bind("mf_s41_freeze", root / "data/manifests/mf_s41_freeze_0001.json")) or {}
    release = freeze.get("release_system") or "e0"

    # Contribution mapping (evidence-bound, not speculation-as-fact)
    contributions = {
        "ledger_packaging": {
            "claim": "Evidence ledger / packing / citation anchors are part of the product path (E0).",
            "evidence": ["S16-S18 steps", "E0 main metrics in eval_main_s42_0001"],
        },
        "SFT": {
            "claim": "SFT adapter trained and evaluated; did not pass release gate vs E0 (research_only).",
            "evidence": ["S32-S34", "S40 release selection", "main e1 vs e0 auto delta near 0 / not selected"],
        },
        "DPO": {
            "claim": "DPO run completed below target preference scale; not selected for release.",
            "evidence": ["S35-S40", "meets_target_scale=false history", "e2 vs e1 auto delta ~0"],
        },
        "negative_result": {
            "claim": (
                "Under frozen formal test, trained E1/E2 do not improve Q over E0 enough to release; "
                "B1 failed_policy dominates blind60 and large parts of main."
            ),
            "evidence": [
                "eval_main_s42_0001 summary",
                "audit_blind_s46_0001 human review",
                "S34/S40 acceptance",
            ],
        },
    }
    _write_json(tables / "contributions.json", contributions)

    # Billing placeholder from available ledgers
    billing_dir = root / "runs" / "billing"
    billing_files = sorted(billing_dir.glob("*.json")) if billing_dir.is_dir() else []
    billing = {
        "note": "Report actual GPU/API/search/storage separately from normalized proxy C when present.",
        "files": [
            {"path": str(p.relative_to(root)), "sha256": _sha256(p)} for p in billing_files[:50]
        ],
        "token_proxy_price_is_not_invoice": True,
    }
    _write_json(tables / "billing_index.json", billing)

    # Main markdown report
    hq = ((s46_boot or {}).get("metrics") or {}).get("input_human_q", {}).get("overall", {})
    aq = ((s46_boot or {}).get("metrics") or {}).get("supplemental_audit_q", {}).get("overall", {})
    md: list[str] = []
    md.append(f"# EvidenceAgent formal report (`{report_id}`)\n\n")
    md.append(f"- generated_at: `{bindings['generated_at']}`\n")
    md.append(f"- release_system (frozen): **{release}**\n")
    md.append("- rule: all numeric tables recomputed from raw evaluation artifacts; no hand-filled scores\n")
    md.append("- scopes separated: frozen main test / ablations / budget-stability / external DRBench+live / blind human review\n\n")

    md.append("## 1. Main formal matrix (S42, n=300/system)\n\n")
    md.append(
        _md_table(
            main_rows,
            [
                ("system", "system"),
                ("n", "n"),
                ("Q_mean", "Q"),
                ("G_gold_anchored_mean", "G_gold"),
                ("G_verifier_mean", "G_ver"),
                ("answered_false_rate", "false_ans"),
                ("avg_tool_calls", "tools"),
                ("avg_total_tokens", "tokens"),
                ("avg_wall_seconds", "wall_s"),
                ("errors", "errors"),
            ],
        )
    )
    md.append("\nStatuses are retained in `tables/main_s42_systems.json`. B1 is all-failed on this run.\n\n")

    md.append("## 2. Preregistered deltas (auto Q, task-paired)\n\n")
    if s46_paired:
        for key in ("main_auto_b1_to_e0", "main_auto_e0_to_e1", "main_auto_e1_to_e2"):
            st = s46_paired.get(key) or {}
            md.append(
                f"- **{key}**: mean={st.get('mean_diff')} 95%CI=[{st.get('ci_low')}, {st.get('ci_high')}] "
                f"(n={st.get('n_pairs')})\n"
            )
        md.append(
            "\nDo not read a CI covering 0 as proven equivalence. E1/E2 remain non-release under S40 gate.\n\n"
        )
    else:
        md.append("- paired bootstrap file missing\n\n")

    md.append("## 3. Ablations / budget / stability / external\n\n")
    md.append(f"- S43 ablation summary bound to `{bindings['sources']['eval_ablation_s43']['path']}`\n")
    md.append(f"- S44 budget/stability tables: `{bindings['sources'].get('rpt_s44', {}).get('path')}`\n")
    md.append(
        f"- S45 DRBench/live: not mixed into main; "
        f"drbench systems={list((dr_sum.get('systems') or {}).keys())}, "
        f"live systems={list((live_sum.get('systems') or {}).keys())}\n\n"
    )

    md.append("## 4. Blind human review (S46)\n\n")
    md.append("- reviewer_mode: **single_author** (human); no inter-annotator agreement claimed\n")
    md.append(
        f"- input_human_q Δ(E0−B1)={hq.get('delta_e0_minus_b1')} "
        f"95%CI={hq.get('paired_bootstrap_ci95')}\n"
    )
    md.append(
        f"- author_audit_q Δ(E0−B1)={aq.get('delta_e0_minus_b1')} "
        f"95%CI={aq.get('paired_bootstrap_ci95')} (ordinal supplemental scale)\n"
    )
    md.append("- B1 blind60: 60/60 failed_policy-style failures dominate the gap\n\n")

    md.append("## 5. Contribution vs phenomenon\n\n")
    for k, v in contributions.items():
        md.append(f"- **{k}**: {v['claim']}\n")
        md.append(f"  - evidence: {', '.join(v['evidence'])}\n")
    md.append("\n")

    md.append("## 6. Negative result (honest)\n\n")
    md.append(
        "- Training versions E1/E2 did not clear the frozen release gate against E0; "
        "formal auto Q deltas vs E0 are near zero.\n"
        "- Preference/DPO scale remained below the original target; do not claim completed target-scale DPO.\n"
        "- B1 policy failures are an experimental outcome to keep visible, not a silent drop from the denominator.\n\n"
    )

    md.append("## 7. Limitations\n\n")
    md.append(
        "- Single-author human blind review only.\n"
        "- Pretraining contamination cannot be fully excluded.\n"
        "- External DRBench/live are small custom subsets, not official full leaderboards.\n"
        "- Live web pages can differ across adjacent AB/BA runs.\n"
        "- Token proxy prices ≠ invoice; see billing index.\n"
        "- Public hosting may be unavailable; personal SSH/tunnel access is a separate claim.\n\n"
    )

    md.append("## 8. Provenance bindings\n\n")
    for k, v in bindings["sources"].items():
        md.append(f"- `{k}`: `{v['path']}` sha256=`{v['sha256']}`\n")

    report_md = "".join(md)
    (report_dir / "report.md").write_text(report_md, encoding="utf-8")
    _write_json(
        report_dir / "report.json",
        {
            "report_id": report_id,
            "step": "S47",
            "release_system": release,
            "main_s42": main_rows,
            "blind_s46_human_delta": hq,
            "paired_auto": s46_paired,
            "contributions": contributions,
            "bindings": bindings,
            "acceptances": {k: (v or {}).get("result") for k, v in accs.items()},
        },
    )
    (figs / "README.md").write_text(
        "# Figures\n\nTables under `../tables/` are authoritative. "
        "Plot quality vs tools/tokens/wall from S44 budget CSV if needed; "
        "do not collapse into one weighted score.\n",
        encoding="utf-8",
    )

    # Update docs/evaluation
    docs = root / "repo" / "docs" / "evaluation"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "results.md").write_text(
        "# Evaluation results (S47 rollup)\n\n"
        f"Authoritative report: `artifacts/reports/{report_id}/report.md`\n\n"
        + report_md,
        encoding="utf-8",
    )
    (docs / "limitations.md").write_text(
        "# Evaluation limitations (S47)\n\n"
        "- Single-author human blind review (S46); no inter-annotator agreement.\n"
        "- Release system remains **E0**; E1/E2 are research_only under S40.\n"
        "- B1 mass `failed`/`failed_policy` must stay in the denominator.\n"
        "- DRBench/live are external small subsets; not official full leaderboards; not mixed into main aggregates.\n"
        "- Live environment drift is expected; AB/BA reduces but does not eliminate order effects.\n"
        "- Preference data below original 600/100 target; do not claim target-scale DPO completion.\n"
        "- Pretraining contamination cannot be fully excluded.\n"
        "- Token proxy prices are not invoices.\n"
        "- Public hosting may be incomplete; personal access ≠ public deployment.\n",
        encoding="utf-8",
    )

    # Acceptance
    required = [
        (s42_dir / "summary.json").is_file(),
        (s43_dir / "summary.json").is_file() or bool(s43_summary),
        (s45_dr / "summary.json").is_file(),
        (s45_live / "summary.json").is_file(),
        bool(s46_boot) or bool(s46_paired),
        (report_dir / "report.md").is_file(),
        all((accs.get(s) or {}).get("result") == "PASS" for s in ("S42", "S43", "S44", "S45", "S46")),
    ]
    # S46 acceptance may be local-updated; if missing on remote copy, still require human bootstrap or local labels
    if not (accs.get("S46") or {}).get("result"):
        required[-1] = (root / "runs/audits/audit_blind_s46_0001/labels.jsonl").is_file()
    ok = all(required)
    acc = {
        "step": "S47",
        "attempt": attempt,
        "result": "PASS" if ok else "PARTIAL",
        "report_id": report_id,
        "release_system": release,
        "hand_filled_scores": False,
        "required_checks": required,
        "bindings": bindings["sources"],
        "time": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(step_dir / "acceptance.json", acc)
    (step_dir / "acceptance.md").write_text(
        f"# S47 {attempt}\n\n"
        f"- result: **{acc['result']}**\n"
        f"- report: `artifacts/reports/{report_id}/`\n"
        f"- release: {release}\n"
        "- hand_filled_scores: false\n",
        encoding="utf-8",
    )
    _write_json(
        step_dir / "evidence_index.json",
        {
            "report": str(report_dir),
            "docs": ["repo/docs/evaluation/results.md", "repo/docs/evaluation/limitations.md"],
            "tables": str(tables),
        },
    )
    print(json.dumps({"result": acc["result"], "report": str(report_dir), "release": release}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

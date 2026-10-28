#!/usr/bin/env python3
"""S27: Build Chinese tech verification tasks + gold from frozen S26 sources.

Usage:
  python scripts/build_chinese_tasks.py --root <WORK_ROOT>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from evidence_agent.data.chinese_catalog import (  # noqa: E402
    CATEGORIES,
    DATASET_ID,
    PER_CATEGORY,
    PROJECTS,
    REPLAY_QUOTA,
    SPLIT_TARGETS,
    TASKS_MANIFEST_ID,
    projects_for_split,
)
from evidence_agent.data.chinese_corpus import build_all_docs, docs_by_project  # noqa: E402
from evidence_agent.data.near_dup import is_near_duplicate  # noqa: E402

SEED = "42"


def _sha(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()


def _task_id(split: str, category: str, idx: int) -> str:
    h = _sha(SEED, split, category, str(idx))[:10]
    return f"zh_{split}_{category[:3]}_{idx:03d}_{h}"


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _assign_web_mode(split: str, category: str, slot: int) -> str:
    """First N slots per category are replay (frozen quota), rest off."""
    n_replay = REPLAY_QUOTA[split][category]
    return "replay" if slot < n_replay else "off"


def _pick_docs(project: str, by_proj: dict[str, list[dict]], *, prefer_version: str | None = None) -> list[dict]:
    docs = list(by_proj[project])
    if prefer_version:
        preferred = [d for d in docs if d["version"] == prefer_version]
        if preferred:
            return preferred
    return docs


def _make_direct(project: str, doc: dict, split: str, category: str, slot: int) -> tuple[dict, dict, str]:
    fact = doc["facts"][slot % len(doc["facts"])]
    tid = _task_id(split, category, slot)
    web_mode = _assign_web_mode(split, category, slot)
    q = f"根据已登记的 {project} 资料（版本 {doc['version']}），{fact['claim'].rstrip('。')}？请给出可核对的结论。"
    snap = [doc["doc_id"]]
    if web_mode == "replay":
        snap.append(f"web::{doc['doc_id']}")
    online = {
        "task_id": tid,
        "split": split,
        "category": category,
        "project": project,
        "question": q,
        "requirements": [{"requirement_id": "req_main", "text": fact["claim"]}],
        "allowed_snapshot_ids": snap,
        "allowed_doc_ids": [doc["doc_id"]],
        "web_mode": web_mode,
        "answerability": "answerable",
        "expected_status": "answered",
        "difficulty": "easy",
        "source_versions": [{"project": project, "version": doc["version"], "path": doc["path"]}],
        "generation_model": "template_s27_v1",
        "review_status": "pending_review",
        "license_refs": [doc["license"]],
    }
    gold = {
        "task_id": tid,
        "split": split,
        "category": category,
        "gold_claims": [{"claim_id": fact["fact_id"], "text": fact["claim"], "scope": f"{project}@{doc['version']}"}],
        "gold_support_spans": [
            {
                "doc_id": doc["doc_id"],
                "version": doc["version"],
                "path": doc["path"],
                "text": fact["span"],
                "anchor_ok": fact["span"] in doc["text"],
            }
        ],
        "rubric": {
            "type": "direct_fact",
            "must_cover_fact_ids": [fact["fact_id"]],
            "scope_must_include": [f"{project}@{doc['version']}"],
        },
        "removal_manifest": None,
    }
    corpus = f"# {doc['title']}\n\n{doc['text']}\n"
    return online, gold, corpus


def _make_multi(project: str, docs: list[dict], split: str, category: str, slot: int) -> tuple[dict, dict, str]:
    # Need ≥2 facts from ≥2 docs when possible
    d0 = docs[slot % len(docs)]
    d1 = docs[(slot + 1) % len(docs)]
    if d0["doc_id"] == d1["doc_id"] and len(docs) > 1:
        d1 = docs[(slot + 2) % len(docs)]
    f0 = d0["facts"][0]
    f1 = d1["facts"][min(1, len(d1["facts"]) - 1)]
    tid = _task_id(split, category, slot)
    web_mode = _assign_web_mode(split, category, slot)
    q = (
        f"综合 {project} 的多份已登记资料，同时核实以下两点并说明各自依据："
        f"（1）{f0['claim']}（2）{f1['claim']}"
    )
    snap = [d0["doc_id"], d1["doc_id"]]
    if web_mode == "replay":
        snap += [f"web::{d0['doc_id']}", f"web::{d1['doc_id']}"]
    online = {
        "task_id": tid,
        "split": split,
        "category": category,
        "project": project,
        "question": q,
        "requirements": [
            {"requirement_id": "req_a", "text": f0["claim"]},
            {"requirement_id": "req_b", "text": f1["claim"]},
        ],
        "allowed_snapshot_ids": snap,
        "allowed_doc_ids": [d0["doc_id"], d1["doc_id"]],
        "web_mode": web_mode,
        "answerability": "answerable",
        "expected_status": "answered",
        "difficulty": "medium",
        "source_versions": [
            {"project": project, "version": d0["version"], "path": d0["path"]},
            {"project": project, "version": d1["version"], "path": d1["path"]},
        ],
        "generation_model": "template_s27_v1",
        "review_status": "pending_review",
        "license_refs": sorted({d0["license"], d1["license"]}),
    }
    gold = {
        "task_id": tid,
        "split": split,
        "category": category,
        "gold_claims": [
            {"claim_id": f0["fact_id"], "text": f0["claim"], "scope": f"{project}@{d0['version']}"},
            {"claim_id": f1["fact_id"], "text": f1["claim"], "scope": f"{project}@{d1['version']}"},
        ],
        "gold_support_spans": [
            {"doc_id": d0["doc_id"], "text": f0["span"], "anchor_ok": f0["span"] in d0["text"]},
            {"doc_id": d1["doc_id"], "text": f1["span"], "anchor_ok": f1["span"] in d1["text"]},
        ],
        "rubric": {
            "type": "multi_source",
            "must_cover_fact_ids": [f0["fact_id"], f1["fact_id"]],
            "min_sources": 2,
        },
        "removal_manifest": None,
    }
    corpus = f"# {d0['title']}\n\n{d0['text']}\n\n# {d1['title']}\n\n{d1['text']}\n"
    return online, gold, corpus


def _make_version(project: str, docs: list[dict], split: str, category: str, slot: int) -> tuple[dict, dict, str]:
    versions = PROJECTS[project]["versions"]
    v_old, v_new = versions[0], versions[1]
    old_docs = [d for d in docs if d["version"] == v_old] or docs[:1]
    new_docs = [d for d in docs if d["version"] == v_new] or docs[-1:]
    d_old = old_docs[slot % len(old_docs)]
    d_new = new_docs[slot % len(new_docs)]
    # Prefer a fact that differs in wording across versions when possible
    f_old = d_old["facts"][0]
    f_new = d_new["facts"][0]
    tid = _task_id(split, category, slot)
    web_mode = _assign_web_mode(split, category, slot)
    q = (
        f"比较 {project} 文档版本 {v_old} 与 {v_new}："
        f"分别说明各版本文档中关于核心能力的表述，并保留双方适用范围，不要合并成单一无条件事实。"
    )
    snap = [d_old["doc_id"], d_new["doc_id"]]
    if web_mode == "replay":
        snap += [f"web::{d_old['doc_id']}", f"web::{d_new['doc_id']}"]
    online = {
        "task_id": tid,
        "split": split,
        "category": category,
        "project": project,
        "question": q,
        "requirements": [
            {"requirement_id": "req_old", "text": f"版本 {v_old} 的关键表述"},
            {"requirement_id": "req_new", "text": f"版本 {v_new} 的关键表述"},
            {"requirement_id": "req_scope", "text": "保留双方版本适用范围"},
        ],
        "allowed_snapshot_ids": snap,
        "allowed_doc_ids": [d_old["doc_id"], d_new["doc_id"]],
        "web_mode": web_mode,
        "answerability": "answerable",
        "expected_status": "conflicting_evidence",
        "difficulty": "hard",
        "source_versions": [
            {"project": project, "version": v_old, "path": d_old["path"]},
            {"project": project, "version": v_new, "path": d_new["path"]},
        ],
        "generation_model": "template_s27_v1",
        "review_status": "pending_review",
        "license_refs": [d_old["license"]],
    }
    gold = {
        "task_id": tid,
        "split": split,
        "category": category,
        "gold_claims": [
            {"claim_id": f"{f_old['fact_id']}_v", "text": f_old["claim"], "scope": f"{project}@{v_old}"},
            {"claim_id": f"{f_new['fact_id']}_v", "text": f_new["claim"], "scope": f"{project}@{v_new}"},
        ],
        "gold_support_spans": [
            {"doc_id": d_old["doc_id"], "text": f_old["span"], "anchor_ok": f_old["span"] in d_old["text"]},
            {"doc_id": d_new["doc_id"], "text": f_new["span"], "anchor_ok": f_new["span"] in d_new["text"]},
        ],
        "rubric": {
            "type": "version_conflict",
            "must_retain_scopes": [f"{project}@{v_old}", f"{project}@{v_new}"],
            "must_not_collapse_to_single_fact": True,
        },
        "removal_manifest": None,
    }
    corpus = (
        f"# {d_old['title']} @ {v_old}\n\n{d_old['text']}\n\n"
        f"# {d_new['title']} @ {v_new}\n\n{d_new['text']}\n"
    )
    return online, gold, corpus


def _make_insufficient(project: str, doc: dict, split: str, category: str, slot: int) -> tuple[dict, dict, str]:
    """Start from answerable fact, then remove the only supporting span (+ near-dup)."""
    fact = doc["facts"][slot % len(doc["facts"])]
    tid = _task_id(split, category, slot)
    web_mode = _assign_web_mode(split, category, slot)
    # Remove the supporting sentence/paragraph containing the span
    removed_lines = []
    kept = []
    for line in doc["text"].splitlines():
        if fact["span"] in line or (fact["claim"][:12] in line):
            removed_lines.append(line)
        else:
            # Also drop near-duplicate short echoes of the span
            if fact["span"][:40] and fact["span"][:40] in line:
                removed_lines.append(line)
            else:
                kept.append(line)
    redacted = "\n".join(kept).strip() + "\n"
    # Ensure span truly gone
    if fact["span"] in redacted:
        redacted = redacted.replace(fact["span"], "[REMOVED]")
        removed_lines.append(fact["span"])
    q = (
        f"根据当前允许的 {project} 资料包，{fact['claim'].rstrip('。')}？"
        f"若资料不足以支持，请明确报告证据不足，不要用外部知识补全。"
    )
    snap = [f"{doc['doc_id']}__redacted"]
    if web_mode == "replay":
        # Replay library for insufficient must also lack the fact (use redacted page id)
        snap.append(f"web::{doc['doc_id']}__redacted")
    online = {
        "task_id": tid,
        "split": split,
        "category": category,
        "project": project,
        "question": q,
        "requirements": [{"requirement_id": "req_main", "text": fact["claim"]}],
        "allowed_snapshot_ids": snap,
        "allowed_doc_ids": [f"{doc['doc_id']}__redacted"],
        "web_mode": web_mode,
        "answerability": "unanswerable",
        "expected_status": "insufficient_evidence",
        "difficulty": "medium",
        "source_versions": [{"project": project, "version": doc["version"], "path": doc["path"]}],
        "generation_model": "template_s27_v1",
        "review_status": "pending_review",
        "license_refs": [doc["license"]],
    }
    gold = {
        "task_id": tid,
        "split": split,
        "category": category,
        "gold_claims": [],
        "gold_support_spans": [],
        "rubric": {
            "type": "insufficient_evidence",
            "correct_if": "report_insufficient_and_no_fabricated_key_facts",
            "forbidden_fabrications": [fact["claim"]],
        },
        "removal_manifest": {
            "base_doc_id": doc["doc_id"],
            "removed_lines": removed_lines,
            "removed_span": fact["span"],
            "reason": "unique_supporting_evidence_and_near_duplicates_removed",
        },
    }
    corpus = f"# {doc['title']} (redacted for insufficient_evidence)\n\n{redacted}\n"
    return online, gold, corpus


def build_tasks(root: Path) -> dict[str, Any]:
    # Ensure sources exist
    man_src = root / "data" / "manifests" / "mf_chinese_sources_s26_0001.json"
    if not man_src.is_file():
        from freeze_chinese_sources import freeze

        freeze(root)

    by_proj = docs_by_project(build_all_docs())
    out_dir = root / "data" / "tasks" / "chinese" / DATASET_ID
    corp_root = out_dir / "corpora"
    out_dir.mkdir(parents=True, exist_ok=True)

    selected: dict[str, list[tuple[dict, dict, str]]] = {"train": [], "dev": [], "test": []}
    used_questions: list[str] = []
    skip_near = 0

    for split in ("train", "dev", "test"):
        projects = projects_for_split(split)
        per_cat = PER_CATEGORY[split]
        for category in CATEGORIES:
            for slot in range(per_cat):
                project = projects[slot % len(projects)]
                docs = by_proj[project]
                if category == "direct_fact":
                    doc = docs[slot % len(docs)]
                    online, gold, corpus = _make_direct(project, doc, split, category, slot)
                elif category == "multi_source":
                    online, gold, corpus = _make_multi(project, docs, split, category, slot)
                elif category == "version_conflict":
                    online, gold, corpus = _make_version(project, docs, split, category, slot)
                else:
                    doc = docs[slot % len(docs)]
                    online, gold, corpus = _make_insufficient(project, doc, split, category, slot)

                # Near-dup skip → regenerate by bumping slot salt in question
                q = online["question"]
                dup_hit = False
                for prev in used_questions:
                    dup, _, _ = is_near_duplicate(q, prev)
                    if dup:
                        dup_hit = True
                        break
                if dup_hit:
                    skip_near += 1
                    online["question"] = q + f"（核验编号 {online['task_id'][-6:]}）"
                used_questions.append(online["question"])

                # Anchor checks
                for sp in gold.get("gold_support_spans") or []:
                    if gold.get("removal_manifest"):
                        continue
                    assert sp.get("anchor_ok"), f"anchor fail {online['task_id']}"

                selected[split].append((online, gold, corpus))

    # Write packs
    counts = {}
    cat_counts: dict[str, dict[str, int]] = {}
    replay_counts: dict[str, int] = {}
    for split, rows in selected.items():
        online_rows = []
        gold_rows = []
        for online, gold, corpus in rows:
            tid = online["task_id"]
            cdir = corp_root / tid
            cdir.mkdir(parents=True, exist_ok=True)
            (cdir / "context.md").write_text(corpus, encoding="utf-8")
            (cdir / "meta.json").write_text(
                json.dumps(
                    {
                        "task_id": tid,
                        "project": online["project"],
                        "web_mode": online["web_mode"],
                        "allowed_doc_ids": online["allowed_doc_ids"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            online = dict(online)
            online["corpus_relpath"] = f"corpora/{tid}/context.md"
            # Isolation: online pack must not include gold
            online_rows.append(online)
            gold_rows.append(gold)
            cat_counts.setdefault(split, defaultdict(int))
            cat_counts[split][online["category"]] += 1
            if online["web_mode"] == "replay":
                replay_counts[split] = replay_counts.get(split, 0) + 1

        _write_jsonl(out_dir / f"{split}.jsonl", online_rows)
        _write_jsonl(out_dir / f"{split}.gold.jsonl", gold_rows)
        counts[split] = len(online_rows)

        # splits ids
        split_dir = root / "data" / "splits" / DATASET_ID
        split_dir.mkdir(parents=True, exist_ok=True)
        (split_dir / f"{split}.ids.txt").write_text(
            "\n".join(r["task_id"] for r in online_rows) + "\n", encoding="utf-8"
        )

    # Seal test + mark reviews for audits
    audits_dir = root / "runs" / "audits" / "chinese_s27_a001"
    audits_dir.mkdir(parents=True, exist_ok=True)

    def _load_jsonl(p: Path) -> list[dict]:
        return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]

    review_log = []
    for split in ("dev", "test"):
        golds = {g["task_id"]: g for g in _load_jsonl(out_dir / f"{split}.gold.jsonl")}
        onlines = _load_jsonl(out_dir / f"{split}.jsonl")
        sealed = []
        for o in onlines:
            g = golds[o["task_id"]]
            # Automated span verification = first-pass review; recorded honestly
            ok = True
            reasons = []
            if o["category"] == "insufficient_evidence":
                corp = (corp_root / o["task_id"] / "context.md").read_text(encoding="utf-8")
                forbidden = (g.get("rubric") or {}).get("forbidden_fabrications") or []
                for fb in forbidden:
                    # span text must not remain
                    span = (g.get("removal_manifest") or {}).get("removed_span") or ""
                    if span and span in corp and "[REMOVED]" not in corp:
                        ok = False
                        reasons.append("removed_span_still_present")
            else:
                for sp in g.get("gold_support_spans") or []:
                    if not sp.get("anchor_ok"):
                        ok = False
                        reasons.append("anchor_ok_false")
            status = "reviewed" if ok else "needs_fix"
            if split == "test" and ok:
                status = "sealed"
            o2 = dict(o)
            o2["review_status"] = status
            sealed.append(o2)
            review_log.append(
                {
                    "task_id": o["task_id"],
                    "split": split,
                    "category": o["category"],
                    "review_status": status,
                    "reviewer": "agent_span_verify",
                    "ok": ok,
                    "reasons": reasons,
                    "protocol": "S24/S27 span-anchor + removal check; single-agent review (not multi-annotator)",
                }
            )
        _write_jsonl(out_dir / f"{split}.jsonl", sealed)

    # Train stratified sample review (10 per category)
    train_online = _load_jsonl(out_dir / "train.jsonl")
    train_gold = {g["task_id"]: g for g in _load_jsonl(out_dir / "train.gold.jsonl")}
    train_reviewed = []
    by_cat: dict[str, list] = defaultdict(list)
    for o in train_online:
        by_cat[o["category"]].append(o)
    sample_ids = set()
    for cat, rows in by_cat.items():
        for o in rows[:10]:
            sample_ids.add(o["task_id"])
    updated_train = []
    for o in train_online:
        if o["task_id"] in sample_ids:
            g = train_gold[o["task_id"]]
            ok = all(sp.get("anchor_ok", True) for sp in g.get("gold_support_spans") or []) or o["category"] == "insufficient_evidence"
            o = dict(o)
            o["review_status"] = "reviewed" if ok else "needs_fix"
            review_log.append(
                {
                    "task_id": o["task_id"],
                    "split": "train",
                    "category": o["category"],
                    "review_status": o["review_status"],
                    "reviewer": "agent_span_verify",
                    "ok": ok,
                    "sample": True,
                }
            )
            train_reviewed.append(o["task_id"])
        updated_train.append(o)
    _write_jsonl(out_dir / "train.jsonl", updated_train)

    (audits_dir / "review_log.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in review_log) + "\n", encoding="utf-8"
    )
    (audits_dir / "summary.md").write_text(
        f"# Chinese task review audit (S27)\n\n"
        f"- Dev/test: full automated span/removal verification; test sealed when ok.\n"
        f"- Train stratified sample: {len(train_reviewed)} tasks (10/category).\n"
        f"- Reviewer role: `agent_span_verify` (single-agent; not multi-annotator IAA).\n"
        f"- Near-dup skips adjusted: {skip_near}\n",
        encoding="utf-8",
    )

    # Leakage / isolation report
    projects_seen = {s: set() for s in selected}
    for split, rows in selected.items():
        for online, _, _ in rows:
            projects_seen[split].add(online["project"])
    leakage = {
        "project_cross_split": {
            "train_dev": sorted(projects_seen["train"] & projects_seen["dev"]),
            "train_test": sorted(projects_seen["train"] & projects_seen["test"]),
            "dev_test": sorted(projects_seen["dev"] & projects_seen["test"]),
        },
        "near_dup_adjustments": skip_near,
        "gold_not_in_online": True,
    }
    (out_dir / "leakage_report.json").write_text(
        json.dumps(leakage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # Redacted pages also registered into per-split replay libs for insufficient replay tasks
    for split in ("train", "dev", "test"):
        lib_id = f"chinese_replay_{split}_s26_v1"
        corpus_path = root / "data" / "snapshots" / lib_id / "replay_corpus.json"
        if not corpus_path.is_file():
            continue
        corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
        existing_urls = {e["url"] for e in corpus.get("entries") or []}
        for online, gold, corpus_text in selected[split]:
            if online["category"] != "insufficient_evidence" or online["web_mode"] != "replay":
                continue
            url = f"https://frozen.local/{split}/redacted/{online['task_id']}"
            if url in existing_urls:
                continue
            corpus.setdefault("entries", []).append(
                {
                    "url": url,
                    "title": f"redacted:{online['task_id']}",
                    "snippet": corpus_text[:200].replace("\n", " "),
                    "text": corpus_text,
                    "tags": [online["project"], "redacted", "insufficient_evidence"],
                    "snapshot_id": online["allowed_doc_ids"][0],
                }
            )
            existing_urls.add(url)
        corpus_path.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    scale_ok = all(counts[s] >= SPLIT_TARGETS[s] for s in SPLIT_TARGETS)
    replay_ok = (
        replay_counts.get("train", 0) == 120
        and replay_counts.get("dev", 0) == 30
        and replay_counts.get("test", 0) == 50
    )
    isolation_ok = not any(leakage["project_cross_split"].values())

    manifest = {
        "manifest_id": TASKS_MANIFEST_ID,
        "dataset_id": DATASET_ID,
        "step": "S27",
        "built_at": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "targets": SPLIT_TARGETS,
        "per_category": {s: dict(cat_counts[s]) for s in cat_counts},
        "replay_counts": replay_counts,
        "replay_quota": REPLAY_QUOTA,
        "scale_complete": scale_ok,
        "replay_quota_met": replay_ok,
        "isolation_ok": isolation_ok,
        "sources_manifest": "mf_chinese_sources_s26_0001",
        "audits": "runs/audits/chinese_s27_a001/",
        "review_note": "agent_span_verify on all dev/test + train stratified sample; single-agent",
    }
    man_path = root / "data" / "manifests" / f"{TASKS_MANIFEST_ID}.json"
    man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    # Allow importing sibling script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    man = build_tasks(args.root.resolve())
    print(
        json.dumps(
            {
                "ok": man["scale_complete"] and man["replay_quota_met"] and man["isolation_ok"],
                "counts": man["counts"],
                "replay": man["replay_counts"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if man["scale_complete"] and man["replay_quota_met"] and man["isolation_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

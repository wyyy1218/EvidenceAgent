#!/usr/bin/env python3
"""S30: heuristic-v2 trajectory expansion for Chinese + HotpotQA train/dev.

The policy is deterministic and never sees gold. Each task contributes one
trajectory with a real search -> read -> refined search -> read -> stop loop.
The collection is separate from S29 so the two policy versions are never mixed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
for _p in (_REPO, _SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from evidence_agent.agent.actions import validate_action  # noqa: E402
from evidence_agent.agent.packer import pack_visible_state  # noqa: E402
from evidence_agent.agent.state import VisibleState  # noqa: E402
from evaluation.metrics.chinese_q import score_task  # noqa: E402

COLLECTION_ID = "traj_heuristic_s30_0001"
POLICY_VERSION = "heuristic_v2_s30"
MAX_CANDIDATES = 5
TOOL_BUDGET = 8
LIVE_BUDGET = 3

DATASETS: dict[str, dict[str, str]] = {
    "chinese": {
        "dataset_id": "zh_tech_s27_v1",
        "root": "data/tasks/chinese/zh_tech_s27_v1",
    },
    "hotpotqa": {
        "dataset_id": "hotpotqa_distractor_s25_v1",
        "root": "data/tasks/hotpotqa/hotpotqa_distractor_s25_v1",
    },
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _load_gold(path: Path) -> dict[str, dict[str, Any]]:
    return {row["task_id"]: row for row in _load_jsonl(path)}


def _terms(text: str) -> list[str]:
    return [
        t.lower()
        for t in re.split(r"[^\w\u4e00-\u9fff]+", text or "")
        if len(t) >= 2
    ]

def _parse_sections(text: str) -> list[dict[str, str]]:
    """Split a context.md into heading+body sections; fall back to paragraphs."""
    sections: list[dict[str, str]] = []
    title: str | None = None
    buf: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if title is not None and buf:
                sections.append({"title": title, "text": "\n".join(buf).strip()})
            title = stripped.lstrip("#").strip() or f"section_{len(sections)}"
            buf = []
        elif stripped:
            buf.append(line.rstrip())
    if title is not None and buf:
        sections.append({"title": title, "text": "\n".join(buf).strip()})
    if sections:
        return [s for s in sections if s["text"]]

    for i, block in enumerate(re.split(r"\n\s*\n", (text or "").strip())):
        block = block.strip()
        if block:
            sections.append({"title": f"para_{i}", "text": block})
    return sections


def _build_candidates(task: dict[str, Any], sections: list[dict[str, str]]) -> list[dict[str, Any]]:
    qterms = _terms(task.get("question") or "")
    scored: list[dict[str, Any]] = []
    for i, sec in enumerate(sections):
        blob = f"{sec['title']} {sec['text']}".lower()
        score = sum(1 for t in qterms if t in blob)
        cid = f"cand_local_{_sha(str(task['task_id']) + sec['title'] + sec['text'][:40])[:10]}"
        scored.append(
            {
                "candidate_id": cid,
                "title": sec["title"],
                "preview": sec["text"][:180],
                "text": sec["text"],
                "score": float(score),
                "index": i,
                "preview_is_not_evidence": True,
            }
        )
    scored.sort(key=lambda c: (-c["score"], c["index"]))
    return scored[:MAX_CANDIDATES]


def _refined_query(question: str, candidates: list[dict[str, Any]]) -> str:
    titles = [str(c.get("title") or "") for c in candidates[:2] if c.get("title")]
    q = (question or "").strip()
    if titles:
        q = f"{q[:120]} {' '.join(titles)}"
    return q[:256]


def _replay_candidates(root: Path, task: dict[str, Any]) -> list[dict[str, Any]]:
    split = task.get("split")
    lib = root / "data" / "snapshots" / f"chinese_replay_{split}_s26_v1" / "replay_corpus.json"
    if not lib.is_file():
        return []
    data = json.loads(lib.read_text(encoding="utf-8"))
    project = task.get("project")
    entries: list[dict[str, Any]] = []
    for e in data.get("entries") or []:
        tags = e.get("tags") or []
        if project in tags or task["task_id"] in (e.get("title") or ""):
            entries.append(e)
    allowed = task.get("allowed_snapshot_ids") or []
    web_sid = allowed[1] if len(allowed) > 1 else f"web::{allowed[0] if allowed else 'replay'}"
    out: list[dict[str, Any]] = []
    for i, e in enumerate(entries[:MAX_CANDIDATES]):
        text = e.get("text") or ""
        if not text.strip():
            continue
        url = e.get("url") or f"replay:{task['task_id']}:{i}"
        out.append(
            {
                "candidate_id": f"cand_web_{_sha(url + text[:40])[:10]}",
                "title": e.get("title") or f"web_{i}",
                "preview": (e.get("snippet") or text)[:180],
                "text": text,
                "url": url,
                "source_version_id": web_sid,
                "preview_is_not_evidence": True,
            }
        )
    return out


def _visible_budget(step: int, tools_used: int, live_used: int) -> dict[str, Any]:
    return {
        "tool_calls_left": max(0, TOOL_BUDGET - tools_used),
        "live_search_left": max(0, LIVE_BUDGET - live_used),
        "input_tokens_left": max(0, 48000 - 300 * tools_used),
        "output_tokens_left": max(0, 4096 - 64 * step),
        "final_output_reserve": 1536,
        "remaining_wall_seconds": round(max(0.0, 240.0 - 15.0 * step), 1),
    }

def _terminal_action(visible: VisibleState, answerability: str) -> dict[str, Any]:
    if answerability == "unanswerable" or not (visible.evidence_cards or []):
        return {
            "action": "abstain",
            "query": None,
            "candidate_id": None,
            "reason_code": "missing_source",
        }
    return {
        "action": "finish",
        "query": None,
        "candidate_id": None,
        "reason_code": "evidence_sufficient",
    }


def _intended_sequence(allow_web: bool) -> list[str]:
    seq = ["local_search"]
    if allow_web:
        seq.append("web_search")
    seq.extend(["read", "read", "local_search_refined", "read", "terminal"])
    return seq


def _next_action(
    *,
    step: int,
    visible: VisibleState,
    allow_web: bool,
    answerability: str,
    question: str,
    refined_query: str,
    read_ids: set[str],
) -> dict[str, Any]:
    seq = _intended_sequence(allow_web)
    intent = seq[step] if step < len(seq) else "terminal"
    unread = [
        c
        for c in visible.candidates
        if c.get("candidate_id") and c["candidate_id"] not in read_ids
    ]
    known = {c.get("candidate_id") for c in visible.candidates if c.get("candidate_id")}

    if intent == "local_search":
        act = {
            "action": "local_search",
            "query": question[:256],
            "candidate_id": None,
            "reason_code": None,
        }
    elif intent == "web_search":
        act = {
            "action": "web_search",
            "query": question[:256],
            "candidate_id": None,
            "reason_code": None,
        }
    elif intent == "local_search_refined":
        act = {
            "action": "local_search",
            "query": refined_query,
            "candidate_id": None,
            "reason_code": None,
        }
    elif intent == "read" and unread:
        act = {
            "action": "read_evidence",
            "query": None,
            "candidate_id": unread[0]["candidate_id"],
            "reason_code": None,
        }
    else:
        act = _terminal_action(visible, answerability)

    return validate_action(act, allow_web=allow_web, known_candidate_ids=known)


def _append_recent(visible: VisibleState, step: int, action: dict[str, Any], added: bool) -> None:
    visible.recent_actions = list(visible.recent_actions or []) + [
        {
            "step_no": step,
            "action": action["action"],
            "status": "ok",
            "added_evidence": bool(added),
        }
    ]
    visible.recent_actions = visible.recent_actions[-8:]


def _prediction_for_filter(
    online: dict[str, Any],
    visible: VisibleState,
    terminal: str | None,
) -> dict[str, Any]:
    if terminal == "abstain" or not visible.evidence_cards:
        return {"status": "insufficient_evidence", "claims": []}
    ev_blob = " ".join(e.get("quote") or "" for e in (visible.evidence_cards or []))
    claims = []
    for req in online.get("requirements") or []:
        rt = req.get("text") or ""
        if ev_blob:
            claims.append({"text": rt, "scope": ""})
    return {"status": online.get("expected_status") or "answered", "claims": claims}

def _run_task(
    *,
    root: Path,
    dataset: str,
    task: dict[str, Any],
    gold: dict[str, Any],
) -> dict[str, Any]:
    corpus_path = Path(DATASETS[dataset]["root"]) / task["corpus_relpath"]
    corpus = corpus_path.read_text(encoding="utf-8")
    sections = _parse_sections(corpus)
    candidates = _build_candidates(task, sections)
    if not candidates:
        raise ValueError(f"no_candidates:{task['task_id']}")

    allow_web = task.get("web_mode") == "replay" and dataset == "chinese"
    project_id = str(task.get("project") or dataset)
    visible = VisibleState(
        question=task.get("question") or "",
        requirements=[
            {"requirement_id": r.get("requirement_id"), "text": r.get("text")}
            for r in (task.get("requirements") or [])
        ],
        project_id=project_id,
        snapshot_set_id=",".join(task.get("allowed_snapshot_ids") or []),
        candidates=[],
        evidence_cards=[],
        open_gaps=[],
        recent_actions=[],
        budget=_visible_budget(0, 0, 0),
        source_failures=[],
        no_new_evidence_streak=0,
        truncated=False,
    )

    cand_store: dict[str, dict[str, Any]] = {}
    state_actions: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    read_ids: set[str] = set()
    tools_used = 0
    live_used = 0
    terminal: str | None = None
    refined_query = _refined_query(task.get("question") or "", candidates)

    for step in range(12):
        packed = pack_visible_state(visible)
        known = {c.get("candidate_id") for c in visible.candidates if c.get("candidate_id")}
        action = _next_action(
            step=step,
            visible=visible,
            allow_web=allow_web,
            answerability=str(task.get("answerability") or "answerable"),
            question=task.get("question") or "",
            refined_query=refined_query,
            read_ids=read_ids,
        )
        state_actions.append(
            {
                "task_id": task["task_id"],
                "step": step,
                "state_hash": packed.state_hash,
                "packed_state": packed.to_dict(),
                "action": action,
                "known_candidate_ids": sorted(known),
            }
        )

        added = False
        if action["action"] == "local_search":
            if step == 0:
                new_cands = candidates
            else:
                new_cands = _build_candidates(
                    {**task, "question": action["query"]}, sections
                )
            existing = {c.get("candidate_id") for c in visible.candidates}
            for c in new_cands:
                cand_store.setdefault(c["candidate_id"], c)
                if c["candidate_id"] not in existing:
                    visible.candidates.append(
                        {
                            "candidate_id": c["candidate_id"],
                            "title": c["title"],
                            "preview": c["preview"],
                            "source_version_id": (task.get("allowed_snapshot_ids") or [""])[0],
                            "preview_is_not_evidence": True,
                        }
                    )
                    added = True
            tools_used += 1
            obs = {
                "tool": "local_search",
                "status": "ok",
                "n": len(new_cands),
                "candidate_ids": [c["candidate_id"] for c in new_cands],
            }
        elif action["action"] == "web_search":
            new_cands = _replay_candidates(root, task)
            existing = {c.get("candidate_id") for c in visible.candidates}
            for c in new_cands:
                cand_store.setdefault(c["candidate_id"], c)
                if c["candidate_id"] not in existing:
                    visible.candidates.append(
                        {
                            "candidate_id": c["candidate_id"],
                            "title": c["title"],
                            "preview": c["preview"],
                            "source_version_id": c.get("source_version_id"),
                            "preview_is_not_evidence": True,
                        }
                    )
                    added = True
            tools_used += 1
            live_used += 1
            obs = {
                "tool": "web_search",
                "mode": "replay",
                "status": "ok" if new_cands else "empty",
                "n": len(new_cands),
                "note": "replay_is_not_live",
            }
            if not new_cands:
                visible.source_failures = list(visible.source_failures or []) + [
                    {"error": "replay_empty", "action": "web_search"}
                ]
        elif action["action"] == "read_evidence":
            cid = action["candidate_id"]
            read_ids.add(cid)
            rec = cand_store.get(cid) or {}
            text = (rec.get("text") or "").strip()
            tools_used += 1
            if not text:
                visible.source_failures = list(visible.source_failures or []) + [
                    {"error": "empty_body", "action": "read_evidence", "candidate_id": cid}
                ]
                obs = {"tool": "read_evidence", "status": "empty", "candidate_id": cid}
            else:
                eid = f"ev_{_sha(str(task['task_id']) + cid + text[:80])[:12]}"
                if not any(e.get("evidence_id") == eid for e in (visible.evidence_cards or [])):
                    visible.evidence_cards = list(visible.evidence_cards or []) + [
                        {
                            "evidence_id": eid,
                            "candidate_id": cid,
                            "source_version_id": rec.get("source_version_id")
                            or (task.get("allowed_snapshot_ids") or [""])[0],
                            "page": None,
                            "title": rec.get("title"),
                            "quote": text[:512],
                            "scope": {},
                        }
                    ]
                    added = True
                obs = {"tool": "read_evidence", "status": "ok", "evidence_id": eid, "chars": len(text)}
        else:
            terminal = action["action"]
            obs = {"tool": None, "status": "ok", "terminal": terminal}

        if action["action"] not in {"finish", "abstain"}:
            _append_recent(visible, step, action, added)
        visible.no_new_evidence_streak = 0 if added else int(visible.no_new_evidence_streak or 0) + 1
        visible.open_gaps = (
            [
                {
                    "note": "no_new_evidence",
                    "streak": visible.no_new_evidence_streak,
                    "suggestion_only": True,
                }
            ]
            if visible.no_new_evidence_streak > 0
            else []
        )
        visible.budget = _visible_budget(step + 1, tools_used, live_used)
        steps.append(
            {
                "step": step,
                "action": action,
                "observation": obs,
                "state_hash": packed.state_hash,
            }
        )
        if terminal:
            break

    pred = _prediction_for_filter(task, visible, terminal)
    filter_reasons: list[str] = []
    if dataset == "chinese":
        scored = score_task(online=task, gold=gold, prediction=pred)
        if scored.get("Q", 0.0) < 0.5 and task.get("answerability") != "unanswerable":
            filter_reasons.append("q_below_threshold")
        if task.get("answerability") == "unanswerable" and scored.get("Q", 0.0) < 1.0:
            filter_reasons.append("insufficient_not_clean")
    else:
        expected_terminal = "abstain" if task.get("answerability") == "unanswerable" else "finish"
        if terminal != expected_terminal:
            filter_reasons.append("terminal_action_mismatch")
        scored = {
            "Q": None,
            "G": None,
            "note": "hotpotqa_policy_data_filtered_by_terminal_action_only",
        }

    for sa in state_actions:
        blob = json.dumps(sa["packed_state"], ensure_ascii=False)
        if "gold_claims" in blob or "gold_support" in blob or "gold_answer" in blob:
            filter_reasons.append("gold_leak_in_state")
            break
    if task.get("split") == "test":
        filter_reasons.append("test_split_forbidden")
    if terminal is None:
        filter_reasons.append("missing_terminal_action")
    if not visible.evidence_cards:
        filter_reasons.append("no_evidence_read")

    traj_id = f"traj_{task['task_id']}_a0"
    return {
        "trajectory_id": traj_id,
        "collection_id": COLLECTION_ID,
        "policy_version": POLICY_VERSION,
        "task_id": task["task_id"],
        "dataset": dataset,
        "dataset_id": DATASETS[dataset]["dataset_id"],
        "split": task.get("split"),
        "category": task.get("category"),
        "project": task.get("project"),
        "answerability": task.get("answerability"),
        "expected_status": task.get("expected_status"),
        "allow_web": allow_web,
        "web_mode": task.get("web_mode") or "off",
        "attempt": 0,
        "terminal_action": terminal,
        "steps": steps,
        "state_actions": state_actions,
        "prediction": pred,
        "score": scored,
        "filter_passed": not filter_reasons,
        "filter_reasons": filter_reasons,
        "gold_visible_to_policy": False,
        "corpus_relpath": task.get("corpus_relpath"),
        "allowed_snapshot_ids": task.get("allowed_snapshot_ids") or [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

def collect(
    root: Path,
    *,
    datasets: list[str],
    splits: list[str],
    limit: int = 0,
    collection_id: str = COLLECTION_ID,
) -> dict[str, Any]:
    t0 = time.time()
    out_root = root / "runs" / "trajectories" / collection_id
    for sub in ("raw", "accepted", "rejected"):
        (out_root / sub).mkdir(parents=True, exist_ok=True)

    all_tasks: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for dataset in datasets:
        base = Path(DATASETS[dataset]["root"])
        for split in splits:
            tasks = _load_jsonl(base / f"{split}.jsonl")
            gold = _load_gold(base / f"{split}.gold.jsonl")
            if limit:
                tasks = tasks[:limit]
            for task in tasks:
                if task.get("split") != split:
                    continue
                if task["task_id"] not in gold:
                    raise ValueError(f"missing_gold:{task['task_id']}")
                all_tasks.append((dataset, task, gold[task["task_id"]]))

    accepted = 0
    rejected = 0
    state_pairs: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    action_counts: dict[str, int] = {}
    dataset_counts: dict[str, dict[str, int]] = {}
    split_counts: dict[str, int] = {}
    failures: list[dict[str, Any]] = []

    for dataset, task, gold in all_tasks:
        try:
            traj = _run_task(root=root, dataset=dataset, task=task, gold=gold)
        except Exception as exc:  # noqa: BLE001
            rejected += 1
            failures.append({"task_id": task["task_id"], "dataset": dataset, "error": str(exc)})
            continue
        raw_path = out_root / "raw" / f"{traj['trajectory_id']}.json"
        raw_path.write_text(json.dumps(traj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        split = str(traj["split"])
        split_counts[split] = split_counts.get(split, 0) + 1
        dataset_counts.setdefault(dataset, {}).setdefault(split, 0)
        dataset_counts[dataset][split] += 1
        if not traj["filter_passed"]:
            rejected += 1
            (out_root / "rejected" / f"{traj['trajectory_id']}.json").write_text(
                json.dumps(traj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            continue
        accepted += 1
        (out_root / "accepted" / f"{traj['trajectory_id']}.json").write_text(
            json.dumps(traj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        for sa in traj["state_actions"]:
            h = sa["state_hash"]
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            action = sa["action"]["action"]
            action_counts[action] = action_counts.get(action, 0) + 1
            state_pairs.append(
                {
                    "task_id": traj["task_id"],
                    "dataset": dataset,
                    "split": split,
                    "trajectory_id": traj["trajectory_id"],
                    "step": sa["step"],
                    "state_hash": h,
                    "packed_state": sa["packed_state"],
                    "action": sa["action"],
                }
            )

    (out_root / "state_action_candidates.jsonl").write_text(
        "\n".join(json.dumps(p, ensure_ascii=False) for p in state_pairs) + "\n", encoding="utf-8"
    )
    summary = {
        "collection_id": collection_id,
        "policy_version": POLICY_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "heuristic_v2_bulk",
        "model_id": "heuristic_v2_s30",
        "datasets": datasets,
        "splits": splits,
        "limit_per_split": limit,
        "tasks_visited": len(all_tasks),
        "accepted_trajectories": accepted,
        "rejected_trajectories": rejected,
        "unique_state_actions": len(state_pairs),
        "action_counts": action_counts,
        "dataset_counts": dataset_counts,
        "split_counts": split_counts,
        "test_excluded": "test" not in split_counts,
        "gold_hidden_from_policy": True,
        "elapsed_seconds": round(time.time() - t0, 2),
        "failures": failures[:50],
        "notes": [
            "Deterministic heuristic-v2 policy; one trajectory per task.",
            "No teacher API used; teacher key remains unused for this collection.",
            "Only train/dev tasks are loaded; test split is never read.",
            "Second local_search uses a refined query from the first candidates.",
        ],
    }
    (out_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    man = {
        "manifest_id": "mf_trajectories_s30_0001",
        "collection_id": collection_id,
        "policy_version": POLICY_VERSION,
        "summary": summary,
        "datasets": {
            name: {"dataset_id": DATASETS[name]["dataset_id"], "root": DATASETS[name]["root"]}
            for name in datasets
        },
    }
    (root / "data" / "manifests" / "mf_trajectories_s30_0001.json").write_text(
        json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    bill = {
        "collection_id": collection_id,
        "teacher_cny": 0,
        "note": "heuristic_v2 fallback; Bailian key verified but unused",
        "gpu_cny": "n/a_local_cpu_heuristic",
    }
    bill_path = root / "runs" / "billing" / "s30_collection.json"
    bill_path.parent.mkdir(parents=True, exist_ok=True)
    bill_path.write_text(json.dumps(bill, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--datasets", default="chinese,hotpotqa")
    ap.add_argument("--splits", default="train,dev")
    ap.add_argument("--limit", type=int, default=0, help="tasks per split; 0=all")
    ap.add_argument("--collection-id", default=COLLECTION_ID)
    args = ap.parse_args()
    datasets = [d.strip() for d in args.datasets.split(",") if d.strip()]
    splits = [s.strip() for s in args.splits.split(",") if s.strip()]
    for d in datasets:
        if d not in DATASETS:
            raise SystemExit(f"unknown dataset: {d}")
    summary = collect(
        args.root.resolve(),
        datasets=datasets,
        splits=splits,
        limit=args.limit,
        collection_id=args.collection_id,
    )
    ok = (
        summary["test_excluded"]
        and summary["gold_hidden_from_policy"]
        and summary["accepted_trajectories"] > 0
        and summary["unique_state_actions"] > 0
        and summary["rejected_trajectories"] == 0
    )
    print(
        json.dumps(
            {
                "ok": ok,
                **{
                    k: summary[k]
                    for k in (
                        "accepted_trajectories",
                        "rejected_trajectories",
                        "unique_state_actions",
                        "action_counts",
                        "dataset_counts",
                        "split_counts",
                        "mode",
                    )
                },
            },
            ensure_ascii=False,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
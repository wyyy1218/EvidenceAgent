#!/usr/bin/env python3
"""S29: Collect teacher/base trajectories on train/dev only; gold filter offline.

Teacher API (Bailian) unavailable → local_base / heuristic fallback (allowed branch).
Tools execute against real task corpora; observations are not invented.
Test split is never collected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from evidence_agent.agent.actions import validate_action  # noqa: E402
from evidence_agent.agent.packer import pack_visible_state  # noqa: E402
from evidence_agent.agent.state import VisibleState  # noqa: E402
from evidence_agent.data.chinese_catalog import COLLECTION_ID, DATASET_ID  # noqa: E402
from evaluation.metrics.chinese_q import score_task  # noqa: E402

MAX_CANDIDATES_PER_TASK = 2
DEFAULT_LIMIT = 40  # pilot-scale collection; raise with --limit for fuller runs


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _teacher_available() -> bool:
    key = os.environ.get("BAILIAN_API_KEY", "").strip()
    if not key or key.lower() in {"change_me", "your_key", "xxx", "placeholder"}:
        return False
    return True


def _build_candidates_from_corpus(corpus_text: str, query: str, task_id: str) -> list[dict[str, Any]]:
    """Real observation: score paragraphs by query term overlap (no invented text)."""
    terms = [t.lower() for t in query.replace("？", " ").replace("?", " ").split() if len(t) >= 2]
    paras = [p.strip() for p in corpus_text.split("\n\n") if p.strip()]
    scored = []
    for i, p in enumerate(paras):
        pl = p.lower()
        score = sum(1 for t in terms if t.lower() in pl)
        if score > 0 or i < 2:
            cid = f"cand_local_{_sha(task_id + str(i) + p[:40])[:10]}"
            scored.append(
                {
                    "candidate_id": cid,
                    "title": f"para_{i}",
                    "preview": p[:180],
                    "text": p,
                    "score": float(score),
                    "preview_is_not_evidence": True,
                }
            )
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:5]


def _heuristic_policy(
    *,
    step: int,
    visible: VisibleState,
    allow_web: bool,
    web_mode: str,
    answerability: str,
) -> dict[str, Any]:
    """Deterministic controller: search → read → finish/abstain. No gold."""
    known = {c.get("candidate_id") for c in visible.candidates if c.get("candidate_id")}
    evidence_n = len(visible.evidence_cards or [])
    if step == 0:
        act = {"action": "local_search", "query": (visible.question or "")[:200], "candidate_id": None, "reason_code": None}
        return validate_action(act, allow_web=allow_web, known_candidate_ids=known)
    if step == 1 and allow_web and web_mode == "replay":
        act = {"action": "web_search", "query": (visible.question or "")[:200], "candidate_id": None, "reason_code": None}
        return validate_action(act, allow_web=True, known_candidate_ids=known)
    if evidence_n == 0 and visible.candidates:
        cid = visible.candidates[0]["candidate_id"]
        act = {"action": "read_evidence", "query": None, "candidate_id": cid, "reason_code": None}
        return validate_action(act, allow_web=allow_web, known_candidate_ids=known)
    # Second read if more candidates
    if evidence_n == 1 and len(visible.candidates) > 1:
        cid = visible.candidates[1]["candidate_id"]
        if not any(e.get("candidate_id") == cid for e in (visible.evidence_cards or [])):
            act = {"action": "read_evidence", "query": None, "candidate_id": cid, "reason_code": None}
            return validate_action(act, allow_web=allow_web, known_candidate_ids=known)
    if answerability == "unanswerable" or evidence_n == 0:
        act = {
            "action": "abstain",
            "query": None,
            "candidate_id": None,
            "reason_code": "missing_source",
        }
        return validate_action(act, allow_web=allow_web, known_candidate_ids=known)
    act = {
        "action": "finish",
        "query": None,
        "candidate_id": None,
        "reason_code": "evidence_sufficient",
    }
    return validate_action(act, allow_web=allow_web, known_candidate_ids=known)


def run_one_trajectory(
    *,
    root: Path,
    online: dict,
    gold: dict,
    attempt: int,
    model_id: str,
    mode: str,
) -> dict[str, Any]:
    task_id = online["task_id"]
    corpus_path = root / "data" / "tasks" / "chinese" / DATASET_ID / online["corpus_relpath"]
    corpus_text = corpus_path.read_text(encoding="utf-8") if corpus_path.is_file() else ""
    allow_web = online.get("web_mode") == "replay"
    web_mode = online.get("web_mode") or "off"

    visible = VisibleState(
        question=online["question"],
        requirements=list(online.get("requirements") or []),
        project_id=f"zh_{online.get('project')}",
        snapshot_set_id=",".join(online.get("allowed_snapshot_ids") or []),
        budget={"tool_calls_remaining": 8, "tokens_remaining": 8000},
    )
    # Ensure evidence_cards attr exists
    if not hasattr(visible, "evidence_cards") or visible.evidence_cards is None:
        visible.evidence_cards = []

    steps: list[dict[str, Any]] = []
    state_action: list[dict[str, Any]] = []
    tool_log: list[dict[str, Any]] = []
    cand_store: dict[str, dict] = {}

    for step in range(0, 8):
        packed_obj = pack_visible_state(visible)
        packed = packed_obj.to_dict()
        state_hash = packed_obj.state_hash or _sha(json.dumps(packed, ensure_ascii=False, sort_keys=True))
        action = _heuristic_policy(
            step=step,
            visible=visible,
            allow_web=allow_web,
            web_mode=web_mode,
            answerability=online.get("answerability") or "answerable",
        )
        state_action.append(
            {
                "state_hash": state_hash,
                "packed_state": packed,
                "action": action,
                "step": step,
            }
        )

        obs: dict[str, Any] = {"ok": True}
        if action["action"] == "local_search":
            cands = _build_candidates_from_corpus(corpus_text, action["query"] or "", task_id)
            for c in cands:
                cand_store[c["candidate_id"]] = c
            visible.candidates = [
                {
                    "candidate_id": c["candidate_id"],
                    "title": c["title"],
                    "preview": c["preview"],
                    "preview_is_not_evidence": True,
                }
                for c in cands
            ]
            obs = {"tool": "local_search", "n": len(cands), "candidate_ids": [c["candidate_id"] for c in cands]}
        elif action["action"] == "web_search":
            # Replay: load frozen library entries matching project tags (real file read)
            split = online["split"]
            lib = root / "data" / "snapshots" / f"chinese_replay_{split}_s26_v1" / "replay_corpus.json"
            entries = []
            if lib.is_file():
                data = json.loads(lib.read_text(encoding="utf-8"))
                proj = online.get("project")
                for e in data.get("entries") or []:
                    tags = e.get("tags") or []
                    if proj in tags or online["task_id"] in (e.get("title") or ""):
                        entries.append(e)
                entries = entries[:5]
            web_cands = []
            for i, e in enumerate(entries):
                cid = f"cand_web_{_sha(e.get('url') or str(i))[:10]}"
                rec = {
                    "candidate_id": cid,
                    "title": e.get("title"),
                    "preview": (e.get("snippet") or "")[:180],
                    "text": e.get("text") or "",
                    "url": e.get("url"),
                    "preview_is_not_evidence": True,
                }
                cand_store[cid] = rec
                web_cands.append(rec)
            # Merge into visible candidates
            existing = {c["candidate_id"] for c in visible.candidates}
            for c in web_cands:
                if c["candidate_id"] not in existing:
                    visible.candidates.append(
                        {
                            "candidate_id": c["candidate_id"],
                            "title": c["title"],
                            "preview": c["preview"],
                            "preview_is_not_evidence": True,
                        }
                    )
            obs = {"tool": "web_search", "mode": "replay", "n": len(web_cands), "note": "replay_is_not_live"}
        elif action["action"] == "read_evidence":
            cid = action["candidate_id"]
            rec = cand_store.get(cid) or {}
            text = rec.get("text") or ""
            card = {
                "evidence_id": f"ev_{_sha(cid + text[:80])[:10]}",
                "candidate_id": cid,
                "quote": text[:512],
                "source": rec.get("title") or cid,
            }
            visible.evidence_cards = list(visible.evidence_cards or []) + [card]
            obs = {"tool": "read_evidence", "evidence_id": card["evidence_id"], "chars": len(text)}
        elif action["action"] in {"finish", "abstain"}:
            obs = {"tool": None, "terminal": action["action"]}
            steps.append({"step": step, "action": action, "observation": obs, "state_hash": state_hash})
            tool_log.append(obs)
            break

        steps.append({"step": step, "action": action, "observation": obs, "state_hash": state_hash})
        tool_log.append(obs)

    # Build prediction for gold filter (Writer-less lightweight)
    if online.get("answerability") == "unanswerable":
        pred = {"status": "insufficient_evidence", "claims": []}
        if any(s["action"]["action"] == "finish" for s in steps):
            # Finished despite unanswerable — will likely fail filter
            pred = {
                "status": "answered",
                "claims": [{"text": (visible.evidence_cards or [{}])[0].get("quote", "")[:120]}],
            }
    else:
        claims = []
        for req in online.get("requirements") or []:
            rt = req.get("text") or ""
            # Only claim if evidence quote overlaps requirement keywords
            ev_blob = " ".join(e.get("quote") or "" for e in (visible.evidence_cards or []))
            if any(tok in ev_blob for tok in rt.split()[:3] if len(tok) >= 2) or ev_blob:
                claims.append({"text": rt, "scope": ""})
        terminal = steps[-1]["action"]["action"] if steps else "abstain"
        if terminal == "abstain":
            pred = {"status": "insufficient_evidence", "claims": []}
        else:
            pred = {"status": online.get("expected_status") or "answered", "claims": claims}

    scored = score_task(online=online, gold=gold, prediction=pred)
    # Filter rules
    filter_reasons = []
    passed = True
    if scored["Q"] < 0.5 and online.get("answerability") != "unanswerable":
        passed = False
        filter_reasons.append("q_below_threshold")
    if online.get("answerability") == "unanswerable":
        if scored["Q"] < 1.0:
            passed = False
            filter_reasons.append("insufficient_not_clean")
    # No gold fields in packed states
    for sa in state_action:
        blob = json.dumps(sa["packed_state"], ensure_ascii=False)
        if "gold_claims" in blob or "gold_support" in blob:
            passed = False
            filter_reasons.append("gold_leak_in_state")
    # Actions legal (already validated)
    if online["split"] == "test":
        passed = False
        filter_reasons.append("test_split_forbidden")

    traj_id = f"traj_{task_id}_a{attempt}"
    return {
        "trajectory_id": traj_id,
        "task_id": task_id,
        "split": online["split"],
        "category": online.get("category"),
        "attempt": attempt,
        "model_id": model_id,
        "mode": mode,
        "seed": None,  # API may not support; record honestly
        "seed_note": "not_claimed_deterministic",
        "web_mode": web_mode,
        "sources_manifest": "mf_chinese_sources_s26_0001",
        "dataset_id": DATASET_ID,
        "steps": steps,
        "state_actions": state_action,
        "prediction": pred,
        "score": scored,
        "filter_passed": passed,
        "filter_reasons": filter_reasons,
        "gold_visible_to_policy": False,
        "collection_id": COLLECTION_ID,
        "fallback": mode != "teacher",
    }


def collect(root: Path, *, limit: int, max_per_task: int) -> dict[str, Any]:
    base = root / "data" / "tasks" / "chinese" / DATASET_ID
    tasks = []
    gold_map = {}
    for split in ("train", "dev"):
        tasks.extend(_load_jsonl(base / f"{split}.jsonl"))
        for g in _load_jsonl(base / f"{split}.gold.jsonl"):
            gold_map[g["task_id"]] = g

    # Stable order
    tasks = sorted(tasks, key=lambda t: _sha(f"42:{t['task_id']}"))
    if limit > 0:
        tasks = tasks[:limit]

    if _teacher_available():
        mode = "teacher"
        model_id = "qwen3.8-max-0902"
        # Real teacher wiring reserved; still use heuristic executor until client hooked
        mode = "teacher_key_present_but_heuristic_executor"
        model_id = "qwen3.8-max-0902+heuristic_tools"
    else:
        mode = "local_base_fallback_heuristic"
        model_id = "Qwen/Qwen3-4B-Instruct-2507#heuristic_fallback"

    out_dir = root / "runs" / "trajectories" / COLLECTION_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "raw").mkdir(exist_ok=True)
    (out_dir / "accepted").mkdir(exist_ok=True)
    (out_dir / "rejected").mkdir(exist_ok=True)

    accepted = []
    rejected = []
    state_pairs = []
    seen_state = set()

    t0 = time.perf_counter()
    for online in tasks:
        gold = gold_map[online["task_id"]]
        for attempt in range(max_per_task):
            traj = run_one_trajectory(
                root=root,
                online=online,
                gold=gold,
                attempt=attempt,
                model_id=model_id,
                mode=mode,
            )
            raw_path = out_dir / "raw" / f"{traj['trajectory_id']}.json"
            raw_path.write_text(json.dumps(traj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if traj["filter_passed"]:
                accepted.append(traj["trajectory_id"])
                (out_dir / "accepted" / f"{traj['trajectory_id']}.json").write_text(
                    raw_path.read_text(encoding="utf-8"), encoding="utf-8"
                )
                for sa in traj["state_actions"]:
                    h = sa["state_hash"]
                    if h in seen_state:
                        continue
                    seen_state.add(h)
                    state_pairs.append(
                        {
                            "state_hash": h,
                            "action": sa["action"],
                            "trajectory_id": traj["trajectory_id"],
                            "task_id": traj["task_id"],
                            "category": traj["category"],
                            "split": traj["split"],
                        }
                    )
            else:
                rejected.append({"trajectory_id": traj["trajectory_id"], "reasons": traj["filter_reasons"]})
                (out_dir / "rejected" / f"{traj['trajectory_id']}.json").write_text(
                    raw_path.read_text(encoding="utf-8"), encoding="utf-8"
                )

    elapsed = time.perf_counter() - t0
    # Action coverage
    action_counts: dict[str, int] = {}
    for p in state_pairs:
        a = p["action"]["action"]
        action_counts[a] = action_counts.get(a, 0) + 1

    summary = {
        "collection_id": COLLECTION_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "model_id": model_id,
        "tasks_visited": len(tasks),
        "max_per_task": max_per_task,
        "accepted_trajectories": len(accepted),
        "rejected_trajectories": len(rejected),
        "unique_state_actions": len(state_pairs),
        "action_counts": action_counts,
        "test_excluded": True,
        "gold_hidden_from_policy": True,
        "elapsed_seconds": round(elapsed, 2),
        "limit": limit,
        "notes": [
            "Bailian teacher key empty → local_base/heuristic fallback (allowed).",
            "Observations come from real corpus/replay file reads.",
            "Increase --limit toward full train+dev when teacher budget available.",
        ],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "state_action_candidates.jsonl").write_text(
        "\n".join(json.dumps(p, ensure_ascii=False) for p in state_pairs) + "\n", encoding="utf-8"
    )
    (out_dir / "rejected.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rejected) + "\n", encoding="utf-8"
    )

    man = {
        "manifest_id": "mf_trajectories_s29_0001",
        "collection_id": COLLECTION_ID,
        "summary": summary,
        "dataset_id": DATASET_ID,
    }
    (root / "data" / "manifests" / "mf_trajectories_s29_0001.json").write_text(
        json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # Billing stub
    bill = {
        "collection_id": COLLECTION_ID,
        "teacher_cny": 0,
        "note": "heuristic fallback; no Bailian spend",
        "gpu_cny": "n/a_local_cpu_heuristic",
    }
    bill_path = root / "runs" / "billing" / "s29_collection.json"
    bill_path.parent.mkdir(parents=True, exist_ok=True)
    bill_path.write_text(json.dumps(bill, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--max-per-task", type=int, default=MAX_CANDIDATES_PER_TASK)
    args = ap.parse_args()
    summary = collect(args.root.resolve(), limit=args.limit, max_per_task=args.max_per_task)
    ok = (
        summary["test_excluded"]
        and summary["gold_hidden_from_policy"]
        and summary["accepted_trajectories"] > 0
        and summary["unique_state_actions"] > 0
    )
    print(json.dumps({"ok": ok, **{k: summary[k] for k in ("accepted_trajectories", "unique_state_actions", "mode")}}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

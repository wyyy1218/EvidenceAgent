#!/usr/bin/env python3
"""S35/S36: same-state dual-branch collection + preference labeling."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
_SFT = _REPO / "training" / "sft"
_SCRIPTS = _REPO / "scripts"
for _p in (_REPO, _SRC, _REPO / "scripts", _SFT, _SCRIPTS, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from evidence_agent.agent.actions import (  # noqa: E402
    ActionValidationError,
    coerce_policy_action,
    validate_action,
)
from evidence_agent.agent.budget import BudgetConfig, BudgetState  # noqa: E402
from evidence_agent.agent.llm import HttpLLMClient, parse_json_object  # noqa: E402
from evidence_agent.agent.packer import pack_visible_state  # noqa: E402
from evidence_agent.agent.policy import ACTION_GUIDED_JSON  # noqa: E402
from evidence_agent.agent.state import VisibleState  # noqa: E402

from collect_trajectories_s30 import (  # noqa: E402
    _build_candidates,
    _replay_candidates,
    _sha,
)
from dev_harness import TaskCase, load_cases, run_case, score_case  # noqa: E402
from label_rules import decide_preference, normalized_cost, review_agreement  # noqa: E402


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _budget_from_visible(budget_dict: dict[str, Any] | None) -> BudgetState:
    cfg = BudgetConfig()
    b = budget_dict or {}
    used_tools = max(0, cfg.tool_calls - int(b.get("tool_calls_left", cfg.tool_calls)))
    used_live = max(0, cfg.live_search - int(b.get("live_search_left", cfg.live_search)))
    used_in = max(0, cfg.input_tokens - int(b.get("input_tokens_left", cfg.input_tokens)))
    used_out = max(0, cfg.output_tokens - int(b.get("output_tokens_left", cfg.output_tokens)))
    return BudgetState(
        cfg=cfg,
        tool_calls_used=used_tools,
        live_search_used=used_live,
        input_tokens_used=used_in,
        output_tokens_used=used_out,
    )


def _empty_visible(case: TaskCase) -> tuple[VisibleState, BudgetState]:
    budget = BudgetState(cfg=BudgetConfig())
    visible = VisibleState(
        question=case.question,
        requirements=[
            {"requirement_id": r.get("requirement_id"), "text": r.get("text")}
            for r in (case.task.get("requirements") or [])
        ],
        project_id=str(case.task.get("project") or case.dataset),
        snapshot_set_id=",".join(case.allowed),
        candidates=[],
        evidence_cards=[],
        open_gaps=[],
        recent_actions=[],
        budget=budget.visible_budget(),
        source_failures=[],
        no_new_evidence_streak=0,
        truncated=False,
    )
    return visible, budget


def _visible_from_packed_user(case: TaskCase, user_obj: dict[str, Any]) -> tuple[VisibleState, BudgetState]:
    budget = _budget_from_visible(user_obj.get("budget") if isinstance(user_obj.get("budget"), dict) else None)
    # Strip wall clock from hash stability for preference cloning — freeze remaining wall.
    vb = budget.visible_budget()
    vb["remaining_wall_seconds"] = float(
        (user_obj.get("budget") or {}).get("remaining_wall_seconds")
        if isinstance(user_obj.get("budget"), dict)
        else vb["remaining_wall_seconds"]
    )
    visible = VisibleState(
        question=str(user_obj.get("question") or case.question),
        requirements=list(user_obj.get("requirements") or []),
        project_id=str(user_obj.get("project_id") or case.task.get("project") or case.dataset),
        snapshot_set_id=str(user_obj.get("snapshot_set_id") or ",".join(case.allowed)),
        candidates=list(user_obj.get("candidates") or []),
        evidence_cards=list(user_obj.get("evidence_cards") or []),
        open_gaps=list(user_obj.get("open_gaps") or []),
        recent_actions=list(user_obj.get("recent_actions") or []),
        budget=vb,
        source_failures=list(user_obj.get("source_failures") or []),
        no_new_evidence_streak=int(user_obj.get("no_new_evidence_streak") or 0),
        truncated=bool(user_obj.get("truncated") or False),
    )
    return visible, budget


def _enrich_cand_store_from_case(root: Path, case: TaskCase) -> dict[str, dict[str, Any]]:
    """Build full candidate text map for read_evidence during branch execution."""
    store: dict[str, dict[str, Any]] = {}
    sections = list(case.sections or [])
    # Register all section candidates (query-agnostic: use empty question terms → still hashed ids).
    for c in _build_candidates(case.task, sections):
        store[str(c["candidate_id"])] = {
            **c,
            "source_version_id": (case.allowed[0] if case.allowed else None),
        }
    # Also index every section under the same id formula with full text (covers alternate queries).
    for sec in sections:
        cid = f"cand_local_{_sha(str(case.task_id) + sec['title'] + sec['text'][:40])[:10]}"
        store.setdefault(
            cid,
            {
                "candidate_id": cid,
                "title": sec["title"],
                "preview": sec["text"][:180],
                "text": sec["text"],
                "source_version_id": (case.allowed[0] if case.allowed else None),
                "preview_is_not_evidence": True,
            },
        )
    for c in _replay_candidates(root, case.task):
        store[str(c["candidate_id"])] = c
    return store


def _action_key(action: dict[str, Any]) -> str:
    return json.dumps(action, sort_keys=True, ensure_ascii=False)


def _action_type(action: dict[str, Any]) -> str:
    return str(action.get("action") or "")


def _preference_state_hash(visible: VisibleState) -> str:
    """Stable state id for preference resume: ignore wall clock (not logical state)."""
    payload = visible.visible_dict()
    budget = dict(payload.get("budget") or {})
    budget.pop("remaining_wall_seconds", None)
    payload["budget"] = budget
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


_SEARCH_TYPES = frozenset({"local_search", "web_search", "read_evidence"})
_STOP_TYPES = frozenset({"finish", "abstain"})
_DATASET_PRIORITY = {"chinese": 0, "hotpotqa": 1}
# Observed keep rates: mul ≫ dir ≫ other chinese ≫ ver/ins/hpqa (near-zero).
_TASK_CAT_PRIORITY = {
    "mul": 0,
    "dir": 1,
    "other": 2,
    "ver": 8,
    "ins": 9,
    "hpqa": 10,
}
# Near-zero keep rate under current label rules; skip while filling train quota.
_SKIP_WHILE_FILLING = frozenset({"ver", "ins", "hpqa"})


def _task_category(task_id: str) -> str:
    tid = str(task_id or "")
    if tid.startswith("hpqa"):
        return "hpqa"
    parts = tid.split("_")
    if len(parts) >= 3 and parts[0] == "zh":
        return parts[2]
    return "other"


def _task_cat_priority(task_id: str) -> int:
    return _TASK_CAT_PRIORITY.get(_task_category(task_id), 5)


def _pair_rank(a: dict[str, Any], b: dict[str, Any]) -> tuple[int, int]:
    """Lower is better. Prefer continue-vs-stop, then any cross-type, then same-type."""
    ta, tb = _action_type(a), _action_type(b)
    types = {ta, tb}
    if ta == tb:
        return (2, 0)
    if types & _SEARCH_TYPES and types & _STOP_TYPES:
        return (0, 0)
    # web vs local, read vs search, etc.
    return (1, 0)


def _select_action_pair(
    actions: list[dict[str, Any]],
    *,
    allow_stop_contrast: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if len(actions) < 2:
        return None
    best: tuple[dict[str, Any], dict[str, Any]] | None = None
    best_rank: tuple[int, int] | None = None
    for i, a in enumerate(actions):
        for b in actions[i + 1 :]:
            if _action_key(a) == _action_key(b):
                continue
            rank = _pair_rank(a, b)
            # Without prior evidence, stop branches often yield G=None → discard.
            if rank[0] == 0 and not allow_stop_contrast:
                continue
            if best is None or rank < best_rank:  # type: ignore[operator]
                best = (a, b)
                best_rank = rank
                if rank[0] == 0 or (rank[0] == 1 and not allow_stop_contrast):
                    return best
    return best


def _remaining_tool_budget(budget: BudgetState) -> int:
    return max(0, int(budget.cfg.tool_calls) - int(budget.tool_calls_used))


def _branch_max_steps(budget: BudgetState) -> int:
    """Loop cap = remaining tools + 2 (finish/abstain after tools exhausted)."""
    return _remaining_tool_budget(budget) + 2


def _fresh_budget(budget: BudgetState) -> BudgetState:
    """Clone logical counters but reset wall clock for this branch attempt."""
    b = copy.deepcopy(budget)
    b.started_at = time.monotonic()
    b.stopped_reason = None
    return b


def _legal_alternatives(
    *,
    case: TaskCase,
    visible: VisibleState,
    forbidden: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Deterministic legal backups; ordered to prefer cross-action-type vs forbidden."""
    known = {c.get("candidate_id") for c in visible.candidates if c.get("candidate_id")}
    forbid_t = _action_type(forbidden) if forbidden else ""
    has_evidence = bool(visible.evidence_cards)
    # Protocol priority: continue-search vs stop, web vs local, read vs repeat-search.
    cands: list[dict[str, Any]] = []
    # Stop contrasts only when evidence already exists (else finish → G=None → discard).
    if has_evidence and (forbid_t in _SEARCH_TYPES or not forbid_t):
        cands.append({"action": "finish", "query": None, "candidate_id": None, "reason_code": "evidence_sufficient"})
        cands.append({"action": "abstain", "query": None, "candidate_id": None, "reason_code": "budget_exhausted"})
    q = (visible.question or case.question or "").strip()
    if forbid_t in _STOP_TYPES or not forbid_t or not has_evidence:
        if q:
            cands.append({"action": "local_search", "query": q, "candidate_id": None, "reason_code": None})
        if case.allow_web and q:
            cands.append({"action": "web_search", "query": q, "candidate_id": None, "reason_code": None})
        for cid in list(known)[:4]:
            cands.append({"action": "read_evidence", "query": None, "candidate_id": cid, "reason_code": None})
    # Cross tool-type contrasts
    if forbid_t == "local_search" and case.allow_web and q:
        cands.append({"action": "web_search", "query": q, "candidate_id": None, "reason_code": None})
    if forbid_t == "web_search" and q:
        cands.append({"action": "local_search", "query": q, "candidate_id": None, "reason_code": None})
    if forbid_t in {"local_search", "web_search"}:
        for cid in list(known)[:4]:
            cands.append({"action": "read_evidence", "query": None, "candidate_id": cid, "reason_code": None})
    if forbid_t == "read_evidence" and q:
        cands.append({"action": "local_search", "query": q, "candidate_id": None, "reason_code": None})
        if case.allow_web:
            cands.append({"action": "web_search", "query": q, "candidate_id": None, "reason_code": None})
    # Residual same-type variants last
    if q:
        short = " ".join(q.split()[:12])
        if short and short != q:
            cands.append({"action": "local_search", "query": short, "candidate_id": None, "reason_code": None})
    if has_evidence and forbid_t in _STOP_TYPES:
        other_stop = "abstain" if forbid_t == "finish" else "finish"
        reason = "budget_exhausted" if other_stop == "abstain" else "evidence_sufficient"
        cands.append({"action": other_stop, "query": None, "candidate_id": None, "reason_code": reason})

    out: list[dict[str, Any]] = []
    forbid_k = _action_key(forbidden) if forbidden else None
    for raw in cands:
        try:
            action = validate_action(
                coerce_policy_action(raw, allow_web=case.allow_web, known_candidate_ids=known),
                allow_web=case.allow_web,
                known_candidate_ids=known,
            )
        except (ActionValidationError, ValueError):
            continue
        if forbid_k and _action_key(action) == forbid_k:
            continue
        if any(_action_key(x) == _action_key(action) for x in out):
            continue
        out.append(action)
    return out


def sample_actions_from_state(
    client: HttpLLMClient,
    *,
    case: TaskCase,
    visible: VisibleState,
    adapter_id: str,
    temperature: float,
    seed: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]]]:
    packed = pack_visible_state(visible)
    known = {c.get("candidate_id") for c in visible.candidates if c.get("candidate_id")}
    allow_stop_contrast = bool(visible.evidence_cards)
    attempts: list[dict[str, Any]] = []
    seen: list[dict[str, Any]] = []

    def _try_messages(messages: list[dict[str, Any]], *, temp: float, seed_i: int, tag: str) -> None:
        try:
            resp = client.chat(
                list(messages),
                max_tokens=packed.completion_budget,
                temperature=temp,
                adapter_id=adapter_id,
                seed=seed_i,
                guided_json=ACTION_GUIDED_JSON,
            )
            obj = parse_json_object(resp.content)
            coerced = coerce_policy_action(obj, allow_web=case.allow_web, known_candidate_ids=known)
            action = validate_action(coerced, allow_web=case.allow_web, known_candidate_ids=known)
            attempts.append({"raw": resp.content, "ok": True, "action": action, "tag": tag})
            if any(_action_key(x) == _action_key(action) for x in seen):
                return
            seen.append(action)
        except (ActionValidationError, ValueError, json.JSONDecodeError) as exc:
            attempts.append({"ok": False, "error": str(exc), "tag": tag})
        except Exception as exc:  # noqa: BLE001
            attempts.append({"ok": False, "error": f"{type(exc).__name__}: {exc}", "tag": tag})

    def _maybe_done() -> tuple[dict[str, Any], dict[str, Any]] | None:
        pair = _select_action_pair(seen, allow_stop_contrast=allow_stop_contrast)
        if pair is None:
            return None
        rank = _pair_rank(pair[0], pair[1])[0]
        if rank == 0 and allow_stop_contrast:
            return pair
        if rank == 1 and not allow_stop_contrast:
            return pair
        return None

    # Phase 1: at most one i.i.d. LLM sample, then jump to cheap deterministic cross-type.
    _try_messages(list(packed.messages), temp=float(temperature), seed_i=seed, tag="iid")
    early = _maybe_done()
    if early is not None:
        return early[0], early[1], attempts

    # Phase 2: deterministic cross-type alt (cheap; protocol-preferred) before more LLM calls.
    if seen:
        for alt in _legal_alternatives(case=case, visible=visible, forbidden=seen[0]):
            if any(_action_key(x) == _action_key(alt) for x in seen):
                continue
            attempts.append({"ok": True, "action": alt, "tag": "deterministic_cross_type"})
            seen.append(alt)
            early = _maybe_done()
            if early is not None:
                return early[0], early[1], attempts
            if _action_type(alt) != _action_type(seen[0]):
                break
    else:
        for alt in _legal_alternatives(case=case, visible=visible, forbidden=None)[:2]:
            attempts.append({"ok": True, "action": alt, "tag": "deterministic_pair"})
            seen.append(alt)

    # Phase 3: one type-targeted nudge only if still missing cross-type.
    pair = _select_action_pair(seen, allow_stop_contrast=allow_stop_contrast)
    if pair is not None and _pair_rank(pair[0], pair[1])[0] <= 1:
        return pair[0], pair[1], attempts
    if seen:
        banned_type = _action_type(seen[0])
        prefer = (
            "prefer finish/abstain vs search/read, or web vs local"
            if allow_stop_contrast
            else "prefer web vs local, or read_evidence vs search (avoid finish/abstain)"
        )
        nudge = list(packed.messages) + [
            {
                "role": "user",
                "content": (
                    "Emit a legal next action JSON whose \"action\" field is a DIFFERENT type "
                    f"than \"{banned_type}\" ({prefer})."
                ),
            }
        ]
        early = _maybe_done()
        if early is not None:
            return early[0], early[1], attempts
        _try_messages(
            nudge,
            temp=min(1.0, float(temperature) + 0.4),
            seed_i=seed + 1000,
            tag="nudge_type",
        )

    pair = _select_action_pair(seen, allow_stop_contrast=allow_stop_contrast)
    if pair is None:
        return None, None, attempts
    return pair[0], pair[1], attempts


def _side_metrics(case: TaskCase, result: dict[str, Any], *, initial_tool_budget: int) -> dict[str, Any]:
    usage = result.get("usage") or {}
    c = normalized_cost(
        input_tokens=usage.get("input_tokens") or 0,
        output_tokens=usage.get("output_tokens") or 0,
        tool_calls=usage.get("tool_calls") or 0,
        initial_tool_budget=initial_tool_budget,
    )
    score_error: str | None = None
    try:
        score = score_case(case, result)
    except Exception as exc:  # noqa: BLE001
        # Do not abort the whole collection on one malformed claim field.
        score = {"Q": 0.0, "G_gold_anchored": None}
        score_error = f"score_error:{type(exc).__name__}:{exc}"
    forged = bool(
        case.task.get("category") == "insufficient_evidence"
        and result.get("terminal") == "finish"
        and float(score.get("Q") or 0) < 0.5
    )
    return {
        "q": float(score.get("Q") or 0.0),
        "g": score.get("G_gold_anchored"),
        "c": c,
        "forged_confident_on_insufficient": forged,
        "score": score,
        "usage": usage,
        "error": result.get("error") or score_error,
        "terminal": result.get("terminal"),
        "status": result.get("status"),
        "run_id": result.get("run_id"),
        "actions": result.get("actions") or [],
    }


def _branch_incomplete(m: dict[str, Any]) -> str | None:
    if m.get("error"):
        return f"branch_error:{m.get('error')}"
    if m.get("terminal") is None and m.get("status") == "failed":
        return "branch_failed_no_terminal"
    if m.get("terminal") is None:
        # Allow writer-only completion without explicit finish if status answered/partial/insufficient
        if m.get("status") in {"answered", "partial", "insufficient_evidence"}:
            return None
        return "branch_incomplete"
    return None


def _load_sft_states(
    root: Path,
    *,
    splits: list[str],
    cases_by_id: dict[str, TaskCase],
    states_per_task: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    per_task: dict[str, int] = defaultdict(int)
    for split in splits:
        path = root / "data" / "sft" / "sft_s30_v1" / f"{split}.jsonl"
        if not path.is_file():
            continue
        with path.open(encoding="utf-8") as f:
            for ln in f:
                if not ln.strip():
                    continue
                row = json.loads(ln)
                tid = str(row.get("task_id") or "")
                if tid not in cases_by_id:
                    continue
                if per_task[tid] >= states_per_task:
                    continue
                msgs = row.get("messages") or []
                if len(msgs) < 2:
                    continue
                try:
                    user_obj = json.loads(msgs[1]["content"])
                except Exception:  # noqa: BLE001
                    continue
                # Prefer non-terminal mid states (step>0 or non-empty candidates/evidence/history)
                step = int(row.get("step") or 0)
                nc = len(user_obj.get("candidates") or [])
                ne = len(user_obj.get("evidence_cards") or [])
                nr = len(user_obj.get("recent_actions") or [])
                if step <= 0 and nc == 0 and ne == 0 and nr == 0:
                    # opening-like; still usable but lower priority — skip if we want mid only
                    # Keep a fraction of openings by allowing when states_per_task not filled later.
                    continue
                out.append(
                    {
                        "task_id": tid,
                        "split": row.get("split") or split,
                        "step": step,
                        "state_hash": row.get("state_hash"),
                        "messages": msgs,
                        "user_obj": user_obj,
                        "prompt": row.get("prompt"),
                        "prompt_tokens": row.get("prompt_tokens"),
                    }
                )
                per_task[tid] += 1
    # Backfill openings when mid-states alone cannot fill states_per_task
    # (or when the split has no mid-states at all). Prefer mid first.
    for split in splits:
        path = root / "data" / "sft" / "sft_s30_v1" / f"{split}.jsonl"
        if not path.is_file():
            continue
        with path.open(encoding="utf-8") as f:
            for ln in f:
                if not ln.strip():
                    continue
                row = json.loads(ln)
                tid = str(row.get("task_id") or "")
                if tid not in cases_by_id or per_task[tid] >= states_per_task:
                    continue
                if int(row.get("step") or 0) != 0:
                    continue
                msgs = row.get("messages") or []
                if len(msgs) < 2:
                    continue
                try:
                    user_obj = json.loads(msgs[1]["content"])
                except Exception:  # noqa: BLE001
                    continue
                # Only treat true openings (empty mid signals) as backfill.
                nc = len(user_obj.get("candidates") or [])
                ne = len(user_obj.get("evidence_cards") or [])
                nr = len(user_obj.get("recent_actions") or [])
                if nc or ne or nr:
                    continue
                out.append(
                    {
                        "task_id": tid,
                        "split": row.get("split") or split,
                        "step": 0,
                        "state_hash": row.get("state_hash"),
                        "messages": msgs,
                        "user_obj": user_obj,
                        "prompt": row.get("prompt"),
                        "prompt_tokens": row.get("prompt_tokens"),
                    }
                )
                per_task[tid] += 1
    return out


def _preflight(client: HttpLLMClient, adapter_id: str) -> None:
    resp = client.chat(
        [{"role": "user", "content": 'Reply with JSON: {"action":"abstain","query":null,"candidate_id":null,"reason_code":"budget_exhausted"}'}],
        max_tokens=64,
        temperature=0.0,
        adapter_id=adapter_id,
        guided_json=ACTION_GUIDED_JSON,
        seed=0,
    )
    obj = parse_json_object(resp.content)
    coerce_policy_action(obj, allow_web=False, known_candidate_ids=set())


def collect(
    *,
    root: Path,
    out_dir: Path,
    adapter_id: str,
    max_pairs: int,
    max_pairs_train: int,
    max_pairs_dev: int,
    seed: int,
    splits: list[str],
    state_source: str,
    states_per_task: int,
    resume: bool,
    skip_review_if_no_seed: bool,
) -> dict[str, Any]:
    if "test" in splits:
        raise SystemExit("test split is forbidden for preference collection")
    out_dir.mkdir(parents=True, exist_ok=True)
    branch_dir = out_dir / "branches"
    branch_dir.mkdir(parents=True, exist_ok=True)
    client = HttpLLMClient()
    try:
        _preflight(client, adapter_id)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"preflight_failed: {type(exc).__name__}: {exc}") from exc

    cases: list[TaskCase] = []
    for split in splits:
        cases.extend(load_cases(root, datasets=["chinese", "hotpotqa"], split=split))
    cases_by_id = {c.task_id: c for c in cases}

    pairs_path = out_dir / "pairs.jsonl"
    discarded_path = out_dir / "discarded.jsonl"
    done_tasks: set[str] = set()
    done_states: set[tuple[str, str]] = set()
    done_steps: set[tuple[str, int]] = set()
    done_action_pairs: set[tuple[str, str, str]] = set()
    kept = 0
    kept_train = 0
    kept_dev = 0
    discarded = 0

    def _mark_done(row: dict[str, Any], *, count_discard: bool) -> None:
        nonlocal discarded
        tid = str(row.get("task_id") or "")
        if tid:
            done_tasks.add(tid)
        sh = str(row.get("state_hash") or "")
        if tid and sh:
            done_states.add((tid, sh))
        if tid and row.get("step") is not None:
            try:
                done_steps.add((tid, int(row["step"])))
            except (TypeError, ValueError):
                pass
        aa = row.get("action_a") or row.get("chosen")
        ab = row.get("action_b") or row.get("rejected")
        if tid and isinstance(aa, dict) and isinstance(ab, dict):
            ka, kb = _action_key(aa), _action_key(ab)
            done_action_pairs.add((tid, ka, kb))
            done_action_pairs.add((tid, kb, ka))
        if count_discard:
            discarded += 1

    if resume and pairs_path.is_file():
        # Deduplicate exact logical pairs written under unstable wall-affected hashes.
        unique_pairs: list[dict[str, Any]] = []
        seen_pair_keys: set[tuple[str, str, str]] = set()
        for row in _load_jsonl(pairs_path):
            tid = str(row.get("task_id") or "")
            aa = row.get("action_a") or {}
            ab = row.get("action_b") or {}
            if isinstance(aa, dict) and isinstance(ab, dict):
                ka, kb = _action_key(aa), _action_key(ab)
                key = (tid, min(ka, kb), max(ka, kb))
                if key in seen_pair_keys:
                    continue
                seen_pair_keys.add(key)
            unique_pairs.append(row)
            _mark_done(row, count_discard=False)
            kept += 1
            if row.get("split") == "dev":
                kept_dev += 1
            else:
                kept_train += 1
        # Rewrite compact unique pairs if duplicates were dropped.
        raw_n = sum(1 for _ in pairs_path.open(encoding="utf-8") if _.strip())
        if len(unique_pairs) < raw_n:
            pairs_path.write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in unique_pairs) + ("\n" if unique_pairs else ""),
                encoding="utf-8",
            )
            print(f"deduped_pairs {raw_n}->{len(unique_pairs)}", flush=True)
        if discarded_path.is_file():
            for row in _load_jsonl(discarded_path):
                reason = str(row.get("reason") or (row.get("final") or {}).get("reason") or "")
                # Transient branch failures (timeout / incomplete) may succeed after
                # remaining-budget max_steps + fresh wall; do not permanently skip.
                if reason.startswith("branch_error:") or reason in {
                    "branch_incomplete",
                    "branch_failed_no_terminal",
                    "review_branch_incomplete",
                }:
                    discarded += 1
                    continue
                _mark_done(row, count_discard=True)
    else:
        for p in (pairs_path, discarded_path):
            if p.exists():
                p.unlink()

    # Probe whether seed is accepted AND changes sampling (many vLLM builds ignore seed).
    seed_supported = False
    try:
        probe_msgs = [
            {
                "role": "user",
                "content": 'Pick one JSON at random: {"action":"finish","query":null,"candidate_id":null,"reason_code":"evidence_sufficient"} or {"action":"abstain","query":null,"candidate_id":null,"reason_code":"budget_exhausted"}',
            }
        ]
        samples: list[str] = []
        for s in (seed, seed + 1, seed + 2, seed + 3):
            rr = client.chat(
                probe_msgs,
                max_tokens=64,
                temperature=0.9,
                adapter_id=adapter_id,
                seed=s,
                guided_json=ACTION_GUIDED_JSON,
            )
            samples.append((rr.content or "").strip())
        seed_accepted = True
        seed_supported = len(set(samples)) >= 2
        if not seed_supported:
            print(
                f"seed_not_independent accepted={seed_accepted} unique={len(set(samples))} samples={samples[:2]}",
                flush=True,
            )
    except Exception as exc:  # noqa: BLE001
        seed_supported = False
        print(f"seed_probe_failed: {type(exc).__name__}: {exc}", flush=True)

    work_items: list[dict[str, Any]] = []
    if state_source == "opening":
        for case in cases:
            visible, budget = _empty_visible(case)
            packed = pack_visible_state(visible)
            work_items.append(
                {
                    "task_id": case.task_id,
                    "split": case.task.get("split") or "train",
                    "visible": visible,
                    "budget": budget,
                    "messages": packed.messages,
                    "prompt": None,
                    "prompt_tokens": packed.prompt_tokens,
                    "state_hash": _preference_state_hash(visible),
                    "step": 0,
                }
            )
    else:
        sft_rows = _load_sft_states(
            root, splits=splits, cases_by_id=cases_by_id, states_per_task=states_per_task
        )
        for row in sft_rows:
            case = cases_by_id[row["task_id"]]
            visible, budget = _visible_from_packed_user(case, row["user_obj"])
            # Prefer SFT prompt when available (matches training distribution).
            msgs = row.get("messages")
            work_items.append(
                {
                    "task_id": case.task_id,
                    "split": row.get("split") or case.task.get("split") or "train",
                    "visible": visible,
                    "budget": budget,
                    "messages": msgs,
                    "prompt": row.get("prompt"),
                    "prompt_tokens": row.get("prompt_tokens"),
                    "state_hash": _preference_state_hash(visible),
                    "step": row.get("step"),
                }
            )

    # Prefer high-yield categories (mul/dir) before ver/ins/hpqa empty-burn.
    work_items.sort(
        key=lambda it: (
            _DATASET_PRIORITY.get(cases_by_id[it["task_id"]].dataset, 9),
            _TASK_CAT_PRIORITY.get(_task_category(it["task_id"]), 5),
            _remaining_tool_budget(it["budget"]),
            int(it.get("step") or 0),
        )
    )

    def _quota_full(split: str) -> bool:
        if max_pairs and kept >= max_pairs:
            return True
        if split == "dev":
            return bool(max_pairs_dev and kept_dev >= max_pairs_dev)
        return bool(max_pairs_train and kept_train >= max_pairs_train)

    def _already_done(item: dict[str, Any], case: TaskCase) -> bool:
        tid = case.task_id
        sh = str(item.get("state_hash") or "")
        if (tid, sh) in done_states:
            return True
        if item.get("step") is not None:
            try:
                if (tid, int(item["step"])) in done_steps:
                    return True
            except (TypeError, ValueError):
                pass
        return False

    for item in work_items:
        case = cases_by_id[item["task_id"]]
        split = str(item.get("split") or "train")
        if resume and state_source == "opening" and case.task_id in done_tasks:
            continue
        if resume and _already_done(item, case):
            continue
        if _quota_full(split):
            # Still allow other split to continue
            if all(_quota_full(s) for s in splits):
                break
            if _quota_full(split):
                continue
        # Avoid burning budget on empirically zero-yield categories until
        # the *current split* quota is met (train or dev).
        if (
            not _quota_full(split)
            and _task_category(case.task_id) in _SKIP_WHILE_FILLING
        ):
            continue

        visible: VisibleState = copy.deepcopy(item["visible"])
        budget_template: BudgetState = copy.deepcopy(item["budget"])
        # Keep frozen packed budget on visible for identity/prompts; wall resets in _fresh_budget.
        state_h = str(item.get("state_hash") or _preference_state_hash(visible))
        visible.budget = dict(visible.budget or budget_template.visible_budget())
        cand_store = _enrich_cand_store_from_case(root, case)
        # Also register candidates already in visible (preview-only) if missing text
        for c in visible.candidates:
            cid = str(c.get("candidate_id") or "")
            if cid and cid not in cand_store:
                cand_store[cid] = dict(c)

        a1, a2, attempts = sample_actions_from_state(
            client,
            case=case,
            visible=visible,
            adapter_id=adapter_id,
            temperature=0.6,
            seed=seed,
        )
        if a1 is None or a2 is None:
            rec_skip = {
                "task_id": case.task_id,
                "split": split,
                "state_hash": state_h,
                "step": item.get("step"),
                "reason": "no_diverse_pair",
                "attempts": attempts[-4:],
            }
            _append_jsonl(discarded_path, rec_skip)
            _mark_done(rec_skip, count_discard=True)
            continue
        if a1 == a2:
            rec_skip = {
                "task_id": case.task_id,
                "split": split,
                "state_hash": state_h,
                "step": item.get("step"),
                "reason": "identical_actions",
            }
            _append_jsonl(discarded_path, rec_skip)
            _mark_done(rec_skip, count_discard=True)
            continue
        if (case.task_id, _action_key(a1), _action_key(a2)) in done_action_pairs:
            continue

        initial_tools = max(1, _remaining_tool_budget(budget_template))
        max_steps = _branch_max_steps(budget_template)

        def _run_branch(system: str, action: dict[str, Any], *, policy_seed: int) -> dict[str, Any]:
            # Stop-first branches need only 1 loop step; continue side keeps full remaining budget.
            side_steps = 1 if _action_type(action) in _STOP_TYPES else max_steps
            return run_case(
                root=root,
                case=case,
                client=client,
                system=system,
                policy_adapter_id=adapter_id,
                forced_first_action=action,
                start_visible=copy.deepcopy(visible),
                start_budget=_fresh_budget(budget_template),
                start_cand_store=dict(cand_store),
                max_steps=side_steps,
                policy_temperature=0.3,
                policy_seed=policy_seed,
            )

        # Same preference pair only: dual branches in parallel (uses vLLM max_num_seqs=2).
        # Not two independent research tasks / Worker jobs.
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_a = pool.submit(_run_branch, "branch_a", a1, policy_seed=seed)
            fut_b = pool.submit(_run_branch, "branch_b", a2, policy_seed=seed)
            branch_a = fut_a.result()
            branch_b = fut_b.result()
        ma = _side_metrics(case, branch_a, initial_tool_budget=initial_tools)
        mb = _side_metrics(case, branch_b, initial_tool_budget=initial_tools)
        bad_a = _branch_incomplete(ma)
        bad_b = _branch_incomplete(mb)
        if bad_a or bad_b:
            discarded += 1
            _append_jsonl(
                discarded_path,
                {
                    "task_id": case.task_id,
                    "split": split,
                    "state_hash": state_h,
                    "reason": bad_a or bad_b,
                    "run_id_a": ma.get("run_id"),
                    "run_id_b": mb.get("run_id"),
                },
            )
            continue

        label42 = decide_preference({**ma, "action": a1}, {**mb, "action": a2})

        do_review = seed_supported or not skip_review_if_no_seed
        if do_review and seed_supported:
            with ThreadPoolExecutor(max_workers=2) as pool:
                fut_a2 = pool.submit(_run_branch, "branch_a_s43", a1, policy_seed=seed + 1)
                fut_b2 = pool.submit(_run_branch, "branch_b_s43", a2, policy_seed=seed + 1)
                branch_a2 = fut_a2.result()
                branch_b2 = fut_b2.result()
            ma2 = _side_metrics(case, branch_a2, initial_tool_budget=initial_tools)
            mb2 = _side_metrics(case, branch_b2, initial_tool_budget=initial_tools)
            if _branch_incomplete(ma2) or _branch_incomplete(mb2):
                discarded += 1
                _append_jsonl(
                    discarded_path,
                    {
                        "task_id": case.task_id,
                        "split": split,
                        "state_hash": state_h,
                        "reason": "review_branch_incomplete",
                    },
                )
                continue
            label43 = decide_preference({**ma2, "action": a1}, {**mb2, "action": a2})
            final = review_agreement(label42, label43)
        else:
            label43 = {"status": "skip", "reason": "seed_unsupported", "chosen": None}
            if label42.get("status") == "keep":
                final = {
                    "status": "keep",
                    "reason": label42.get("reason"),
                    "chosen": label42.get("chosen"),
                    "review": "not_independent",
                }
            else:
                final = label42

        # Persist branch artifacts
        pair_id = hashlib.sha256(
            f"{case.task_id}:{state_h}:{json.dumps(a1, sort_keys=True)}:{json.dumps(a2, sort_keys=True)}".encode()
        ).hexdigest()[:32]
        _write_json(
            branch_dir / f"{pair_id}_a.json",
            {
                "run_id": ma.get("run_id"),
                "actions": ma.get("actions"),
                "terminal": ma.get("terminal"),
                "status": ma.get("status"),
                "error": ma.get("error"),
                "usage": ma.get("usage"),
                "score": ma.get("score"),
            },
        )
        _write_json(
            branch_dir / f"{pair_id}_b.json",
            {
                "run_id": mb.get("run_id"),
                "actions": mb.get("actions"),
                "terminal": mb.get("terminal"),
                "status": mb.get("status"),
                "error": mb.get("error"),
                "usage": mb.get("usage"),
                "score": mb.get("score"),
            },
        )

        messages = item.get("messages")
        if not messages:
            messages = pack_visible_state(visible).messages
        prompt_text = item.get("prompt")
        prompt_tokens = item.get("prompt_tokens")
        if not prompt_text:
            # Leave raw messages; export will apply chat template if tokenizer available.
            prompt_text = json.dumps(messages, ensure_ascii=False)

        rec = {
            "pair_id": pair_id,
            "task_id": case.task_id,
            "dataset": case.dataset,
            "split": split,
            "step": item.get("step"),
            "state_hash": state_h,
            "messages": messages,
            "prompt": prompt_text,
            "prompt_tokens": prompt_tokens,
            "action_a": a1,
            "action_b": a2,
            "run_id_a": ma.get("run_id"),
            "run_id_b": mb.get("run_id"),
            "metrics_a": {k: ma[k] for k in ("q", "g", "c", "forged_confident_on_insufficient")},
            "metrics_b": {k: mb[k] for k in ("q", "g", "c", "forged_confident_on_insufficient")},
            "label_seed42": label42,
            "label_seed43": label43,
            "final": final,
            "branch_a_status": branch_a.get("status"),
            "branch_b_status": branch_b.get("status"),
            "seed_supported": seed_supported,
        }
        if final.get("status") == "keep":
            chosen_side = final["chosen"]
            rec["chosen"] = a1 if chosen_side == "a" else a2
            rec["rejected"] = a2 if chosen_side == "a" else a1
            _append_jsonl(pairs_path, rec)
            _mark_done(rec, count_discard=False)
            kept += 1
            if split == "dev":
                kept_dev += 1
            else:
                kept_train += 1
            print(
                f"KEEP {kept} train={kept_train} dev={kept_dev} {case.task_id} reason={final.get('reason')} review={final.get('review')}",
                flush=True,
            )
        else:
            _append_jsonl(discarded_path, rec)
            _mark_done(rec, count_discard=True)
            print(f"DISC {case.task_id} reason={final.get('reason')}", flush=True)

    summary = {
        "kept": kept,
        "kept_train": kept_train,
        "kept_dev": kept_dev,
        "discarded": discarded,
        "adapter_id": adapter_id,
        "seed": seed,
        "seed_supported": seed_supported,
        "state_source": state_source,
        "pairs_path": str(pairs_path),
        "min_train_for_dpo": 300,
        "target_train": 600,
        "target_dev": 100,
    }
    _write_json(out_dir / "summary.json", summary)
    _write_json(
        out_dir / "manifest.json",
        {
            "collection_id": out_dir.name,
            "protocol": "preference_protocol.md",
            "adapter_id": adapter_id,
            "seed_exec": seed,
            "seed_review": seed + 1 if seed_supported else None,
            "offline_sample_temperature": 0.6,
            "continuation_temperature": 0.3,
            "seed_supported": seed_supported,
            "state_source": state_source,
            "states_per_task": states_per_task,
            "review_mode": "seed43" if seed_supported else "not_independent",
            "diversity_fallback": [
                "iid_one",
                "deterministic_cross_type",
                "nudge_type_one",
            ],
            "max_steps_policy": "remaining_tool_budget_plus_2_stop_first_one",
            "pair_priority": "continue_vs_stop_then_cross_type",
            "branch_exec": "parallel_same_pair_max_workers_2",
            "work_order": "chinese_mul_dir_then_short_budget_before_ver_ins_hpqa",
            "state_hash_policy": "preference_ignore_remaining_wall_seconds",
        },
    )
    return summary


def export_dpo_dataset(pairs_paths: list[Path], out_dir: Path, *, root: Path | None = None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_action_pairs: set[tuple[str, str, str]] = set()
    for pairs_path in pairs_paths:
        if not pairs_path.is_file():
            continue
        for r in _load_jsonl(pairs_path):
            tid = str(r.get("task_id") or "")
            aa, ab = r.get("action_a") or r.get("chosen"), r.get("action_b") or r.get("rejected")
            if isinstance(aa, dict) and isinstance(ab, dict):
                ka, kb = _action_key(aa), _action_key(ab)
                ap_key = (tid, min(ka, kb), max(ka, kb))
                if ap_key in seen_action_pairs:
                    continue
                seen_action_pairs.add(ap_key)
            pid = str(r.get("pair_id") or "")
            key = pid or f"{tid}:{r.get('state_hash')}"
            if key in seen_ids:
                continue
            seen_ids.add(key)
            rows.append(r)
    train = [r for r in rows if r.get("split") != "dev"]
    dev = [r for r in rows if r.get("split") == "dev"]
    out_dir.mkdir(parents=True, exist_ok=True)

    tokenizer = None
    if root is not None:
        try:
            from transformers import AutoTokenizer  # type: ignore

            # Prefer adapter tokenizer files; fall back to base model dir via paths.
            tok_dir = root / "artifacts" / "adapters" / "sft" / "exp_sft_0001"
            if tok_dir.is_dir():
                tokenizer = AutoTokenizer.from_pretrained(str(tok_dir), trust_remote_code=True)
        except Exception:  # noqa: BLE001
            tokenizer = None

    def _prompt_text(r: dict[str, Any]) -> str:
        if r.get("prompt") and not str(r["prompt"]).startswith("[{"):
            # Already chat-templated string from SFT export
            if isinstance(r["prompt"], str) and "action_schema" not in r["prompt"][:40]:
                # Heuristic: SFT prompt is templated; messages dump starts with [{
                pass
        msgs = r.get("messages")
        if isinstance(msgs, list) and tokenizer is not None:
            return tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        if isinstance(r.get("prompt"), str) and r["prompt"] and not r["prompt"].startswith("[{"):
            return r["prompt"]
        if isinstance(msgs, list):
            # Fallback: serialize messages; DPO trainer can also accept this if configured.
            return json.dumps(msgs, ensure_ascii=False)
        return str(r.get("state_hash") or "")

    def _fmt(r: dict[str, Any]) -> dict[str, Any]:
        prompt = _prompt_text(r)
        return {
            "prompt": prompt,
            "chosen": json.dumps(r["chosen"], ensure_ascii=False, separators=(",", ":")),
            "rejected": json.dumps(r["rejected"], ensure_ascii=False, separators=(",", ":")),
            "task_id": r["task_id"],
            "pair_id": r["pair_id"],
            "label_reason": (r.get("final") or {}).get("reason"),
            "state_hash": r["state_hash"],
            "prompt_tokens": r.get("prompt_tokens"),
            "run_id_a": r.get("run_id_a"),
            "run_id_b": r.get("run_id_b"),
            "q_a": (r.get("metrics_a") or {}).get("q"),
            "g_a": (r.get("metrics_a") or {}).get("g"),
            "c_a": (r.get("metrics_a") or {}).get("c"),
            "q_b": (r.get("metrics_b") or {}).get("q"),
            "g_b": (r.get("metrics_b") or {}).get("g"),
            "c_b": (r.get("metrics_b") or {}).get("c"),
        }

    (out_dir / "train.jsonl").write_text(
        "\n".join(json.dumps(_fmt(r), ensure_ascii=False) for r in train) + ("\n" if train else ""),
        encoding="utf-8",
    )
    (out_dir / "dev.jsonl").write_text(
        "\n".join(json.dumps(_fmt(r), ensure_ascii=False) for r in dev) + ("\n" if dev else ""),
        encoding="utf-8",
    )
    unique_train = len({(r.get("task_id"), r.get("state_hash")) for r in train})
    report = {
        "train": len(train),
        "dev": len(dev),
        "unique_train_states": unique_train,
        "meets_min_train": len(train) >= 300,
        "meets_target": len(train) >= 600 and len(dev) >= 100,
    }
    _write_json(out_dir / "quality_report.json", report)
    _write_json(
        out_dir / "manifest.json",
        {
            "dataset_id": out_dir.name,
            "sources": [str(p) for p in pairs_paths],
            "train": len(train),
            "dev": len(dev),
        },
    )
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--adapter-id", default="sft_e1")
    ap.add_argument("--max-pairs", type=int, default=0)
    ap.add_argument("--max-pairs-train", type=int, default=0)
    ap.add_argument("--max-pairs-dev", type=int, default=0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--splits", default="train,dev")
    ap.add_argument("--state-source", choices=["opening", "sft_states"], default="sft_states")
    ap.add_argument("--states-per-task", type=int, default=3)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--skip-review-if-no-seed", action="store_true", default=True)
    ap.add_argument("--export-dpo", type=Path, default=None)
    ap.add_argument(
        "--merge-pairs",
        type=Path,
        nargs="*",
        default=None,
        help="Additional pairs.jsonl files to merge when exporting DPO",
    )
    args = ap.parse_args()
    root = args.root.resolve()
    out = args.out if args.out.is_absolute() else root / args.out
    splits = [s.strip() for s in args.splits.split(",") if s.strip()]
    summary = collect(
        root=root,
        out_dir=out,
        adapter_id=args.adapter_id,
        max_pairs=args.max_pairs,
        max_pairs_train=args.max_pairs_train,
        max_pairs_dev=args.max_pairs_dev,
        seed=args.seed,
        splits=splits,
        state_source=args.state_source,
        states_per_task=args.states_per_task,
        resume=args.resume,
        skip_review_if_no_seed=args.skip_review_if_no_seed,
    )
    if args.export_dpo:
        export_path = args.export_dpo if args.export_dpo.is_absolute() else root / args.export_dpo
        paths = [out / "pairs.jsonl"]
        if args.merge_pairs:
            for p in args.merge_pairs:
                pp = p if p.is_absolute() else root / p
                paths.append(pp)
        report = export_dpo_dataset(paths, export_path, root=root)
        summary["dpo_export"] = report
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

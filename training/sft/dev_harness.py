#!/usr/bin/env python3
"""S33 development harness: real tools + policy + Writer/Verifier, no DB.

The harness is model-level end-to-end: it reads each task corpus directly,
executes search/read actions, packs the same visible state as the product,
and runs the same Writer/Verifier prompts. Citation integrity is enforced in
code against the task's allowed snapshot ids.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
_SCRIPTS = _REPO / "scripts"
for _p in (_REPO, _SRC, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from evidence_agent.agent.actions import validate_action  # noqa: E402
from evidence_agent.agent.budget import BudgetConfig, BudgetState  # noqa: E402
from evidence_agent.agent.packer import pack_visible_state  # noqa: E402
from evidence_agent.agent.policy import run_policy  # noqa: E402
from evidence_agent.agent.result import decide_status  # noqa: E402
from evidence_agent.agent.state import VisibleState  # noqa: E402
from evidence_agent.agent.verifier import apply_verification_to_claims, run_verifier  # noqa: E402
from evidence_agent.agent.writer import run_writer  # noqa: E402
from evidence_agent.data.near_dup import normalize_question  # noqa: E402
from evaluation.metrics.chinese_q import score_task  # noqa: E402
from evaluation.metrics.english_em_f1 import exact_match, f1_score  # noqa: E402

from collect_trajectories_s30 import (  # noqa: E402
    _build_candidates,
    _parse_sections,
    _replay_candidates,
)

DATASETS = {
    "chinese": {"root": "data/tasks/chinese/zh_tech_s27_v1"},
    "hotpotqa": {"root": "data/tasks/hotpotqa/hotpotqa_distractor_s25_v1"},
    "drbench": {"root": "data/tasks/drbench/drbench_s45_v1"},
    "live": {"root": "data/tasks/live/live_s41_v1"},
}
ACTION_ORDER = ("action", "query", "candidate_id", "reason_code")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


@dataclass
class TaskCase:
    dataset: str
    task: dict[str, Any]
    gold: dict[str, Any]
    sections: list[dict[str, str]]
    allow_web: bool

    @property
    def task_id(self) -> str:
        return self.task["task_id"]

    @property
    def question(self) -> str:
        return self.task.get("question") or ""

    @property
    def allowed(self) -> list[str]:
        return list(self.task.get("allowed_snapshot_ids") or [])


def load_cases(
    root: Path,
    *,
    datasets: list[str],
    split: str = "dev",
    task_ids: set[str] | None = None,
) -> list[TaskCase]:
    cases: list[TaskCase] = []
    for dataset in datasets:
        if dataset not in DATASETS:
            raise KeyError(f"unknown_dataset:{dataset}")
        base = root / DATASETS[dataset]["root"]
        gold_path = base / f"{split}.gold.jsonl"
        gold = {row["task_id"]: row for row in _load_jsonl(gold_path)}
        # External/live may ship a single tasks.jsonl + gold.jsonl without split names.
        task_path = base / f"{split}.jsonl"
        if not task_path.is_file() and (base / "tasks.jsonl").is_file():
            task_path = base / "tasks.jsonl"
        if not gold and (base / "gold.jsonl").is_file():
            gold = {row["task_id"]: row for row in _load_jsonl(base / "gold.jsonl")}
        for task in _load_jsonl(task_path):
            tid = task.get("task_id")
            if tid not in gold:
                # External open tasks: allow empty gold with NA scoring stubs.
                if dataset not in {"drbench", "live"}:
                    continue
                gold[tid] = {
                    "task_id": tid,
                    "gold_answer": None,
                    "rubric": task.get("rubric") or {"type": "external_manual"},
                    "external": True,
                }
            if task_ids is not None and tid not in task_ids:
                continue
            corpus_rel = task.get("corpus_relpath")
            if corpus_rel and (base / corpus_rel).is_file():
                corpus = (base / corpus_rel).read_text(encoding="utf-8")
            else:
                corpus = task.get("corpus_text") or ""
            allow_web = bool(
                task.get("allow_web")
                or task.get("web_mode") in {"replay", "live"}
                or dataset in {"live", "drbench"}
            )
            cases.append(
                TaskCase(
                    dataset=dataset,
                    task=task,
                    gold=gold[tid],
                    sections=_parse_sections(corpus) if corpus else [],
                    allow_web=allow_web,
                )
            )
    return cases


class MemoryUsageLedger:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    def add(self, conn, *, kind: str, model: str, input_tokens: int, output_tokens: int, billing_status: str = "n/a", meta: dict[str, Any] | None = None):
        self.records.append(
            {
                "kind": kind,
                "model": model,
                "input_tokens": int(input_tokens),
                "output_tokens": int(output_tokens),
                "billing_status": billing_status,
                "meta": meta or {},
            }
        )
        self.input_tokens += int(input_tokens)
        self.output_tokens += int(output_tokens)
        self.calls += 1


def local_citation_check(
    claims: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    allowed_snapshot_ids: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    ok: list[dict[str, Any]] = []
    unresolved: list[str] = []
    allowed = [str(x) for x in allowed_snapshot_ids]
    for cl in claims:
        eids = cl.get("evidence_ids") or []
        if not eids:
            unresolved.append(f"missing_citation:{cl.get('text', '')[:60]}")
            continue
        good = True
        for eid in eids:
            card = evidence_by_id.get(eid)
            if not card:
                good = False
                unresolved.append(f"unknown_evidence:{eid}")
                continue
            sid = str(card.get("source_version_id") or "")
            if not any(sid == a or sid.startswith(a) or a.startswith(sid) for a in allowed):
                good = False
                unresolved.append(f"unauthorized_version:{eid}:{sid}")
            if not (card.get("quote") or "").strip():
                good = False
                unresolved.append(f"empty_quote:{eid}")
        if good:
            ok.append(cl)
    return ok, unresolved

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


def _live_web_candidates(
    *,
    root: Path,
    case: TaskCase,
    query: str,
    run_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Real Tavily live search for S45; never claim replay is live."""
    from evidence_agent.tools.web_search import WebSearchBudget, web_search

    result = web_search(
        query=query,
        mode="live",
        project_id=str(case.task.get("project") or case.dataset or "live"),
        run_id=run_id,
        root=root,
        allow_web=True,
        budget=WebSearchBudget(live_calls=0, max_live=3),
        tavily_api_key=None,  # reads TAVILY_API_KEY from env
    )
    meta = {
        "tool": "web_search",
        "mode": "live",
        "status": result.status.value if hasattr(result.status, "value") else str(result.status),
        "error_code": getattr(result, "error_code", None),
        "usage": getattr(result, "usage", None) or {},
    }
    cands: list[dict[str, Any]] = []
    payload = result.data if isinstance(getattr(result, "data", None), dict) else {}
    for item in (payload.get("candidates") or payload.get("results") or []):
        url = item.get("url") or ""
        cid = item.get("candidate_id") or f"cand_live_{hashlib.sha256(url.encode()).hexdigest()[:12]}"
        text = (item.get("text") or item.get("content") or item.get("snippet") or "")[:4000]
        cands.append(
            {
                "candidate_id": cid,
                "title": item.get("title") or url,
                "preview": (item.get("snippet") or text)[:240],
                "text": text,
                "url": url,
                "source_version_id": item.get("source_version_id") or f"live_{cid}",
                "preview_is_not_evidence": True,
            }
        )
    meta["n"] = len(cands)
    # Persist lightweight snapshot stubs for audit (S45).
    if cands:
        snap_dir = root / "data" / "snapshots" / "live" / case.task_id
        snap_dir.mkdir(parents=True, exist_ok=True)
        (snap_dir / f"search_{int(time.time())}.json").write_text(
            json.dumps({"query": query, "candidates": cands, "meta": meta}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
    return cands, meta


def _execute_action(
    *,
    root: Path,
    case: TaskCase,
    action: dict[str, Any],
    visible: VisibleState,
    cand_store: dict[str, dict[str, Any]],
    step: int,
    budget: BudgetState,
    web_mode: str = "replay",
    ablation_variant: str | None = None,
    run_id: str = "run",
) -> tuple[dict[str, Any], bool, str | None]:
    name = action["action"]
    if name in {"finish", "abstain"}:
        return {"tool": None, "status": "ok", "terminal": name}, False, None
    if name == "read_evidence" and ablation_variant == "no_source_anchor":
        # Policy-visible anchors removed; re-read disabled for this ablation only.
        obs = {
            "tool": "read_evidence",
            "status": "error",
            "error": "ablation_no_source_anchor_blocks_read",
        }
        visible.source_failures = list(visible.source_failures or []) + [
            {"error": "ablation_no_source_anchor_blocks_read", "action": "read_evidence"}
        ]
        return obs, False, None
    ok, reason = budget.can_call_tool(live_search=name == "web_search" and web_mode == "live")
    if not ok:
        return {"tool": name, "status": "error", "error": reason}, False, reason
    budget.tool_calls_used += 1
    added = False
    if name == "local_search":
        new_cands = _build_candidates(
            {**case.task, "question": action["query"]}, case.sections
        )
        existing = {c.get("candidate_id") for c in visible.candidates}
        for c in new_cands:
            cand_store.setdefault(c["candidate_id"], {**c, "source_version_id": case.allowed[0]})
            if c["candidate_id"] not in existing:
                visible.candidates.append(
                    {
                        "candidate_id": c["candidate_id"],
                        "title": c["title"],
                        "preview": c["preview"],
                        "source_version_id": case.allowed[0],
                        "preview_is_not_evidence": True,
                    }
                )
                added = True
        obs = {
            "tool": "local_search",
            "status": "ok",
            "n": len(new_cands),
            "candidate_ids": [c["candidate_id"] for c in new_cands],
        }
    elif name == "web_search":
        if web_mode == "live":
            budget.live_search_used += 1
            new_cands, obs = _live_web_candidates(
                root=root, case=case, query=str(action.get("query") or ""), run_id=run_id
            )
            if obs.get("error_code"):
                visible.source_failures = list(visible.source_failures or []) + [
                    {"error": obs.get("error_code"), "action": "web_search", "mode": "live"}
                ]
        else:
            # off/replay formal path — never label as live.
            budget.live_search_used += 1
            new_cands = _replay_candidates(root, case.task)
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
    elif name == "read_evidence":
        cid = action["candidate_id"]
        rec = cand_store.get(cid) or {}
        text = (rec.get("text") or "").strip()
        if not text:
            visible.source_failures = list(visible.source_failures or []) + [
                {"error": "empty_body", "action": "read_evidence", "candidate_id": cid}
            ]
            obs = {"tool": "read_evidence", "status": "empty", "candidate_id": cid}
        else:
            eid = f"ev_{hashlib.sha256((case.task_id + cid + text[:80]).encode()).hexdigest()[:12]}"
            if not any(e.get("evidence_id") == eid for e in (visible.evidence_cards or [])):
                visible.evidence_cards = list(visible.evidence_cards or []) + [
                    {
                        "evidence_id": eid,
                        "candidate_id": cid,
                        "source_version_id": rec.get("source_version_id") or case.allowed[0],
                        "page": None,
                        "title": rec.get("title"),
                        "quote": text[:512],
                        "scope": {},
                    }
                ]
                added = True
            obs = {"tool": "read_evidence", "status": "ok", "evidence_id": eid, "chars": len(text)}
    else:
        obs = {"tool": name, "status": "error", "error": "unknown_action"}
    return obs, added, None


def run_case(
    *,
    root: Path,
    case: TaskCase,
    client,
    system: str,
    policy_adapter_id: str | None,
    max_steps: int | None = None,
    forced_first_action: dict[str, Any] | None = None,
    policy_temperature: float = 0.0,
    policy_seed: int | None = None,
    start_visible: VisibleState | None = None,
    start_cand_store: dict[str, dict[str, Any]] | None = None,
    start_budget: BudgetState | None = None,
    budget_cfg: BudgetConfig | None = None,
    ablation_variant: str | None = None,
    web_mode: str = "replay",
) -> dict[str, Any]:
    t0 = time.perf_counter()
    if start_budget is not None:
        budget = start_budget
    elif budget_cfg is not None:
        budget = BudgetState(cfg=budget_cfg)
    else:
        budget = BudgetState(cfg=BudgetConfig())
    # Cap loop by remaining tool budget (+2 for finish/abstain after tools exhausted).
    if max_steps is None:
        remaining_tools = max(0, int(budget.cfg.tool_calls) - int(budget.tool_calls_used))
        max_steps = remaining_tools + 2
    ledger = MemoryUsageLedger()
    run_id = f"dev_{system}_{case.task_id}_{int(t0 * 1000) % 10_000_000}"
    if start_visible is not None:
        visible = start_visible
        visible.budget = budget.visible_budget()
    else:
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
    cand_store: dict[str, dict[str, Any]] = dict(start_cand_store or {})
    actions: list[dict[str, Any]] = []
    policy_attempts: list[dict[str, Any]] = []
    terminal: str | None = None
    error: str | None = None
    step = 0
    pack_meta: dict[str, Any] = {"prompt_tokens_last": None, "truncated_any": False}
    try:
        for step in range(max_steps):
            visible.budget = budget.visible_budget()
            packed = pack_visible_state(visible, ablation_variant=ablation_variant)
            pack_meta["prompt_tokens_last"] = packed.prompt_tokens
            pack_meta["truncated_any"] = pack_meta["truncated_any"] or bool(packed.truncated)
            known = {c.get("candidate_id") for c in visible.candidates if c.get("candidate_id")}
            # Ablation strips candidate_ids from policy view; validation still uses store.
            if ablation_variant == "no_source_anchor":
                known = set(cand_store.keys())
            if step == 0 and forced_first_action is not None:
                try:
                    action = validate_action(
                        forced_first_action,
                        allow_web=case.allow_web or web_mode == "live",
                        known_candidate_ids=known,
                    )
                    err = None
                    attempts = [{"raw": forced_first_action, "ok": True, "forced": True}]
                except Exception as exc:  # noqa: BLE001
                    action, err, attempts = None, f"forced_invalid:{exc}", [{"ok": False}]
            else:
                step_seed = None if policy_seed is None else int(policy_seed) + step
                action, err, attempts = run_policy(
                    client,
                    packed,
                    allow_web=case.allow_web or web_mode == "live",
                    known_candidate_ids=known,
                    budget=budget,
                    usage_ledger=ledger,
                    conn=None,
                    run_id=run_id,
                    repair_budget=1,
                    policy_adapter_id=policy_adapter_id,
                    temperature=float(policy_temperature),
                    seed=step_seed,
                )
            policy_attempts.extend(attempts)
            if err or action is None:
                error = err or "no_action"
                break
            actions.append(action)
            if action["action"] in {"finish", "abstain"}:
                terminal = action["action"]
                break
            obs, added, tool_err = _execute_action(
                root=root,
                case=case,
                action=action,
                visible=visible,
                cand_store=cand_store,
                step=step,
                budget=budget,
                web_mode=web_mode,
                ablation_variant=ablation_variant,
                run_id=run_id,
            )
            if tool_err:
                error = tool_err
                break
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
            visible.budget = budget.visible_budget()
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    claims: list[dict[str, Any]] = []
    verification: list[dict[str, Any]] = []
    unresolved: list[str] = []
    answer = ""
    status = "failed" if error else "insufficient_evidence"
    if visible.evidence_cards:
        try:
            writer_out, w_usage = run_writer(
                client,
                question=case.question,
                requirements=[
                    {"requirement_id": r.get("requirement_id"), "text": r.get("text")}
                    for r in (case.task.get("requirements") or [])
                ],
                evidence_cards=visible.evidence_cards,
            )
            ledger.add(
                None,
                kind="writer",
                model=w_usage.model,
                input_tokens=w_usage.input_tokens,
                output_tokens=w_usage.output_tokens,
            )
            claims = writer_out["claims"]
            for i, cl in enumerate(claims):
                cl.setdefault("claim_id", f"cl_{i}")
            unresolved = list(writer_out["unresolved"])
            answer = writer_out.get("answer") or ""
            evidence_by_id = {
                (c.get("evidence_id") or c.get("id")): c for c in visible.evidence_cards
            }
            ok_claims, cite_unresolved = local_citation_check(
                claims, evidence_by_id, case.allowed
            )
            unresolved.extend(cite_unresolved)
            if ok_claims:
                verification, v_usage = run_verifier(
                    client, claims=ok_claims, evidence_by_id=evidence_by_id
                )
                ledger.add(
                    None,
                    kind="verifier",
                    model=v_usage.model,
                    input_tokens=v_usage.input_tokens,
                    output_tokens=v_usage.output_tokens,
                )
                ok_claims, v_unresolved = apply_verification_to_claims(ok_claims, verification)
                unresolved.extend(v_unresolved)
            claims = ok_claims
            status = decide_status(
                claims=claims, unresolved=unresolved, verification=verification
            )
            if status == "insufficient_evidence" and not claims:
                answer = "当前资料与已执行搜索不足以支持主要结论（未找到不等于不存在）。"
        except Exception as exc:  # noqa: BLE001
            error = error or f"writer_verifier:{type(exc).__name__}: {exc}"
            status = "failed"
    else:
        answer = "当前资料与已执行搜索不足以支持主要结论（未找到不等于不存在）。"

    return {
        "task_id": case.task_id,
        "dataset": case.dataset,
        "system": system,
        "run_id": run_id,
        "policy_adapter_id": policy_adapter_id,
        "status": status,
        "answer": answer,
        "claims": claims,
        "verification": verification,
        "unresolved": unresolved,
        "evidence_cards": visible.evidence_cards,
        "actions": actions,
        "terminal": terminal,
        "policy_attempts": policy_attempts,
        "usage": {
            "input_tokens": ledger.input_tokens,
            "output_tokens": ledger.output_tokens,
            "model_calls": ledger.calls,
            "tool_calls": budget.tool_calls_used,
            "live_search_used": budget.live_search_used,
        },
        "wall_seconds": round(time.perf_counter() - t0, 3),
        "error": error,
        "tool_budget": int(budget.cfg.tool_calls),
        "temperature": float(policy_temperature),
        "seed": policy_seed,
        "ablation_variant": ablation_variant,
        "web_mode": web_mode,
        "pack_meta": pack_meta,
    }

def _tokens(text: str) -> set[str]:
    norm = normalize_question(text)
    latin = re.findall(r"[a-z0-9]+", norm)
    cjk = re.findall(r"[\u4e00-\u9fff]", norm)
    return set(latin) | set(cjk)


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _gold_anchor(card: dict[str, Any], gold: dict[str, Any], dataset: str) -> bool:
    spans = gold.get("gold_support_spans") or []
    if dataset == "chinese":
        sid = str(card.get("source_version_id") or "")
        sid = sid.removeprefix("web::")
        for span in spans:
            doc_id = str(span.get("doc_id") or "")
            if doc_id and (sid == doc_id or sid.startswith(doc_id) or doc_id.startswith(sid)):
                return True
        return False
    title = normalize_question(str(card.get("title") or ""))
    if not title:
        return False
    for span in spans:
        st = normalize_question(str(span.get("title") or ""))
        if st and (title == st or title in st or st in title):
            return True
    return False


def _claim_supported(
    claim: dict[str, Any],
    card: dict[str, Any],
    verification_by_claim: dict[str, str],
    gold: dict[str, Any],
    dataset: str,
) -> bool:
    cid = claim.get("claim_id") or claim.get("id")
    if verification_by_claim.get(str(cid)) != "supported":
        return False
    text = str(claim.get("text") or "")
    quote = str(card.get("quote") or "")
    if not text or not quote:
        return False
    overlap = _jaccard(text, quote)
    contained = normalize_question(text) in normalize_question(quote)
    if overlap < 0.15 and not contained:
        return False
    return _gold_anchor(card, gold, dataset)


def score_case(case: TaskCase, result: dict[str, Any]) -> dict[str, Any]:
    claims = result.get("claims") or []
    verification = result.get("verification") or []
    verification_by_claim = {
        str(v.get("claim_id")): str(v.get("label")) for v in verification if v.get("claim_id") is not None
    }
    evidence_by_id = {
        (c.get("evidence_id") or c.get("id")): c for c in (result.get("evidence_cards") or [])
    }
    q_detail: dict[str, Any] | None = None
    external = case.dataset in {"drbench", "live"} or bool((case.gold or {}).get("external"))
    if case.dataset == "chinese":
        q_detail = score_task(
            online=case.task,
            gold=case.gold,
            prediction={"status": result.get("status"), "claims": claims},
        )
        q = float(q_detail.get("Q") or 0.0)
        q_em = q
        q_f1 = q
        answer_contains_gold = None
    elif external and not case.gold.get("gold_answer"):
        # Pre-registered external rubric: do not invent Q from missing gold.
        # Report structural completion only; human/external audit fills quality later.
        status = str(result.get("status") or "")
        q = 1.0 if status in {"answered", "insufficient_evidence", "partial"} else 0.0
        q_em = q
        q_f1 = q
        answer_contains_gold = None
        q_detail = {
            "Q": q,
            "rubric": "external_structural_only",
            "note": "not_mixed_into_main_aggregates",
        }
    else:
        gold_answer = str(case.gold.get("gold_answer") or "")
        answer = str(result.get("answer") or "")
        em_answer = exact_match(answer, gold_answer)
        f1_answer = f1_score(answer, gold_answer)
        em_claims = [exact_match(str(c.get("text") or ""), gold_answer) for c in claims] or [0.0]
        f1_claims = [f1_score(str(c.get("text") or ""), gold_answer) for c in claims] or [0.0]
        q_em = max([em_answer] + em_claims)
        q_f1 = max([f1_answer] + f1_claims)
        q = q_f1
        answer_contains_gold = normalize_question(gold_answer) in normalize_question(answer)

    supported_claims = 0
    relations = 0
    supported_relations = 0
    anchored_claims = 0
    for cl in claims:
        eids = cl.get("evidence_ids") or []
        cid = str(cl.get("claim_id") or cl.get("id"))
        if verification_by_claim.get(cid) == "supported":
            supported_claims += 1
        anchor_hit = False
        for eid in eids:
            card = evidence_by_id.get(eid)
            if not card:
                continue
            relations += 1
            if _gold_anchor(card, case.gold, case.dataset):
                anchor_hit = True
            if _claim_supported(cl, card, verification_by_claim, case.gold, case.dataset):
                supported_relations += 1
        if anchor_hit:
            anchored_claims += 1
    n_claims = len(claims)
    return {
        "task_id": case.task_id,
        "dataset": case.dataset,
        "system": result.get("system"),
        "status": result.get("status"),
        "Q": round(q, 4),
        "Q_em": round(q_em, 4),
        "Q_f1": round(q_f1, 4),
        "G_verifier": round(supported_claims / n_claims, 4) if n_claims else None,
        "G_gold_anchored": round(supported_relations / relations, 4) if relations else None,
        "citation_anchor_rate": round(anchored_claims / n_claims, 4) if n_claims else None,
        "claims": n_claims,
        "evidence": len(result.get("evidence_cards") or []),
        "answered_false": bool(
            result.get("status") == "answered" and q < 0.5
        ),
        "action_valid_rate": _action_valid_rate(result.get("policy_attempts") or []),
        "stop_action": (result.get("actions") or [{}])[-1].get("action") if result.get("actions") else None,
        "usage": result.get("usage") or {},
        "wall_seconds": result.get("wall_seconds"),
        "error": result.get("error"),
        "answer_contains_gold": answer_contains_gold,
        "q_detail": q_detail if case.dataset == "chinese" else None,
    }


def _action_valid_rate(attempts: list[dict[str, Any]]) -> float:
    if not attempts:
        return 0.0
    ok = sum(1 for a in attempts if a.get("ok"))
    return round(ok / len(attempts), 4)


def aggregate(scored: list[dict[str, Any]]) -> dict[str, Any]:
    if not scored:
        return {"n": 0}
    def mean(key: str):
        vals = [x[key] for x in scored if isinstance(x.get(key), (int, float))]
        return round(sum(vals) / len(vals), 4) if vals else None
    statuses: dict[str, int] = {}
    for x in scored:
        statuses[str(x.get("status"))] = statuses.get(str(x.get("status")), 0) + 1
    return {
        "n": len(scored),
        "Q_mean": mean("Q"),
        "Q_em_mean": mean("Q_em"),
        "Q_f1_mean": mean("Q_f1"),
        "G_verifier_mean": mean("G_verifier"),
        "G_gold_anchored_mean": mean("G_gold_anchored"),
        "citation_anchor_rate_mean": mean("citation_anchor_rate"),
        "answered_false_rate": round(sum(1 for x in scored if x.get("answered_false")) / len(scored), 4),
        "action_valid_rate_mean": mean("action_valid_rate"),
        "avg_input_tokens": round(sum((x.get("usage") or {}).get("input_tokens", 0) for x in scored) / len(scored), 1),
        "avg_output_tokens": round(sum((x.get("usage") or {}).get("output_tokens", 0) for x in scored) / len(scored), 1),
        "avg_tool_calls": round(sum((x.get("usage") or {}).get("tool_calls", 0) for x in scored) / len(scored), 2),
        "avg_wall_seconds": round(sum(x.get("wall_seconds") or 0 for x in scored) / len(scored), 3),
        "statuses": statuses,
        "errors": sum(1 for x in scored if x.get("error")),
    }

#!/usr/bin/env python3
"""ORPHAN duplicate — do not extend.

S42+ formal dispatch is `formal_systems.py` via `dev_eval.py`. This module is
kept only for historical reference; resume paths and result `run_id` prefixes
differ. Prefer `formal_systems.run_formal_case`.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from evidence_agent.agent.actions import ActionValidationError, validate_action
from evidence_agent.agent.budget import BudgetConfig, BudgetState
from evidence_agent.agent.llm import parse_json_object
from evidence_agent.agent.result import decide_status
from evidence_agent.agent.state import VisibleState
from evidence_agent.agent.verifier import apply_verification_to_claims, run_verifier
from evidence_agent.agent.writer import run_writer

from dev_harness import (  # noqa: E402
    MemoryUsageLedger,
    TaskCase,
    _append_recent,
    _execute_action,
    local_citation_check,
    run_case,
)

MAIN_SYSTEMS = ("b0", "b1", "b2", "e0", "e1", "e2")

_REACT_SYSTEM = (
    "你是资料研究任务的下一步动作控制器（ReAct 滚动历史模式）。"
    "只能依据问题、近期动作与观察、候选来源和剩余预算选择下一步。"
    "输出一个 JSON 对象，字段仅有 action, query, candidate_id, reason_code。"
    "搜索摘要只是候选，不是已读原文。缺少证据时继续查找/阅读或 abstain，"
    "不用参数记忆补成确定事实。finish 表示根据现有已读来源生成答案。"
)
_HISTORY_WINDOW = 12


def system_adapter(system: str) -> str | None:
    s = system.lower().strip()
    if s in {"e0", "base", "b0", "b1", "b2"}:
        return None
    if s in {"e1", "e1_final", "sft_e1"}:
        return "sft_e1"
    if s in {"e2", "e2_final", "dpo_e2", "exp_dpo_0001"}:
        return "dpo_e2"
    if s in {"e1_ckpt_600", "e1_ckpt_616"}:
        return s
    return s


def _requirements(case: TaskCase) -> list[dict[str, Any]]:
    return [
        {"requirement_id": r.get("requirement_id"), "text": r.get("text")}
        for r in (case.task.get("requirements") or [])
    ]


def _new_visible(case: TaskCase, budget: BudgetState) -> VisibleState:
    return VisibleState(
        question=case.question,
        requirements=_requirements(case),
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


def _writer_verifier(
    *,
    client,
    case: TaskCase,
    evidence_cards: list[dict[str, Any]],
    ledger: MemoryUsageLedger,
    error: str | None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], list[str], str, str | None]:
    claims: list[dict[str, Any]] = []
    verification: list[dict[str, Any]] = []
    unresolved: list[str] = []
    answer = ""
    status = "failed" if error else "insufficient_evidence"
    if not evidence_cards:
        answer = "当前资料与已执行搜索不足以支持主要结论（未找到不等于不存在）。"
        return status, claims, verification, unresolved, answer, error
    try:
        writer_out, w_usage = run_writer(
            client,
            question=case.question,
            requirements=_requirements(case),
            evidence_cards=evidence_cards,
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
        evidence_by_id = {(c.get("evidence_id") or c.get("id")): c for c in evidence_cards}
        ok_claims, cite_unresolved = local_citation_check(claims, evidence_by_id, case.allowed)
        unresolved.extend(cite_unresolved)
        if ok_claims:
            verification, v_usage = run_verifier(client, claims=ok_claims, evidence_by_id=evidence_by_id)
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
        status = decide_status(claims=claims, unresolved=unresolved, verification=verification)
        if status == "insufficient_evidence" and not claims:
            answer = "当前资料与已执行搜索不足以支持主要结论（未找到不等于不存在）。"
    except Exception as exc:  # noqa: BLE001
        error = error or f"writer_verifier:{type(exc).__name__}: {exc}"
        status = "failed"
    return status, claims, verification, unresolved, answer, error


def _base_result(
    *,
    case: TaskCase,
    system: str,
    run_id: str,
    policy_adapter_id: str | None,
    t0: float,
    budget: BudgetState,
    ledger: MemoryUsageLedger,
    status: str,
    answer: str,
    claims: list,
    verification: list,
    unresolved: list,
    evidence_cards: list,
    actions: list,
    terminal: str | None,
    policy_attempts: list,
    error: str | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
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
        "evidence_cards": evidence_cards,
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
    }
    if extra:
        out.update(extra)
    return out


def run_b0_case(*, root: Path, case: TaskCase, client, top_k: int = 6) -> dict[str, Any]:
    t0 = time.perf_counter()
    budget = BudgetState(cfg=BudgetConfig())
    ledger = MemoryUsageLedger()
    run_id = f"main_b0_{case.task_id}_{int(t0 * 1000) % 10_000_000}"
    visible = _new_visible(case, budget)
    cand_store: dict[str, dict[str, Any]] = {}
    actions: list[dict[str, Any]] = []
    error: str | None = None
    search_obs: dict[str, Any] | None = None
    try:
        search = {
            "action": "local_search",
            "query": case.question,
            "candidate_id": None,
            "reason_code": None,
        }
        actions.append(search)
        search_obs, _added, tool_err = _execute_action(
            root=root,
            case=case,
            action=search,
            visible=visible,
            cand_store=cand_store,
            step=0,
            budget=budget,
        )
        if tool_err:
            error = tool_err
        else:
            cands = list(visible.candidates)[:top_k]
            for i, cand in enumerate(cands):
                read = {
                    "action": "read_evidence",
                    "query": None,
                    "candidate_id": cand["candidate_id"],
                    "reason_code": None,
                }
                actions.append(read)
                _obs, added, tool_err = _execute_action(
                    root=root,
                    case=case,
                    action=read,
                    visible=visible,
                    cand_store=cand_store,
                    step=i + 1,
                    budget=budget,
                )
                if tool_err:
                    error = tool_err
                    break
                _append_recent(visible, i + 1, read, added)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    status, claims, verification, unresolved, answer, error = _writer_verifier(
        client=client,
        case=case,
        evidence_cards=visible.evidence_cards or [],
        ledger=ledger,
        error=error,
    )
    return _base_result(
        case=case,
        system="b0",
        run_id=run_id,
        policy_adapter_id=None,
        t0=t0,
        budget=budget,
        ledger=ledger,
        status=status,
        answer=answer,
        claims=claims,
        verification=verification,
        unresolved=unresolved,
        evidence_cards=visible.evidence_cards or [],
        actions=actions,
        terminal=None,
        policy_attempts=[],
        error=error,
        extra={"memory_mode": "static_top6", "search_obs": search_obs},
    )


def _b1_policy(
    client,
    *,
    messages: list[dict[str, str]],
    allow_web: bool,
    known: set[str],
    budget: BudgetState,
    ledger: MemoryUsageLedger,
    repair: int = 1,
) -> tuple[dict[str, Any] | None, str | None, list[dict[str, Any]]]:
    msgs = list(messages)
    attempts: list[dict[str, Any]] = []
    for attempt in range(repair + 1):
        ok, reason = budget.can_call_model(
            max_input=1800, max_output=256, is_final_writer_or_verifier=False
        )
        if not ok:
            return None, reason or "budget", attempts
        resp = client.chat(msgs, max_tokens=256, temperature=0.0, adapter_id=None)
        budget.record_tokens(input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens)
        ledger.add(
            None,
            kind="policy",
            model=resp.usage.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            meta={"attempt": attempt, "system": "b1"},
        )
        raw = resp.content
        try:
            obj = parse_json_object(raw)
            action = validate_action(obj, allow_web=allow_web, known_candidate_ids=known)
            attempts.append({"raw": raw[:500], "ok": True})
            return action, None, attempts
        except (ValueError, ActionValidationError, json.JSONDecodeError, TypeError) as exc:
            attempts.append({"raw": raw[:500], "ok": False, "error": str(exc)})
            if attempt >= repair:
                return None, "failed_policy", attempts
            msgs = list(messages) + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        f"Previous output invalid ({exc}). "
                        "Reply with only one JSON object: action, query, candidate_id, reason_code."
                    ),
                },
            ]
    return None, "failed_policy", attempts


def run_b1_case(*, root: Path, case: TaskCase, client) -> dict[str, Any]:
    t0 = time.perf_counter()
    budget = BudgetState(cfg=BudgetConfig())
    ledger = MemoryUsageLedger()
    run_id = f"main_b1_{case.task_id}_{int(t0 * 1000) % 10_000_000}"
    visible = _new_visible(case, budget)
    cand_store: dict[str, dict[str, Any]] = {}
    actions: list[dict[str, Any]] = []
    policy_attempts: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    source_log: list[dict[str, Any]] = []
    terminal: str | None = None
    error: str | None = None
    remaining = max(0, int(budget.cfg.tool_calls) - int(budget.tool_calls_used)) + 2
    try:
        for step in range(remaining):
            visible.budget = budget.visible_budget()
            known = {c.get("candidate_id") for c in visible.candidates if c.get("candidate_id")}
            payload = {
                "question": case.question,
                "requirements": _requirements(case),
                "allow_web": case.allow_web,
                "budget": budget.visible_budget(),
                "candidates": visible.candidates[-16:],
                "source_log_min": source_log[-8:],
                "recent_history": history[-_HISTORY_WINDOW:],
                "note": "B1 uses rolling action/observation history; no persistent evidence-card packing.",
            }
            messages = [
                {"role": "system", "content": _REACT_SYSTEM},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
            action, err, attempts = _b1_policy(
                client,
                messages=messages,
                allow_web=case.allow_web,
                known=known,
                budget=budget,
                ledger=ledger,
            )
            policy_attempts.extend(attempts)
            if err or action is None:
                error = err or "no_action"
                break
            actions.append(action)
            if action["action"] in {"finish", "abstain"}:
                terminal = action["action"]
                history.append({"step": step, "action": action, "observation": {"note": action["action"]}})
                break
            obs, added, tool_err = _execute_action(
                root=root,
                case=case,
                action=action,
                visible=visible,
                cand_store=cand_store,
                step=step,
                budget=budget,
            )
            if tool_err:
                error = tool_err
                break
            if action["action"] == "read_evidence":
                cid = action.get("candidate_id")
                rec = cand_store.get(cid) or {}
                source_log.append(
                    {
                        "candidate_id": cid,
                        "snippet": (rec.get("text") or "")[:200],
                        "title": rec.get("title"),
                    }
                )
            history.append({"step": step, "action": action, "observation": obs})
            _append_recent(visible, step, action, added)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    status, claims, verification, unresolved, answer, error = _writer_verifier(
        client=client,
        case=case,
        evidence_cards=visible.evidence_cards or [],
        ledger=ledger,
        error=error,
    )
    return _base_result(
        case=case,
        system="b1",
        run_id=run_id,
        policy_adapter_id=None,
        t0=t0,
        budget=budget,
        ledger=ledger,
        status=status,
        answer=answer,
        claims=claims,
        verification=verification,
        unresolved=unresolved,
        evidence_cards=visible.evidence_cards or [],
        actions=actions,
        terminal=terminal,
        policy_attempts=policy_attempts,
        error=error,
        extra={"memory_mode": "rolling_history", "source_log": source_log},
    )


def _parse_subtasks(raw: str, question: str) -> list[str]:
    try:
        obj = parse_json_object(raw)
        subs = obj.get("subtasks") or []
        if isinstance(subs, list) and subs:
            return [str(s)[:256] for s in subs[:3]]
    except Exception:
        pass
    return [question[:256]]


def _parse_research_actions(raw: str) -> list[dict[str, Any]]:
    try:
        obj = parse_json_object(raw)
        acts = obj.get("actions") or []
        if isinstance(acts, list) and acts:
            return [a for a in acts[:4] if isinstance(a, dict)]
        if obj.get("action"):
            return [obj]
    except Exception:
        pass
    return [{"action": "local_search", "query": "research", "candidate_id": None, "reason_code": None}]


def run_b2_case(*, root: Path, case: TaskCase, client) -> dict[str, Any]:
    t0 = time.perf_counter()
    budget = BudgetState(cfg=BudgetConfig())
    ledger = MemoryUsageLedger()
    run_id = f"main_b2_{case.task_id}_{int(t0 * 1000) % 10_000_000}"
    visible = _new_visible(case, budget)
    cand_store: dict[str, dict[str, Any]] = {}
    actions: list[dict[str, Any]] = []
    policy_attempts: list[dict[str, Any]] = []
    meter = {
        "orchestrator_llm_calls": 0,
        "subagent_llm_calls": 0,
        "subtask_count": 0,
        "coordination_steps": 0,
        "tool_calls": 0,
    }
    error: str | None = None
    step = 0
    try:
        ok, reason = budget.can_call_model(max_input=2000, max_output=512, is_final_writer_or_verifier=False)
        if not ok:
            error = reason or "budget"
        else:
            resp = client.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "B2 deep_research adapter: plan → research subagent → synthesize. "
                            'Output JSON: {"subtasks": ["..."]}. Max 3 subtasks. Do not invent facts.'
                        ),
                    },
                    {"role": "user", "content": case.question},
                ],
                max_tokens=512,
                temperature=0.0,
                adapter_id=None,
            )
            budget.record_tokens(input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens)
            ledger.add(
                None,
                kind="b2_orchestrator",
                model=resp.usage.model,
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
            )
            meter["orchestrator_llm_calls"] += 1
            policy_attempts.append({"raw": resp.content[:500], "ok": True, "role": "orchestrator"})
            subtasks = _parse_subtasks(resp.content, case.question)
            meter["subtask_count"] = len(subtasks)

            for topic in subtasks:
                meter["coordination_steps"] += 1
                ok, reason = budget.can_call_model(
                    max_input=2000, max_output=512, is_final_writer_or_verifier=False
                )
                if not ok:
                    error = reason or "budget"
                    break
                raw_resp = client.chat(
                    [
                        {
                            "role": "system",
                            "content": (
                                "You are a research sub-agent. Output JSON with "
                                '"actions":[{"action":"local_search"|"web_search"|"read_evidence",'
                                '"query":str|null,"candidate_id":str|null,"reason_code":null}]. '
                                "Prefer local_search then read_evidence. No shell."
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {"topic": topic, "allow_web": case.allow_web}, ensure_ascii=False
                            ),
                        },
                    ],
                    max_tokens=512,
                    temperature=0.0,
                    adapter_id=None,
                )
                budget.record_tokens(
                    input_tokens=raw_resp.usage.input_tokens,
                    output_tokens=raw_resp.usage.output_tokens,
                )
                ledger.add(
                    None,
                    kind="b2_subagent",
                    model=raw_resp.usage.model,
                    input_tokens=raw_resp.usage.input_tokens,
                    output_tokens=raw_resp.usage.output_tokens,
                )
                meter["subagent_llm_calls"] += 1
                policy_attempts.append({"raw": raw_resp.content[:500], "ok": True, "role": "subagent"})
                acts = _parse_research_actions(raw_resp.content)
                if not any(a.get("action") == "local_search" for a in acts):
                    acts = [
                        {
                            "action": "local_search",
                            "query": topic,
                            "candidate_id": None,
                            "reason_code": None,
                        }
                    ] + acts
                known_before = {c.get("candidate_id") for c in visible.candidates if c.get("candidate_id")}
                for act in acts:
                    name = act.get("action") or "local_search"
                    if name not in {"local_search", "web_search", "read_evidence"}:
                        continue
                    if name == "web_search" and not case.allow_web:
                        continue
                    action = {
                        "action": name,
                        "query": act.get("query") or topic,
                        "candidate_id": act.get("candidate_id"),
                        "reason_code": act.get("reason_code"),
                    }
                    try:
                        action = validate_action(
                            action,
                            allow_web=case.allow_web,
                            known_candidate_ids={
                                c.get("candidate_id") for c in visible.candidates if c.get("candidate_id")
                            },
                        )
                    except Exception:
                        if name != "local_search":
                            continue
                        action = {
                            "action": "local_search",
                            "query": topic,
                            "candidate_id": None,
                            "reason_code": None,
                        }
                    actions.append(action)
                    obs, added, tool_err = _execute_action(
                        root=root,
                        case=case,
                        action=action,
                        visible=visible,
                        cand_store=cand_store,
                        step=step,
                        budget=budget,
                    )
                    step += 1
                    meter["tool_calls"] += 1
                    if tool_err:
                        error = tool_err
                        break
                    _append_recent(visible, step, action, added)
                if error:
                    break
                # Auto-read top new candidate if no read requested
                if not any(a.get("action") == "read_evidence" for a in acts):
                    new_ids = [
                        c.get("candidate_id")
                        for c in visible.candidates
                        if c.get("candidate_id") and c.get("candidate_id") not in known_before
                    ]
                    if new_ids:
                        read = {
                            "action": "read_evidence",
                            "query": None,
                            "candidate_id": new_ids[0],
                            "reason_code": None,
                        }
                        actions.append(read)
                        obs, added, tool_err = _execute_action(
                            root=root,
                            case=case,
                            action=read,
                            visible=visible,
                            cand_store=cand_store,
                            step=step,
                            budget=budget,
                        )
                        step += 1
                        meter["tool_calls"] += 1
                        if tool_err:
                            error = tool_err
                            break
                        _append_recent(visible, step, read, added)

            if not error:
                ok, reason = budget.can_call_model(
                    max_input=2000, max_output=128, is_final_writer_or_verifier=False
                )
                if ok:
                    syn = client.chat(
                        [
                            {
                                "role": "system",
                                "content": 'Synthesize research findings into a short JSON note {"ok": true}.',
                            },
                            {
                                "role": "user",
                                "content": json.dumps(
                                    {
                                        "question": case.question,
                                        "n_evidence": len(visible.evidence_cards or []),
                                    },
                                    ensure_ascii=False,
                                ),
                            },
                        ],
                        max_tokens=128,
                        temperature=0.0,
                        adapter_id=None,
                    )
                    budget.record_tokens(
                        input_tokens=syn.usage.input_tokens, output_tokens=syn.usage.output_tokens
                    )
                    ledger.add(
                        None,
                        kind="b2_orchestrator",
                        model=syn.usage.model,
                        input_tokens=syn.usage.input_tokens,
                        output_tokens=syn.usage.output_tokens,
                    )
                    meter["orchestrator_llm_calls"] += 1
                else:
                    error = reason or "budget"
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    status, claims, verification, unresolved, answer, error = _writer_verifier(
        client=client,
        case=case,
        evidence_cards=visible.evidence_cards or [],
        ledger=ledger,
        error=error,
    )
    meter["total_llm_calls"] = meter["orchestrator_llm_calls"] + meter["subagent_llm_calls"]
    return _base_result(
        case=case,
        system="b2",
        run_id=run_id,
        policy_adapter_id=None,
        t0=t0,
        budget=budget,
        ledger=ledger,
        status=status,
        answer=answer,
        claims=claims,
        verification=verification,
        unresolved=unresolved,
        evidence_cards=visible.evidence_cards or [],
        actions=actions,
        terminal=None,
        policy_attempts=policy_attempts,
        error=error,
        extra={
            "memory_mode": "deep_research_subagents",
            "adapter": "deep_research_adapter",
            "upstream": {
                "package": "deepagents==0.7.32",
                "commit": "e85c6b98087861512d2c5240305e16cfac68a746",
            },
            "b2_meter": meter,
        },
    )


def run_system_case(
    *,
    root: Path,
    case: TaskCase,
    client,
    system: str,
) -> dict[str, Any]:
    s = system.lower().strip()
    if s == "b0":
        return run_b0_case(root=root, case=case, client=client)
    if s == "b1":
        return run_b1_case(root=root, case=case, client=client)
    if s == "b2":
        return run_b2_case(root=root, case=case, client=client)
    if s in {"e0", "e1", "e2", "e1_final", "e2_final", "base", "sft_e1", "dpo_e2"}:
        adapter = system_adapter(s)
        # Normalize reported system id to short form for aggregation.
        report = {"e1_final": "e1", "e2_final": "e2", "sft_e1": "e1", "dpo_e2": "e2", "base": "e0"}.get(
            s, s
        )
        out = run_case(
            root=root,
            case=case,
            client=client,
            system=report,
            policy_adapter_id=adapter,
            policy_temperature=0.0,
        )
        out["memory_mode"] = "evidence_ledger_packed"
        return out
    raise ValueError(f"unknown system: {system}")

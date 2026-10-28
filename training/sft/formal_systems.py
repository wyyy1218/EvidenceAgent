#!/usr/bin/env python3
"""S42 formal-system runners on the same TaskCase corpus (no DB).

B0/B1/B2 share Writer/Verifier and tool execution with E0 via dev_harness
helpers; controllers differ (static / rolling ReAct / multi-phase adapter).
"""
from __future__ import annotations

import json
import time
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

_B1_SYSTEM = (
    "你是资料研究任务的下一步动作控制器（ReAct 滚动历史模式）。"
    "只能依据问题、近期动作与观察、候选来源和剩余预算选择下一步。"
    "输出一个 JSON 对象，字段仅有 action, query, candidate_id, reason_code。"
    "搜索摘要只是候选，不是已读原文。缺少证据时继续查找/阅读或 abstain，"
    "不用参数记忆补成确定事实。finish 表示根据现有已读来源生成答案。"
)

_B2_ORCH = (
    "You plan research subtasks for a controlled evidence agent. "
    'Output JSON: {"subtasks": ["..."]}. Max 3 subtasks. Do not invent facts.'
)
_B2_SUB = (
    "You are a research sub-agent. Output JSON with "
    '"actions":[{"action":"local_search"|"web_search"|"read_evidence",'
    '"query":str|null,"candidate_id":str|null}]. '
    "Prefer local_search then read_evidence. No shell."
)


def _empty_visible(case: TaskCase, budget: BudgetState) -> VisibleState:
    return VisibleState(
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


def _finalize(
    *,
    case: TaskCase,
    client,
    system: str,
    policy_adapter_id: str | None,
    visible: VisibleState,
    actions: list[dict[str, Any]],
    budget: BudgetState,
    ledger: MemoryUsageLedger,
    run_id: str,
    t0: float,
    error: str | None,
    terminal: str | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
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

    out = {
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
    }
    if extra:
        out.update(extra)
    return out


def run_case_b0(*, root, case: TaskCase, client, top_k: int = 6) -> dict[str, Any]:
    """Static hybrid-style: one local_search → read Top-k → Writer/Verifier."""
    t0 = time.perf_counter()
    budget = BudgetState(cfg=BudgetConfig())
    ledger = MemoryUsageLedger()
    run_id = f"formal_b0_{case.task_id}_{int(t0 * 1000) % 10_000_000}"
    visible = _empty_visible(case, budget)
    cand_store: dict[str, dict[str, Any]] = {}
    actions: list[dict[str, Any]] = []
    error: str | None = None
    terminal: str | None = None

    search = {
        "action": "local_search",
        "query": case.question,
        "candidate_id": None,
        "reason_code": None,
    }
    actions.append(search)
    obs, added, tool_err = _execute_action(
        root=root,
        case=case,
        action=search,
        visible=visible,
        cand_store=cand_store,
        step=0,
        budget=budget,
    )
    _append_recent(visible, 0, search, added)
    if tool_err:
        error = tool_err
    else:
        for i, cand in enumerate(list(visible.candidates)[:top_k]):
            cid = cand.get("candidate_id")
            if not cid:
                continue
            read = {
                "action": "read_evidence",
                "query": None,
                "candidate_id": cid,
                "reason_code": None,
            }
            actions.append(read)
            obs, added, tool_err = _execute_action(
                root=root,
                case=case,
                action=read,
                visible=visible,
                cand_store=cand_store,
                step=i + 1,
                budget=budget,
            )
            _append_recent(visible, i + 1, read, added)
            if tool_err:
                error = tool_err
                break
        if not error:
            terminal = "finish"
            actions.append(
                {
                    "action": "finish",
                    "query": None,
                    "candidate_id": None,
                    "reason_code": None,
                }
            )

    return _finalize(
        case=case,
        client=client,
        system="b0",
        policy_adapter_id=None,
        visible=visible,
        actions=actions,
        budget=budget,
        ledger=ledger,
        run_id=run_id,
        t0=t0,
        error=error,
        terminal=terminal,
        extra={"memory_mode": "static_top6"},
    )


def _b1_policy(
    client,
    messages,
    *,
    allow_web,
    known,
    budget,
    ledger,
    run_id,
    temperature: float = 0.0,
    seed: int | None = None,
) -> tuple[dict | None, str | None]:
    msgs = list(messages)
    for attempt in range(2):
        ok, reason = budget.can_call_model(
            max_input=1800, max_output=256, is_final_writer_or_verifier=False
        )
        if not ok:
            return None, reason or "budget"
        kwargs: dict[str, Any] = {
            "max_tokens": 256,
            "temperature": float(temperature),
            "adapter_id": None,
        }
        if seed is not None:
            kwargs["seed"] = int(seed) + attempt
        resp = client.chat(msgs, **kwargs)
        budget.record_tokens(input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens)
        ledger.add(
            None,
            kind="policy",
            model=resp.usage.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            meta={"system": "b1", "attempt": attempt, "run_id": run_id},
        )
        raw = resp.content
        try:
            obj = parse_json_object(raw)
            action = validate_action(obj, allow_web=allow_web, known_candidate_ids=known)
            return action, None
        except (ValueError, ActionValidationError, json.JSONDecodeError) as exc:
            if attempt >= 1:
                return None, "failed_policy"
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
    return None, "failed_policy"


def run_case_b1(
    *,
    root,
    case: TaskCase,
    client,
    max_steps: int | None = None,
    budget_cfg: BudgetConfig | None = None,
    policy_temperature: float = 0.0,
    policy_seed: int | None = None,
    web_mode: str = "replay",
) -> dict[str, Any]:
    """Rolling-history ReAct; no E0 evidence-card packing into policy."""
    t0 = time.perf_counter()
    budget = BudgetState(cfg=budget_cfg or BudgetConfig())
    if max_steps is None:
        max_steps = max(0, int(budget.cfg.tool_calls) - int(budget.tool_calls_used)) + 2
    ledger = MemoryUsageLedger()
    run_id = f"formal_b1_{case.task_id}_{int(t0 * 1000) % 10_000_000}"
    visible = _empty_visible(case, budget)
    cand_store: dict[str, dict[str, Any]] = {}
    actions: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    source_log: list[dict[str, Any]] = []
    error: str | None = None
    terminal: str | None = None
    allow_web = bool(case.allow_web or web_mode == "live")
    reqs = [
        {"requirement_id": r.get("requirement_id"), "text": r.get("text")}
        for r in (case.task.get("requirements") or [])
    ]

    for step in range(max_steps):
        visible.budget = budget.visible_budget()
        known = {c.get("candidate_id") for c in visible.candidates if c.get("candidate_id")}
        payload = {
            "question": case.question,
            "requirements": reqs,
            "allow_web": allow_web,
            "budget": budget.visible_budget(),
            "candidates": visible.candidates[-16:],
            "source_log_min": source_log[-8:],
            "recent_history": history[-12:],
            "note": "B1 rolling history; no persistent evidence-card packing.",
        }
        messages = [
            {"role": "system", "content": _B1_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        step_seed = None if policy_seed is None else int(policy_seed) + step
        action, err = _b1_policy(
            client,
            messages,
            allow_web=allow_web,
            known=known,
            budget=budget,
            ledger=ledger,
            run_id=run_id,
            temperature=float(policy_temperature),
            seed=step_seed,
        )
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
            web_mode=web_mode,
            run_id=run_id,
        )
        if tool_err:
            error = tool_err
            break
        _append_recent(visible, step, action, added)
        history.append({"step": step, "action": action, "observation": obs})
        if action["action"] == "read_evidence" and obs.get("status") == "ok":
            source_log.append(
                {
                    "candidate_id": action.get("candidate_id"),
                    "evidence_id": obs.get("evidence_id"),
                    "chars": obs.get("chars"),
                }
            )

    return _finalize(
        case=case,
        client=client,
        system="b1",
        policy_adapter_id=None,
        visible=visible,
        actions=actions,
        budget=budget,
        ledger=ledger,
        run_id=run_id,
        t0=t0,
        error=error,
        terminal=terminal,
        extra={
            "memory_mode": "rolling_history",
            "temperature": float(policy_temperature),
            "seed": policy_seed,
            "web_mode": web_mode,
        },
    )


def _chat_json(client, messages, *, budget, ledger, kind: str) -> dict[str, Any] | None:
    ok, reason = budget.can_call_model(
        max_input=1800, max_output=256, is_final_writer_or_verifier=False
    )
    if not ok:
        raise RuntimeError(reason or "budget")
    resp = client.chat(messages, max_tokens=256, temperature=0.0, adapter_id=None)
    budget.record_tokens(input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens)
    ledger.add(
        None,
        kind=kind,
        model=resp.usage.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )
    try:
        return parse_json_object(resp.content)
    except Exception:  # noqa: BLE001
        return None


def run_case_b2(*, root, case: TaskCase, client) -> dict[str, Any]:
    """Multi-phase adapter loop (orchestrator → subagents → tools); never aliases E0."""
    t0 = time.perf_counter()
    budget = BudgetState(cfg=BudgetConfig())
    ledger = MemoryUsageLedger()
    run_id = f"formal_b2_{case.task_id}_{int(t0 * 1000) % 10_000_000}"
    visible = _empty_visible(case, budget)
    cand_store: dict[str, dict[str, Any]] = {}
    actions: list[dict[str, Any]] = []
    error: str | None = None
    terminal: str | None = None
    b2_meter = {"subtask_count": 0, "coordination_steps": 0, "backend": "adapter_loop_harness"}

    try:
        plan = _chat_json(
            client,
            [
                {"role": "system", "content": _B2_ORCH},
                {"role": "user", "content": case.question},
            ],
            budget=budget,
            ledger=ledger,
            kind="b2_orchestrator",
        )
        subtasks = []
        if isinstance(plan, dict):
            raw = plan.get("subtasks") or []
            if isinstance(raw, list):
                subtasks = [str(x) for x in raw if str(x).strip()][:3]
        if not subtasks:
            subtasks = [case.question]
        b2_meter["subtask_count"] = len(subtasks)

        step = 0
        for topic in subtasks:
            b2_meter["coordination_steps"] += 1
            sub = _chat_json(
                client,
                [
                    {"role": "system", "content": _B2_SUB},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"topic": topic, "allow_web": case.allow_web}, ensure_ascii=False
                        ),
                    },
                ],
                budget=budget,
                ledger=ledger,
                kind="b2_subagent",
            )
            planned = []
            if isinstance(sub, dict) and isinstance(sub.get("actions"), list):
                planned = [a for a in sub["actions"] if isinstance(a, dict)]
            if not any((a.get("action") == "local_search") for a in planned):
                planned = [
                    {
                        "action": "local_search",
                        "query": topic,
                        "candidate_id": None,
                        "reason_code": None,
                    }
                ] + planned
            for raw_act in planned:
                name = raw_act.get("action") or "local_search"
                if name not in {"local_search", "web_search", "read_evidence"}:
                    continue
                if name == "web_search" and not case.allow_web:
                    continue
                action = {
                    "action": name,
                    "query": raw_act.get("query") or topic,
                    "candidate_id": raw_act.get("candidate_id"),
                    "reason_code": raw_act.get("reason_code"),
                }
                try:
                    known = {
                        c.get("candidate_id") for c in visible.candidates if c.get("candidate_id")
                    }
                    action = validate_action(
                        action, allow_web=case.allow_web, known_candidate_ids=known
                    )
                except Exception:  # noqa: BLE001
                    if name == "read_evidence" and visible.candidates:
                        action = {
                            "action": "read_evidence",
                            "query": None,
                            "candidate_id": visible.candidates[0]["candidate_id"],
                            "reason_code": None,
                        }
                    elif name != "local_search":
                        continue
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
                _append_recent(visible, step, action, added)
                step += 1
                if tool_err:
                    error = tool_err
                    break
            if error:
                break
        if not error:
            terminal = "finish"
            actions.append(
                {
                    "action": "finish",
                    "query": None,
                    "candidate_id": None,
                    "reason_code": None,
                }
            )
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    return _finalize(
        case=case,
        client=client,
        system="b2",
        policy_adapter_id=None,
        visible=visible,
        actions=actions,
        budget=budget,
        ledger=ledger,
        run_id=run_id,
        t0=t0,
        error=error,
        terminal=terminal,
        extra={"memory_mode": "deep_research_subagents", "b2_meter": b2_meter, "adapter": "harness"},
    )


def run_formal_case(
    *,
    root,
    case: TaskCase,
    client,
    system: str,
    policy_adapter_id: str | None,
    budget_cfg: BudgetConfig | None = None,
    policy_temperature: float = 0.0,
    policy_seed: int | None = None,
    ablation_variant: str | None = None,
    web_mode: str = "replay",
) -> dict[str, Any]:
    """Dispatch formal systems. Ablation/budget/seed apply to E0/E1/E2 and B1.

    B0/B2 keep fixed internal loops for the main experiment; budget override is
    applied when provided so S44 can run B1 with b4/b12.
    """
    s = system.lower()
    if s in {"b0"}:
        # Main experiment / ablations that need static retrieval stay on default budget.
        out = run_case_b0(root=root, case=case, client=client)
        out.setdefault("tool_budget", 8)
        out.setdefault("temperature", 0.0)
        out.setdefault("seed", None)
        out.setdefault("ablation_variant", ablation_variant)
        out.setdefault("web_mode", web_mode)
        return out
    if s in {"b1"}:
        return run_case_b1(
            root=root,
            case=case,
            client=client,
            budget_cfg=budget_cfg,
            policy_temperature=policy_temperature,
            policy_seed=policy_seed,
            web_mode=web_mode,
        )
    if s in {"b2"}:
        out = run_case_b2(root=root, case=case, client=client)
        out.setdefault("tool_budget", 8)
        out.setdefault("temperature", 0.0)
        out.setdefault("seed", None)
        out.setdefault("ablation_variant", ablation_variant)
        out.setdefault("web_mode", web_mode)
        return out
    return run_case(
        root=root,
        case=case,
        client=client,
        system=system,
        policy_adapter_id=policy_adapter_id,
        budget_cfg=budget_cfg,
        policy_temperature=policy_temperature,
        policy_seed=policy_seed,
        ablation_variant=ablation_variant,
        web_mode=web_mode,
    )

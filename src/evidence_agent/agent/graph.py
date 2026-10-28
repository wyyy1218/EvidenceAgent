"""LangGraph-controlled research loop: load→policy→dispatch→update→write→verify→finalize."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypedDict

from evidence_agent.agent.actions import normalize_query, validate_action, ActionValidationError
from evidence_agent.agent.answer_pipeline import produce_answer
from evidence_agent.agent.budget import BudgetConfig, BudgetState
from evidence_agent.agent.llm import LLMClient, MockLLMClient
from evidence_agent.agent.packer import pack_visible_state
from evidence_agent.agent.policy import run_policy
from evidence_agent.agent.requirements import extract_requirements
from evidence_agent.agent.result import RunResult
from evidence_agent.agent.state import VisibleState
from evidence_agent.agent.usage_ledger import UsageLedger
from evidence_agent.evidence.ledger import register_from_read
from evidence_agent.storage import repositories as repo
from evidence_agent.tools.candidates import CandidateRegistry, GLOBAL_CANDIDATES
from evidence_agent.tools.dispatch import dispatch_tool
from evidence_agent.tools.types import ToolStatus


class GraphState(TypedDict, total=False):
    run_id: str
    project_id: str
    question: str
    allow_web: bool
    web_mode: str
    status: str
    step_no: int
    next_node: str
    result: dict[str, Any]
    error_code: str | None


@dataclass
class RunContext:
    root: Path
    conn: Any
    client: LLMClient
    budget: BudgetState
    usage: UsageLedger
    registry: CandidateRegistry
    retriever: Any = None
    authorized_versions: list[str] = field(default_factory=list)
    visible: VisibleState | None = None
    evidence_cards: list[dict[str, Any]] = field(default_factory=list)
    query_cache: dict[str, Any] = field(default_factory=dict)
    last_action: dict[str, Any] | None = None
    cancel_check: Any = None  # callable -> bool
    policy_adapter_id: str | None = None  # E1 policy route; Writer/Verifier stay base
    paid_call_state: str = "not_started"  # not_started|completed|completion_unknown


def _known_candidates(ctx: RunContext, run_id: str) -> set[str]:
    assert ctx.visible is not None
    ids = {c.get("candidate_id") for c in ctx.visible.candidates if c.get("candidate_id")}
    # Registry may hold candidates not yet copied into visible state
    try:
        bucket = ctx.registry._by_run.get(run_id) or {}  # type: ignore[attr-defined]
        ids |= set(bucket.keys())
    except Exception:
        pass
    return {i for i in ids if i}


def node_load(ctx: RunContext, state: GraphState) -> GraphState:
    reqs = [r.to_dict() for r in extract_requirements(state["question"])]
    versions = repo.list_project_version_ids(ctx.conn, state["project_id"])
    ctx.authorized_versions = versions
    ctx.visible = VisibleState(
        question=state["question"],
        requirements=reqs,
        project_id=state["project_id"],
        snapshot_set_id=",".join(versions[:8]),
        budget=ctx.budget.visible_budget(),
    )
    ctx.usage = UsageLedger(run_id=state["run_id"])
    state["step_no"] = state.get("step_no") or 0
    state["next_node"] = "policy"
    state["status"] = "running"
    return state


def node_policy(ctx: RunContext, state: GraphState) -> GraphState:
    if ctx.cancel_check and ctx.cancel_check():
        state["status"] = "cancelled"
        state["next_node"] = "finalize"
        return state
    assert ctx.visible is not None
    ctx.visible.budget = ctx.budget.visible_budget()
    packed = pack_visible_state(ctx.visible)
    action, err, attempts = run_policy(
        ctx.client,
        packed,
        allow_web=bool(state.get("allow_web")),
        known_candidate_ids=_known_candidates(ctx, state["run_id"]),
        budget=ctx.budget,
        usage_ledger=ctx.usage,
        conn=ctx.conn,
        run_id=state["run_id"],
        policy_adapter_id=ctx.policy_adapter_id,
    )
    if err == "failed_policy":
        state["status"] = "failed"
        state["error_code"] = "failed_policy"
        state["result"] = {"attempts": attempts, "note": "failed_policy"}
        state["next_node"] = "finalize"
        return state
    if err:
        # Budget/time → safe exit via write if evidence else timeout/partial
        state["error_code"] = err
        state["next_node"] = "write" if ctx.evidence_cards else "finalize"
        if not ctx.evidence_cards:
            state["status"] = "timeout" if err == "timeout" else "insufficient_evidence"
        return state
    ctx.last_action = action
    state["next_node"] = "dispatch"
    return state


def node_dispatch(ctx: RunContext, state: GraphState) -> GraphState:
    action = ctx.last_action
    assert action is not None
    step = int(state.get("step_no") or 0) + 1
    state["step_no"] = step

    if action["action"] in {"finish", "abstain"}:
        # Not external tool calls
        repo.register_action_and_result(
            ctx.conn,
            run_id=state["run_id"],
            step_no=step,
            action=action,
            result_status="ok",
            result={"note": action["action"]},
            state_hash=ctx.visible.state_hash() if ctx.visible else None,
            commit=False,
        )
        state["next_node"] = "write"
        return state

    live = action["action"] == "web_search" and state.get("web_mode") == "live"
    ok, reason = ctx.budget.can_call_tool(live_search=live)
    if not ok:
        ctx.budget.stop(reason or "budget")
        state["error_code"] = reason
        state["next_node"] = "write" if ctx.evidence_cards else "finalize"
        if not ctx.evidence_cards:
            state["status"] = "insufficient_evidence"
        return state

    # Cache: normalized query + unchanged version set
    cache_hit = False
    tool_result = None
    if action["action"] in {"local_search", "web_search"}:
        key = normalize_query(action["query"] or "") + "|" + ",".join(ctx.authorized_versions)
        if key in ctx.query_cache:
            tool_result = ctx.query_cache[key]
            cache_hit = True

    ctx.paid_call_state = "not_started"
    if tool_result is None:
        ctx.paid_call_state = "completion_unknown"  # until success committed
        tool_result = dispatch_tool(
            action,
            root=ctx.root,
            project_id=state["project_id"],
            run_id=state["run_id"],
            allow_web=bool(state.get("allow_web")),
            web_mode=str(state.get("web_mode") or "off"),
            authorized_version_ids=ctx.authorized_versions,
            registry=ctx.registry,
            retriever=ctx.retriever,
        )
        ctx.paid_call_state = "completed"
        if action["action"] in {"local_search", "web_search"} and tool_result.status == ToolStatus.OK:
            key = normalize_query(action["query"] or "") + "|" + ",".join(ctx.authorized_versions)
            ctx.query_cache[key] = tool_result

    # Logical tool always counted (even cache hit)
    ctx.budget.record_tool(live_search=live and not cache_hit)
    ctx.usage.add(
        ctx.conn,
        kind=action["action"],
        step_id=str(step),
        logical_tool_call=True,
        physical_request=not cache_hit,
        cache_hit=cache_hit,
        billing_status=getattr(tool_result, "billing_status", None) or "n/a",
        credits=float((tool_result.usage or {}).get("credits") or 0),
        meta={"cache_hit": cache_hit, "status": tool_result.status.value},
    )

    # Persist action+result
    repo.register_action_and_result(
        ctx.conn,
        run_id=state["run_id"],
        step_no=step,
        action=action,
        result_status=tool_result.status.value,
        result=tool_result.to_dict(),
        state_hash=ctx.visible.state_hash() if ctx.visible else None,
        commit=False,
    )
    repo.add_audit(
        ctx.conn,
        state["run_id"],
        "step",
        {
            "step_no": step,
            "action": action,
            "tool_status": tool_result.status.value,
            "cache_hit": cache_hit,
            "paid_call_state": ctx.paid_call_state,
        },
    )

    state["_tool_result"] = tool_result.to_dict()
    state["next_node"] = "update"
    return state


def node_update(ctx: RunContext, state: GraphState) -> GraphState:
    assert ctx.visible is not None
    action = ctx.last_action or {}
    tr = state.pop("_tool_result", None) or {}
    added = False

    if action.get("action") in {"local_search", "web_search"} and tr.get("status") == "ok":
        cands = (tr.get("data") or {}).get("candidates") or []
        # Merge candidates
        existing = {c.get("candidate_id") for c in ctx.visible.candidates}
        for c in cands:
            if c.get("candidate_id") not in existing:
                ctx.visible.candidates.append(c)
                added = True  # new candidates, not evidence yet

    if action.get("action") == "read_evidence" and tr.get("status") == "ok":
        from evidence_agent.tools.types import ToolResult, ToolStatus as TS

        tool_result = ToolResult(
            tool="read_evidence",
            status=TS.OK,
            data=tr.get("data") or {},
            billing_status=tr.get("billing_status"),
            meta=tr.get("meta") or {},
        )
        try:
            rec = register_from_read(
                ctx.conn,
                root=ctx.root,
                run_id=state["run_id"],
                project_id=state["project_id"],
                tool_result=tool_result,
                authorized_version_ids=ctx.authorized_versions,
            )
            ctx.evidence_cards.append(rec.to_dict())
            ctx.visible.evidence_cards = list(ctx.evidence_cards)
            added = True
        except Exception as exc:  # noqa: BLE001
            ctx.visible.source_failures.append({"error": str(exc), "action": action})

    if added:
        ctx.visible.no_new_evidence_streak = 0
    else:
        ctx.visible.no_new_evidence_streak += 1
        # Mark streak — do not auto-abstain
        ctx.visible.open_gaps = [
            {
                "note": "no_new_evidence",
                "streak": ctx.visible.no_new_evidence_streak,
                "suggestion_only": True,
            }
        ]

    ctx.visible.recent_actions.append(
        {
            "step_no": state.get("step_no"),
            "action": action.get("action"),
            "status": tr.get("status"),
            "added_evidence": added and action.get("action") == "read_evidence",
        }
    )
    # Keep recent window small
    ctx.visible.recent_actions = ctx.visible.recent_actions[-8:]
    state["next_node"] = "policy"
    return state


def node_write(ctx: RunContext, state: GraphState) -> GraphState:
    # Shared Writer/Verifier path
    if ctx.cancel_check and ctx.cancel_check():
        state["status"] = "cancelled"
        state["next_node"] = "finalize"
        return state

    ok, reason = ctx.budget.can_call_model(
        max_input=2000, max_output=768, is_final_writer_or_verifier=True
    )
    if not ok and not ctx.evidence_cards:
        state["status"] = "timeout" if reason == "timeout" else "insufficient_evidence"
        state["error_code"] = reason
        state["next_node"] = "finalize"
        return state

    result = produce_answer(
        ctx.client,
        conn=ctx.conn,
        root=ctx.root,
        run_id=state["run_id"],
        project_id=state["project_id"],
        question=state["question"],
        evidence_cards=ctx.evidence_cards,
        authorized_version_ids=ctx.authorized_versions,
        usage_acc={
            "tool_calls": ctx.usage.logical_tool_calls,
            "input_tokens": ctx.usage.input_tokens,
            "output_tokens": ctx.usage.output_tokens,
        },
    )
    # Meter writer/verifier tokens already inside produce_answer via client;
    # fold usage
    ctx.budget.record_tokens(
        input_tokens=result.usage.get("input_tokens", 0) - ctx.usage.input_tokens,
        output_tokens=result.usage.get("output_tokens", 0) - ctx.usage.output_tokens,
    )
    state["result"] = result.to_dict()
    state["status"] = result.status
    if state.get("error_code") in {"timeout", "output_reserve_blocked", "tool_budget_exhausted"}:
        if result.status == "answered" and ctx.evidence_cards:
            state["status"] = "partial"
        elif not ctx.evidence_cards:
            state["status"] = "timeout" if state["error_code"] == "timeout" else "insufficient_evidence"
    state["next_node"] = "finalize"
    return state


def node_finalize(ctx: RunContext, state: GraphState) -> GraphState:
    status = state.get("status") or "failed"
    result = state.get("result") or {
        "status": status,
        "answer": None,
        "claims": [],
        "unresolved": [],
        "usage": ctx.usage.summary(),
    }
    result["usage"] = {**(result.get("usage") or {}), **ctx.usage.summary(), **ctx.budget.snapshot()}
    result["status"] = status
    repo.finalize_run(
        ctx.conn,
        state["run_id"],
        status=status,
        failure_reason=state.get("error_code"),
        error_code=state.get("error_code"),
        result=result,
    )
    try:
        from evidence_agent.storage.backup import dump_run_trajectory

        traj = dump_run_trajectory(ctx.conn, ctx.root, state["run_id"])
        result["trajectory_path"] = str(traj)
    except Exception as exc:  # noqa: BLE001
        result["trajectory_error"] = str(exc)
    state["next_node"] = "end"
    state["result"] = result
    return state


def run_agent_loop(
    *,
    root: Path,
    conn,
    run_id: str,
    project_id: str,
    question: str,
    client: LLMClient,
    allow_web: bool = False,
    web_mode: str = "off",
    budget: BudgetState | None = None,
    registry: CandidateRegistry | None = None,
    retriever: Any = None,
    cancel_check=None,
    max_steps: int = 24,
    policy_adapter_id: str | None = None,
) -> dict[str, Any]:
    """Execute controlled loop. Budget — not graph recursion — is the hard stop."""
    ctx = RunContext(
        root=root,
        conn=conn,
        client=client,
        budget=budget or BudgetState(),
        usage=UsageLedger(run_id=run_id),
        registry=registry or CandidateRegistry(),
        retriever=retriever,
        cancel_check=cancel_check,
        policy_adapter_id=policy_adapter_id,
    )
    state: GraphState = {
        "run_id": run_id,
        "project_id": project_id,
        "question": question,
        "allow_web": allow_web,
        "web_mode": web_mode,
        "status": "running",
        "step_no": 0,
        "next_node": "load",
    }
    state = node_load(ctx, state)

    # Prefer LangGraph wiring for structure; execute via explicit dispatch table
    # so budget remains authoritative (recursion_limit is NOT the budget).
    nodes = {
        "policy": node_policy,
        "dispatch": node_dispatch,
        "update": node_update,
        "write": node_write,
        "finalize": node_finalize,
    }

    try:
        from langgraph.graph import END, StateGraph

        g = StateGraph(dict)
        g.add_node("policy", lambda s: s)
        g.add_node("dispatch", lambda s: s)
        g.add_node("update", lambda s: s)
        g.add_node("write", lambda s: s)
        g.add_node("finalize", lambda s: s)
        g.set_entry_point("policy")
        # Graph structure registered for inspection; we still drive execution below.
        _ = g  # structure available for docs/probes
    except Exception:
        pass

    steps = 0
    while state.get("next_node") not in {None, "end"} and steps < max_steps:
        steps += 1
        if ctx.cancel_check and ctx.cancel_check() and state["next_node"] not in {"finalize", "write"}:
            state["status"] = "cancelled"
            state["next_node"] = "finalize"
        nxt = state["next_node"]
        if nxt == "end":
            break
        fn = nodes.get(nxt)
        if fn is None:
            break
        state = fn(ctx, state)
        if ctx.budget.remaining_wall() <= 0 and state.get("next_node") == "policy":
            state["error_code"] = "timeout"
            state["next_node"] = "write" if ctx.evidence_cards else "finalize"
            if not ctx.evidence_cards:
                state["status"] = "timeout"

    if state.get("next_node") != "end":
        state = node_finalize(ctx, state)
    return state.get("result") or {"status": state.get("status"), "run_id": run_id}


def build_langgraph_app():
    """Export a compiled LangGraph for inspection / future checkpointing."""
    from langgraph.graph import END, StateGraph

    def _passthrough(s: dict) -> dict:
        return s

    g = StateGraph(dict)
    for name in ("load", "policy", "dispatch", "update", "write", "verify", "finalize"):
        g.add_node(name, _passthrough)
    g.set_entry_point("load")
    g.add_edge("load", "policy")
    g.add_conditional_edges(
        "policy",
        lambda s: s.get("next_node", "dispatch"),
        {
            "dispatch": "dispatch",
            "write": "write",
            "finalize": "finalize",
        },
    )
    g.add_edge("dispatch", "update")
    g.add_conditional_edges(
        "update",
        lambda s: s.get("next_node", "policy"),
        {"policy": "policy", "write": "write", "finalize": "finalize"},
    )
    g.add_edge("write", "verify")
    g.add_edge("verify", "finalize")
    g.add_edge("finalize", END)
    return g.compile()

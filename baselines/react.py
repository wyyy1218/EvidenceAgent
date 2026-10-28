"""B1: untrained base + rolling-history ReAct (no E0 evidence-card packing)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from evidence_agent.agent.actions import ActionValidationError, validate_action
from evidence_agent.agent.answer_pipeline import produce_answer
from evidence_agent.agent.budget import BudgetConfig, BudgetState
from evidence_agent.agent.llm import HttpLLMClient, LLMClient, MockLLMClient, parse_json_object
from evidence_agent.agent.requirements import extract_requirements
from evidence_agent.agent.usage_ledger import UsageLedger
from evidence_agent.evidence.ledger import register_from_read
from evidence_agent.retrieval.dense import HashEmbedder
from evidence_agent.retrieval.pipeline import HybridRetriever
from evidence_agent.retrieval.rerank import LexicalReranker
from evidence_agent.storage.db import connect, work_root
from evidence_agent.storage import repositories as repo
from evidence_agent.storage.migrate import ensure_db
from evidence_agent.tools.candidates import CandidateRegistry
from evidence_agent.tools.dispatch import dispatch_tool
from evidence_agent.tools.types import ToolResult, ToolStatus

_REACT_SYSTEM = (
    "你是资料研究任务的下一步动作控制器（ReAct 滚动历史模式）。"
    "只能依据问题、近期动作与观察、候选来源和剩余预算选择下一步。"
    "输出一个 JSON 对象，字段仅有 action, query, candidate_id, reason_code。"
    "搜索摘要只是候选，不是已读原文。缺少证据时继续查找/阅读或 abstain，"
    "不用参数记忆补成确定事实。finish 表示根据现有已读来源生成答案。"
)

_HISTORY_WINDOW = 12


def _known_ids(registry: CandidateRegistry, run_id: str, candidates: list[dict]) -> set[str]:
    ids = {c.get("candidate_id") for c in candidates if c.get("candidate_id")}
    try:
        bucket = registry._by_run.get(run_id) or {}  # type: ignore[attr-defined]
        ids |= set(bucket.keys())
    except Exception:
        pass
    return {i for i in ids if i}


def _build_rolling_messages(
    *,
    question: str,
    requirements: list[dict],
    history: list[dict[str, Any]],
    candidates: list[dict],
    source_log: list[dict],
    budget_visible: dict,
    allow_web: bool,
) -> list[dict[str, str]]:
    """Rolling history prompt — deliberately NOT pack_visible_state / evidence cards."""
    payload = {
        "question": question,
        "requirements": requirements,
        "allow_web": allow_web,
        "budget": budget_visible,
        "candidates": candidates[-16:],
        "source_log_min": source_log[-8:],  # locator/snippet only, not packed cards
        "recent_history": history[-_HISTORY_WINDOW:],
        "note": "B1 uses rolling action/observation history; no persistent evidence-card packing.",
    }
    return [
        {"role": "system", "content": _REACT_SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def _policy_once(
    client: LLMClient,
    messages: list[dict[str, str]],
    *,
    allow_web: bool,
    known: set[str],
    budget: BudgetState,
    usage: UsageLedger,
    conn,
    repair: int = 1,
) -> tuple[dict[str, Any] | None, str | None]:
    msgs = list(messages)
    for attempt in range(repair + 1):
        ok, reason = budget.can_call_model(max_input=1800, max_output=256, is_final_writer_or_verifier=False)
        if not ok:
            return None, reason or "budget"
        resp = client.chat(msgs, max_tokens=256, temperature=0.0, adapter_id=None)
        budget.record_tokens(input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens)
        usage.add(
            conn,
            kind="policy",
            model=resp.usage.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            billing_status="n/a",
            meta={"attempt": attempt, "system": "B1", "route": resp.usage.route},
        )
        raw = resp.content
        try:
            obj = parse_json_object(raw)
            action = validate_action(obj, allow_web=allow_web, known_candidate_ids=known)
            return action, None
        except (ValueError, ActionValidationError, json.JSONDecodeError) as exc:
            if attempt >= repair:
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


def _obs_summary(tool_result: ToolResult, action: dict) -> dict[str, Any]:
    data = tool_result.data or {}
    if action["action"] in {"local_search", "web_search"}:
        cands = data.get("candidates") or []
        return {
            "status": tool_result.status.value,
            "n_candidates": len(cands),
            "candidate_ids": [c.get("candidate_id") for c in cands[:8]],
            "titles": [c.get("title") or c.get("display_name") for c in cands[:4]],
        }
    if action["action"] == "read_evidence":
        loc = data.get("locator") or {}
        text = (data.get("text") or data.get("snippet") or "")[:240]
        return {
            "status": tool_result.status.value,
            "locator": loc,
            "snippet": text,
            "evidence_id": data.get("evidence_id"),
        }
    return {"status": tool_result.status.value}


def run_b1(
    *,
    root: Path,
    project_id: str,
    question: str,
    client: LLMClient | None = None,
    conn=None,
    run_id: str | None = None,
    allow_web: bool = False,
    web_mode: str = "off",
    budget: BudgetState | None = None,
    embedder=None,
    reranker=None,
    max_steps: int = 24,
) -> dict[str, Any]:
    """B1 ReAct with rolling history. Keeps min source log + final citations via Writer."""
    close_conn = False
    if conn is None:
        ensure_db(root)
        conn = connect(root)
        close_conn = True
    client = client or HttpLLMClient()
    budget = budget or BudgetState(cfg=BudgetConfig())
    try:
        versions = repo.list_project_version_ids(conn, project_id)
        if run_id is None:
            run_id, _ = repo.create_run(
                conn,
                project_id=project_id,
                question=question,
                allow_web=allow_web,
                budget_profile="standard",
                budget={"tool_calls": budget.cfg.tool_calls},
                idempotency_key=None,
                request_hash=None,
                version_set=versions,
            )

        usage = UsageLedger(run_id=run_id)
        registry = CandidateRegistry()
        retriever = HybridRetriever(
            root,
            project_id,
            embedder=embedder or HashEmbedder(dim=32),
            reranker=reranker or LexicalReranker(),
        )
        reqs = [r.to_dict() for r in extract_requirements(question)]
        history: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        source_log: list[dict[str, Any]] = []
        evidence_cards: list[dict[str, Any]] = []  # for final Writer only, not packed into policy
        status = "running"
        error_code: str | None = None
        result: dict[str, Any] | None = None

        for step in range(1, max_steps + 1):
            if budget.remaining_wall() <= 0:
                error_code = "timeout"
                break
            known = _known_ids(registry, run_id, candidates)
            messages = _build_rolling_messages(
                question=question,
                requirements=reqs,
                history=history,
                candidates=candidates,
                source_log=source_log,
                budget_visible=budget.visible_budget(),
                allow_web=allow_web,
            )
            action, err = _policy_once(
                client,
                messages,
                allow_web=allow_web,
                known=known,
                budget=budget,
                usage=usage,
                conn=conn,
            )
            if err == "failed_policy":
                status = "failed"
                error_code = "failed_policy"
                break
            if err:
                error_code = err
                break
            assert action is not None

            if action["action"] in {"finish", "abstain"}:
                repo.register_action_and_result(
                    conn,
                    run_id=run_id,
                    step_no=step,
                    action=action,
                    result_status="ok",
                    result={"note": action["action"]},
                    state_hash=None,
                    commit=False,
                )
                history.append({"step": step, "action": action, "observation": {"note": action["action"]}})
                break

            live = action["action"] == "web_search" and web_mode == "live"
            ok, reason = budget.can_call_tool(live_search=live)
            if not ok:
                error_code = reason
                break

            tool_result = dispatch_tool(
                action,
                root=root,
                project_id=project_id,
                run_id=run_id,
                allow_web=allow_web,
                web_mode=web_mode,
                authorized_version_ids=versions,
                registry=registry,
                retriever=retriever,
            )
            budget.record_tool(live_search=live)
            usage.add(
                conn,
                kind=action["action"],
                step_id=str(step),
                logical_tool_call=True,
                physical_request=True,
                billing_status=getattr(tool_result, "billing_status", None) or "n/a",
                credits=float((tool_result.usage or {}).get("credits") or 0),
                meta={"system": "B1", "status": tool_result.status.value},
            )
            obs = _obs_summary(tool_result, action)
            repo.register_action_and_result(
                conn,
                run_id=run_id,
                step_no=step,
                action=action,
                result_status=tool_result.status.value,
                result=tool_result.to_dict(),
                state_hash=None,
                commit=False,
            )

            if action["action"] in {"local_search", "web_search"} and tool_result.status == ToolStatus.OK:
                for c in (tool_result.data or {}).get("candidates") or []:
                    if c.get("candidate_id") not in {x.get("candidate_id") for x in candidates}:
                        candidates.append(c)

            if action["action"] == "read_evidence" and tool_result.status == ToolStatus.OK:
                # Min auditable source log for B1 (not E0 packed cards for policy)
                data = tool_result.data or {}
                source_log.append(
                    {
                        "candidate_id": action.get("candidate_id"),
                        "locator": data.get("locator"),
                        "snippet": (data.get("text") or data.get("snippet") or "")[:200],
                    }
                )
                try:
                    rec = register_from_read(
                        conn,
                        root=root,
                        run_id=run_id,
                        project_id=project_id,
                        tool_result=tool_result,
                        authorized_version_ids=versions,
                    )
                    evidence_cards.append(rec.to_dict())
                except Exception as exc:  # noqa: BLE001
                    source_log[-1]["register_error"] = str(exc)

            history.append({"step": step, "action": action, "observation": obs})

        # Final Writer/Verifier for citations
        ok_w, _ = budget.can_call_model(max_input=2000, max_output=768, is_final_writer_or_verifier=True)
        if ok_w or evidence_cards:
            run_result = produce_answer(
                client,
                conn=conn,
                root=root,
                run_id=run_id,
                project_id=project_id,
                question=question,
                evidence_cards=evidence_cards,
                authorized_version_ids=versions,
                usage_acc={
                    "tool_calls": usage.logical_tool_calls,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                },
            )
            result = run_result.to_dict()
            status = run_result.status
            if error_code and evidence_cards and status == "answered":
                status = "partial"
            elif error_code and not evidence_cards:
                status = "timeout" if error_code == "timeout" else "insufficient_evidence"
        else:
            status = "timeout" if error_code == "timeout" else "insufficient_evidence"
            result = {
                "status": status,
                "answer": None,
                "claims": [],
                "unresolved": [error_code or "budget"],
            }

        out = result or {"status": status}
        out["status"] = status
        out["run_id"] = run_id
        out["system"] = "B1"
        out["source_log"] = source_log
        out["usage"] = {**(out.get("usage") or {}), **usage.summary(), **budget.snapshot()}
        if error_code:
            out["error_code"] = error_code
        out["memory_mode"] = "rolling_history"
        repo.finalize_run(conn, run_id, status=status, failure_reason=error_code, error_code=error_code, result=out)
        conn.commit()
        return out
    finally:
        if close_conn:
            conn.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="B1 rolling-history ReAct baseline")
    p.add_argument("--project-id", required=True)
    p.add_argument("--question", required=True)
    p.add_argument("--mock", action="store_true")
    args = p.parse_args(argv)
    root = work_root()
    if args.mock:
        client: LLMClient = MockLLMClient(
            responses=[
                json.dumps(
                    {
                        "action": "abstain",
                        "query": None,
                        "candidate_id": None,
                        "reason_code": "missing_source",
                    }
                ),
                json.dumps({"status_hint": "insufficient_evidence", "claims": [], "unresolved": ["mock"]}),
                json.dumps({"results": []}),
            ]
        )
    else:
        client = HttpLLMClient()
    out = run_b1(root=root, project_id=args.project_id, question=args.question, client=client)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Single-task research worker — claim, run agent loop, heartbeat, cancel (S19/S21)."""
from __future__ import annotations

import argparse
import json
import os
import signal
import time
from pathlib import Path

from evidence_agent.agent.budget import BudgetState, load_budget_from_project
from evidence_agent.agent.graph import run_agent_loop
from evidence_agent.agent.llm import HttpLLMClient, MockLLMClient
from evidence_agent.retrieval.dense import HashEmbedder
from evidence_agent.retrieval.pipeline import HybridRetriever
from evidence_agent.retrieval.rerank import LexicalReranker
from evidence_agent.storage.db import connect, work_root
from evidence_agent.storage.ids import new_id
from evidence_agent.storage.migrate import ensure_db
from evidence_agent.storage import repositories as repo
from evidence_agent.tools.candidates import CandidateRegistry

_STOP = False


def _handle_signal(signum, frame) -> None:  # noqa: ANN001
    global _STOP
    _STOP = True


def write_worker_state(root: Path, *, running: bool, pid: int | None, lease: str | None) -> None:
    path = root / "runs" / "system" / "service_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    services = data.setdefault("services", {})
    services["worker"] = {"running": running, "pid": pid, "lease": lease}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _load_yaml_budget(root: Path) -> BudgetState:
    try:
        import yaml

        cfg_path = Path(__file__).resolve().parents[2] / "configs" / "project.yaml"
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
        return BudgetState(cfg=load_budget_from_project(cfg))
    except Exception:
        return BudgetState()


def _make_client(*, mock: bool = False):
    if mock or os.environ.get("EVIDENCE_AGENT_WORKER_MOCK") == "1":
        # Default scripted controller: search then finish
        return MockLLMClient(
            responses=[
                json.dumps(
                    {
                        "action": "local_search",
                        "query": "evidence",
                        "candidate_id": None,
                        "reason_code": None,
                    }
                ),
                json.dumps(
                    {
                        "action": "finish",
                        "query": None,
                        "candidate_id": None,
                        "reason_code": "evidence_sufficient",
                    }
                ),
                json.dumps({"status_hint": "insufficient_evidence", "claims": [], "unresolved": ["mock"]}),
                json.dumps({"results": []}),
            ]
        )
    return HttpLLMClient()


def process_one(conn, lease_id: str, *, root: Path, mock: bool = False) -> bool:
    """Claim and execute one run. Returns True if work was done."""
    conn.execute("BEGIN")
    try:
        claimed = repo.claim_run(conn, lease_id)
        if not claimed:
            conn.execute("COMMIT")
            return False
        run_id = claimed["id"]
        if claimed.get("cancel_requested"):
            repo.finalize_run(conn, run_id, status="cancelled", failure_reason="cancelled")
            conn.execute("COMMIT")
            return True
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    def cancel_check() -> bool:
        row = repo.get_run(conn, run_id)
        return bool(row and row.get("cancel_requested"))

    project_id = claimed["project_id"]
    question = claimed["question"]
    allow_web = bool(claimed.get("allow_web"))
    client = _make_client(mock=mock)
    budget = _load_yaml_budget(root)
    registry = CandidateRegistry()
    retriever = HybridRetriever(
        root, project_id, embedder=HashEmbedder(dim=32), reranker=LexicalReranker()
    )

    # Resume from last committed step if any
    resume_step = 0
    rows = conn.execute(
        "SELECT MAX(step_no) AS m FROM actions WHERE run_id = ?", (run_id,)
    ).fetchone()
    if rows and rows["m"] is not None:
        resume_step = int(rows["m"])

    try:
        repo.heartbeat_run(conn, run_id, lease_id)
        result = run_agent_loop(
            root=root,
            conn=conn,
            run_id=run_id,
            project_id=project_id,
            question=question,
            client=client,
            allow_web=allow_web,
            web_mode="off" if not allow_web else "replay",
            budget=budget,
            registry=registry,
            retriever=retriever,
            cancel_check=cancel_check,
        )
        conn.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        conn.execute("BEGIN")
        try:
            repo.finalize_run(
                conn,
                run_id,
                status="failed",
                failure_reason=str(exc)[:500],
                error_code="worker_exception",
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return True


def loop(root: Path, *, poll_seconds: float = 1.0, mock: bool = False) -> None:
    ensure_db(root)
    lease_id = new_id("lease")
    write_worker_state(root, running=True, pid=os.getpid(), lease=lease_id)
    try:
        while not _STOP:
            conn = connect(root)
            try:
                did = process_one(conn, lease_id, root=root, mock=mock)
            finally:
                conn.close()
            if not did:
                time.sleep(poll_seconds)
    finally:
        write_worker_state(root, running=False, pid=None, lease=None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EvidenceAgent research worker")
    parser.add_argument("--once", action="store_true", help="process at most one run then exit")
    parser.add_argument("--poll", type=float, default=1.0)
    parser.add_argument("--mock", action="store_true", help="use MockLLMClient")
    args = parser.parse_args(argv)
    root = work_root()
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    if args.once:
        ensure_db(root)
        lease_id = new_id("lease")
        write_worker_state(root, running=True, pid=os.getpid(), lease=lease_id)
        conn = connect(root)
        try:
            process_one(conn, lease_id, root=root, mock=args.mock)
        finally:
            conn.close()
            write_worker_state(root, running=False, pid=None, lease=None)
        return 0
    loop(root, poll_seconds=args.poll, mock=args.mock)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

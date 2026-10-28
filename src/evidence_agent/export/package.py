"""Build downloadable run export: answer.json + citations + readable Markdown."""
from __future__ import annotations

import csv
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from evidence_agent.storage import repositories as repo


def _list_evidence_for_run(conn, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM evidence WHERE run_id = ? ORDER BY created_at ASC",
        (run_id,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "evidence_id": r["id"],
                "source_version_id": r["source_version_id"],
                "quote": r["quote"],
                "page": r["page"],
                "title": r["title"],
                "line_start": r["line_start"],
                "char_start": r["char_start"],
                "char_end": r["char_end"],
                "span": r["span"],
            }
        )
    return out


def _list_actions_for_run(conn, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT step_no, action_json, result_status, result_json FROM actions "
        "WHERE run_id = ? ORDER BY step_no ASC",
        (run_id,),
    ).fetchall()
    timeline = []
    for r in rows:
        action = json.loads(r["action_json"] or "{}")
        timeline.append(
            {
                "step_no": r["step_no"],
                "action": action.get("action"),
                "query": action.get("query"),
                "candidate_id": action.get("candidate_id"),
                "result_status": r["result_status"],
            }
        )
    return timeline


def _markdown_report(
    *,
    run: dict[str, Any],
    result: dict[str, Any] | None,
    citations: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
) -> str:
    lines = [
        f"# 研究结果 — {run['id']}",
        "",
        f"- **状态:** {run['status']}",
        f"- **问题:** {run['question']}",
        "",
        "## 答案",
        "",
        (result or {}).get("answer") or "（无正文）",
        "",
        "## 结论与证据",
        "",
    ]
    for c in (result or {}).get("claims") or []:
        lines.append(f"- **{c.get('claim_id')}:** {c.get('text')}")
        eids = c.get("evidence_ids") or []
        if eids:
            lines.append(f"  - 证据: {', '.join(eids)}")
        scope = c.get("scope")
        if scope:
            lines.append(f"  - 范围: {json.dumps(scope, ensure_ascii=False)}")
    unresolved = (result or {}).get("unresolved") or []
    if unresolved:
        lines.extend(["", "## 未解决", ""])
        for u in unresolved:
            lines.append(f"- {u}")
    lines.extend(["", "## 引用清单", ""])
    for ev in citations:
        loc_bits = []
        if ev.get("page") is not None:
            loc_bits.append(f"页 {ev['page']}")
        if ev.get("line_start") is not None:
            loc_bits.append(f"行 {ev['line_start']}")
        if ev.get("title"):
            loc_bits.append(str(ev["title"]))
        loc = "；".join(loc_bits) if loc_bits else (ev.get("span") or "")
        quote = (ev.get("quote") or "")[:200]
        lines.append(f"- `{ev['evidence_id']}` ({loc}): {quote}")
    lines.extend(["", "## 动作时间线", ""])
    for t in timeline:
        extra = t.get("query") or t.get("candidate_id") or ""
        lines.append(
            f"- 步骤 {t['step_no']}: **{t['action']}** {extra} → {t['result_status']}"
        )
    lines.append("")
    return "\n".join(lines)


def build_export_package(
    conn,
    *,
    root: Path,
    run_id: str,
) -> dict[str, Any]:
    """Write artifacts/exports/<run_id>/ and optional zip; return paths + hashes."""
    run = repo.get_run(conn, run_id)
    if not run:
        raise KeyError(run_id)
    result = json.loads(run["result_json"]) if run["result_json"] else None
    citations = _list_evidence_for_run(conn, run_id)
    timeline = _list_actions_for_run(conn, run_id)

    export_dir = root / "artifacts" / "exports" / run_id
    export_dir.mkdir(parents=True, exist_ok=True)

    answer = {
        "run_id": run_id,
        "project_id": run["project_id"],
        "question": run["question"],
        "status": run["status"],
        "result": result,
        "version_set": json.loads(run["version_set_json"] or "[]"),
        "usage": (result or {}).get("usage"),
        "system": (result or {}).get("system"),
    }
    answer_path = export_dir / "answer.json"
    answer_path.write_text(json.dumps(answer, ensure_ascii=False, indent=2), encoding="utf-8")

    citations_path = export_dir / "citations.json"
    citations_path.write_text(json.dumps(citations, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = export_dir / "citations.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "evidence_id",
                "source_version_id",
                "page",
                "title",
                "line_start",
                "char_start",
                "char_end",
                "quote",
            ],
        )
        w.writeheader()
        for ev in citations:
            w.writerow({k: ev.get(k) for k in w.fieldnames})

    md_path = export_dir / "report.md"
    md_path.write_text(
        _markdown_report(run=dict(run), result=result, citations=citations, timeline=timeline),
        encoding="utf-8",
    )

    zip_path = export_dir / f"{run_id}_export.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in (answer_path, citations_path, csv_path, md_path):
            zf.write(p, arcname=p.name)

    files = {
        "answer_json": answer_path,
        "citations_json": citations_path,
        "citations_csv": csv_path,
        "report_md": md_path,
        "zip": zip_path,
    }
    hashes = {k: hashlib.sha256(v.read_bytes()).hexdigest() for k, v in files.items()}
    return {
        "run_id": run_id,
        "export_dir": str(export_dir),
        "files": {k: str(v) for k, v in files.items()},
        "sha256": hashes,
        "citation_count": len(citations),
        "status": run["status"],
    }

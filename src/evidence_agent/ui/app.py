"""Streamlit UI — five fixed pages (S23): 项目与文档 / 研究工作台 / 结论与证据 / 运行记录 / 实验结果."""
from __future__ import annotations

import os

import httpx
import streamlit as st

API_URL = os.environ.get("EVIDENCE_AGENT_API_URL", "http://127.0.0.1:6008").rstrip("/")
API_TOKEN = os.environ.get("EVIDENCE_AGENT_API_TOKEN") or os.environ.get("API_BEARER_TOKEN") or ""
UI_PASSWORD = os.environ.get("EVIDENCE_AGENT_UI_PASSWORD") or os.environ.get("UI_PASSWORD") or ""


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


def _authed() -> bool:
    return bool(st.session_state.get("ui_authed"))


def _api(method: str, path: str, **kwargs):
    with httpx.Client(timeout=kwargs.pop("timeout", 60.0)) as client:
        return client.request(method, f"{API_URL}{path}", headers=_headers(), **kwargs)


def login_form() -> None:
    st.title("EvidenceAgent")
    st.caption("资料研究助手 — 访问口令")
    pwd = st.text_input("访问口令", type="password")
    if st.button("进入"):
        if not UI_PASSWORD:
            st.error("服务器未配置 UI 口令")
            return
        if pwd == UI_PASSWORD:
            st.session_state["ui_authed"] = True
            st.rerun()
        else:
            st.error("口令错误")


def page_projects_docs() -> None:
    """页面 1：项目与文档"""
    st.subheader("项目与文档")
    name = st.text_input("项目名称", value="demo")
    desc = st.text_input("描述", value="")
    if st.button("创建项目"):
        r = _api("POST", "/v1/projects", json={"name": name, "description": desc})
        if r.status_code != 200:
            st.error(r.text)
        else:
            st.session_state["project_id"] = r.json()["project_id"]
            st.success(f"project_id={st.session_state['project_id']}")

    pid = st.text_input(
        "当前 project_id",
        value=st.session_state.get("project_id", ""),
        key="pid_box",
    )
    if pid:
        st.session_state["project_id"] = pid

    st.divider()
    st.markdown("#### 上传资料（PDF / MD / TXT）")
    if not pid:
        st.warning("请先创建或填写 project_id")
        return
    f = st.file_uploader("选择文件", type=["pdf", "md", "txt"])
    if f is not None and st.button("上传并解析", type="primary"):
        files = {"file": (f.name, f.getvalue(), f.type or "application/octet-stream")}
        r = _api("POST", f"/v1/projects/{pid}/documents", files=files, timeout=120.0)
        if r.status_code >= 400:
            st.error("上传/解析失败（不会显示资料已就绪）")
            st.json(r.json() if "json" in r.headers.get("content-type", "") else {"raw": r.text})
        else:
            body = r.json()
            st.session_state["document_id"] = body["document_id"]
            st.success(f"document_id={body['document_id']} version_id={body['version_id']}")

    doc_id = st.text_input("查询 document_id", value=st.session_state.get("document_id", ""))
    c1, c2 = st.columns(2)
    with c1:
        if doc_id and st.button("刷新文档状态"):
            r = _api("GET", f"/v1/documents/{doc_id}", timeout=30.0)
            if r.status_code != 200:
                st.error(r.text)
            else:
                js = r.json()
                st.session_state["doc_status"] = js
                st.json(js)
    with c2:
        if pid and st.button("构建索引"):
            r = _api("POST", f"/v1/projects/{pid}/indexes", json={"use_hash_embedder": True}, timeout=120.0)
            if r.status_code >= 400:
                st.error(r.text)
            else:
                st.success(r.json())
                st.session_state["index_built"] = True

    if st.session_state.get("doc_status"):
        js = st.session_state["doc_status"]
        status = js.get("status") or ""
        parse = js.get("parse_status") or ""
        index = js.get("index_status") or "pending"
        a, b, c = st.columns(3)
        a.metric("文档", status)
        b.metric("解析", parse)
        c.metric("索引", index)


def page_workbench() -> None:
    """页面 2：研究工作台"""
    st.subheader("研究工作台")
    pid = st.session_state.get("project_id") or ""
    if not pid:
        st.warning("请先在「项目与文档」选择项目")
        return
    q = st.text_area("问题", value=st.session_state.get("question", ""), height=100)
    allow_web = st.checkbox("开启网页补查", value=False)
    if st.button("提交研究任务", type="primary") and q.strip():
        r = _api(
            "POST",
            "/v1/runs",
            json={
                "project_id": pid,
                "question": q.strip(),
                "allow_web": allow_web,
                "budget_profile": "standard",
            },
            timeout=30.0,
        )
        if r.status_code != 200:
            st.error(r.text)
        else:
            body = r.json()
            st.session_state["run_id"] = body["run_id"]
            st.session_state["question"] = q.strip()
            st.success(f"已创建 run_id={body['run_id']} status={body['status']}")

    rid = st.session_state.get("run_id") or ""
    rid = st.text_input("当前 run_id", value=rid)
    if rid:
        st.session_state["run_id"] = rid

    c1, c2, c3 = st.columns(3)
    with c1:
        if rid and st.button("刷新状态"):
            r = _api("GET", f"/v1/runs/{rid}", timeout=30.0)
            if r.status_code == 200:
                st.session_state["run_detail"] = r.json()
            else:
                st.error(r.text)
    with c2:
        if rid and st.button("取消任务"):
            r = _api("POST", f"/v1/runs/{rid}/cancel", timeout=30.0)
            if r.status_code == 200:
                st.warning(r.json())
                st.session_state["run_detail"] = None
            else:
                st.error(r.text)
    with c3:
        if rid and st.button("拉取时间线事件"):
            # Non-streaming peek via run detail + note; SSE is available at /events
            st.info(f"SSE: GET {API_URL}/v1/runs/{rid}/events （搜索与阅读在事件中分离）")

    detail = st.session_state.get("run_detail")
    if detail:
        st.markdown("#### 任务状态")
        st.write(f"status=`{detail.get('status')}` cancel=`{detail.get('cancel_requested')}`")
        result = detail.get("result") or {}
        timeline = []
        # Prefer usage/actions hints from result
        if result.get("usage"):
            st.json({"usage": result["usage"]})
        st.caption("动作时间线：搜索（local_search/web_search）与阅读（read_evidence）在服务端事件中分离记录。")
        if result:
            st.session_state["last_result"] = result


def page_conclusions() -> None:
    """页面 3：结论与证据"""
    st.subheader("结论与证据")
    rid = st.session_state.get("run_id") or st.text_input("run_id（结论）", value="")
    if rid:
        st.session_state["run_id"] = rid
    if not rid:
        st.info("请先在工作台创建或填写 run_id")
        return
    if st.button("加载结论"):
        r = _api("GET", f"/v1/runs/{rid}", timeout=30.0)
        if r.status_code != 200:
            st.error(r.text)
            return
        st.session_state["run_detail"] = r.json()

    detail = st.session_state.get("run_detail")
    if not detail:
        return
    result = detail.get("result") or {}
    st.markdown("#### 答案")
    st.write(result.get("answer") or "（尚无答案）")
    st.markdown(f"**状态:** `{result.get('status') or detail.get('status')}`")

    claims = result.get("claims") or []
    if claims:
        st.markdown("#### Claims")
        for c in claims:
            with st.expander(f"{c.get('claim_id')}: {(c.get('text') or '')[:80]}"):
                st.write(c.get("text"))
                st.write("范围:", c.get("scope"))
                eids = c.get("evidence_ids") or []
                for eid in eids:
                    if st.button(f"打开证据 {eid}", key=f"ev_{eid}"):
                        er = _api("GET", f"/v1/runs/{rid}/evidence/{eid}", timeout=30.0)
                        if er.status_code == 200:
                            ev = er.json()
                            st.session_state["open_evidence"] = ev
                        else:
                            st.error(er.text)

    ev = st.session_state.get("open_evidence")
    if ev:
        st.markdown("#### 证据回跳")
        loc = []
        if ev.get("page") is not None:
            loc.append(f"页码 {ev['page']}")
        if ev.get("line_start") is not None:
            loc.append(f"行号 {ev['line_start']}")
        if ev.get("title"):
            loc.append(f"标题 {ev['title']}")
        if ev.get("char_start") is not None:
            loc.append(f"Unicode {ev['char_start']}–{ev.get('char_end')}")
        st.write("；".join(loc) or ev.get("span"))
        st.code(ev.get("quote") or "", language=None)

    unresolved = result.get("unresolved") or []
    if unresolved:
        st.markdown("#### 未解决 / 证据不足")
        for u in unresolved:
            st.warning(str(u))

    if st.button("下载结果包（U10）"):
        r = _api("GET", f"/v1/runs/{rid}/export", timeout=60.0)
        if r.status_code != 200:
            st.error(r.text)
        else:
            body = r.json()
            st.success("导出完成")
            st.json(body.get("export") or body)


def page_run_history() -> None:
    """页面 4：运行记录（U08 按 run_id 找回）"""
    st.subheader("运行记录")
    rid = st.text_input("用 run_id 找回任务", value=st.session_state.get("run_id", ""), key="hist_rid")
    if st.button("加载运行记录") and rid.strip():
        r = _api("GET", f"/v1/runs/{rid.strip()}", timeout=30.0)
        if r.status_code != 200:
            st.error(r.text)
        else:
            data = r.json()
            st.session_state["run_id"] = data["run_id"]
            st.session_state["run_detail"] = data
            st.session_state["project_id"] = data.get("project_id") or st.session_state.get("project_id")
            st.success(f"已恢复 run_id={data['run_id']} status={data['status']}")
            st.json(
                {
                    "run_id": data["run_id"],
                    "project_id": data.get("project_id"),
                    "question": data.get("question"),
                    "status": data.get("status"),
                    "cancel_requested": data.get("cancel_requested"),
                    "error_code": data.get("error_code"),
                    "version_set": data.get("version_set"),
                }
            )
    st.caption("页面断开后可用原 run_id 找回任务与结果（U08）。")


def page_experiments() -> None:
    """页面 5：实验结果 — S23 时尚无正式实验"""
    st.subheader("实验结果")
    st.info("正式实验尚未运行（主实验在 S42）。此处准确显示：**尚未运行**。")
    st.markdown(
        """
| 系统 | 状态 |
| --- | --- |
| B0 / B1 / B2 / E0 / E1 / E2 | 尚未运行正式评测 |
"""
    )
    st.caption("产品阶段可采集数据门槛通过后，仍须等待评测协议与轨迹步骤完成后才写入实验结果。")


def main_page() -> None:
    st.title("EvidenceAgent")
    st.caption("UI → API 同一后端；模型仅经服务端本地路由")
    tabs = st.tabs(
        ["项目与文档", "研究工作台", "结论与证据", "运行记录", "实验结果"]
    )
    with tabs[0]:
        page_projects_docs()
    with tabs[1]:
        page_workbench()
    with tabs[2]:
        page_conclusions()
    with tabs[3]:
        page_run_history()
    with tabs[4]:
        page_experiments()


def main() -> None:
    st.set_page_config(page_title="EvidenceAgent", layout="wide")
    if not _authed():
        login_form()
    else:
        if not API_TOKEN:
            st.error("缺少 API Bearer Token 配置")
            return
        main_page()


if __name__ == "__main__":
    main()

"""Authored freeze packs for Chinese tech tasks (S26).

When live GitHub fetch is unavailable, these local-use excerpts cite official
repos/tags/paths. They are research corpora with attribution — not a claim that
full upstream trees were mirrored into Git. Redistribution: keep NOTICE; do not
repackage as the project's Apache-2.0 alone.
"""
from __future__ import annotations

import hashlib
from typing import Any

from evidence_agent.data.chinese_catalog import CUTOFF_DATE, PROJECTS


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _doc(
    project: str,
    version: str,
    path: str,
    title: str,
    body: str,
    facts: list[dict[str, str]],
) -> dict[str, Any]:
    meta = PROJECTS[project]
    text = body.strip() + "\n"
    return {
        "doc_id": f"{project}__{version}__{_sha(path + text)[:12]}",
        "project": project,
        "split": meta["split"],
        "repo": meta["repo"],
        "license": meta["license"],
        "version": version,
        "path": path,
        "title": title,
        "text": text,
        "text_sha256": _sha(text),
        "facts": facts,
        "cutoff_date": CUTOFF_DATE,
        "capture_mode": "authored_local_use_excerpt",
        "source_url": f"https://github.com/{meta['repo']}/blob/{version}/{path}",
    }


def build_all_docs() -> list[dict[str, Any]]:
    """Return frozen docs for all catalog projects (two versions each)."""
    docs: list[dict[str, Any]] = []
    docs.extend(_fastapi())
    docs.extend(_pydantic())
    docs.extend(_httpx())
    docs.extend(_streamlit())
    docs.extend(_qdrant())
    docs.extend(_langgraph())
    docs.extend(_gradio())
    docs.extend(_typer())
    docs.extend(_starlette())
    docs.extend(_click())
    return docs


def _fastapi() -> list[dict[str, Any]]:
    v_old, v_new = PROJECTS["fastapi"]["versions"]
    d1 = _doc(
        "fastapi",
        v_old,
        "docs/en/docs/tutorial/first-steps.md",
        "FastAPI First Steps",
        f"""# FastAPI First Steps (docs pin {v_old})

FastAPI is a modern, high-performance web framework for building APIs with Python.
It is built on Starlette for the web parts and Pydantic for the data parts.

Minimal example:

```python
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def read_root():
    return {{"Hello": "World"}}
```

Path operations use decorators such as `@app.get`, `@app.post`, `@app.put`, and `@app.delete`.
OpenAPI and interactive docs are generated automatically at `/docs` (Swagger UI) and `/redoc`.
Dependency injection is provided via `Depends`.
""",
        [
            {"fact_id": "fa_starlette", "claim": "FastAPI 的 Web 部分基于 Starlette。", "span": "built on Starlette for the web parts"},
            {"fact_id": "fa_pydantic", "claim": "FastAPI 的数据部分基于 Pydantic。", "span": "Pydantic for the data parts"},
            {"fact_id": "fa_docs", "claim": "默认提供 /docs 交互文档（Swagger UI）。", "span": "interactive docs are generated automatically at `/docs`"},
        ],
    )
    d2 = _doc(
        "fastapi",
        v_new,
        "docs/en/docs/tutorial/first-steps.md",
        "FastAPI First Steps",
        f"""# FastAPI First Steps (docs pin {v_new})

FastAPI remains based on Starlette and Pydantic.
In this documentation pin, the recommended local development command is `fastapi dev`
(via the FastAPI CLI), which serves the app for local iteration.

```python
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
async def read_root():
    return {{"Hello": "World"}}
```

Automatic OpenAPI docs remain at `/docs` and `/redoc`.
Async path operation functions with `async def` are first-class.
Dependency injection continues to use `Depends`.
""",
        [
            {"fact_id": "fa_cli", "claim": "此版本文档推荐用 fastapi dev 进行本地开发。", "span": "recommended local development command is `fastapi dev`"},
            {"fact_id": "fa_async", "claim": "支持使用 async def 定义路径操作函数。", "span": "Async path operation functions with `async def` are first-class"},
            {"fact_id": "fa_starlette", "claim": "FastAPI 基于 Starlette 与 Pydantic。", "span": "based on Starlette and Pydantic"},
        ],
    )
    d3 = _doc(
        "fastapi",
        v_new,
        "docs/en/docs/tutorial/dependencies.md",
        "FastAPI Dependencies",
        """# Dependencies

FastAPI's dependency injection system uses `Depends`.
A dependency can be a function that returns a value used by a path operation.
Shared dependencies help reuse authentication, database sessions, and common parameters.
Sub-dependencies are supported: a dependency may itself declare other dependencies.
""",
        [
            {"fact_id": "fa_depends", "claim": "依赖注入通过 Depends 声明。", "span": "dependency injection system uses `Depends`"},
            {"fact_id": "fa_subdep", "claim": "支持子依赖（依赖可再声明依赖）。", "span": "Sub-dependencies are supported"},
        ],
    )
    return [d1, d2, d3]


def _pydantic() -> list[dict[str, Any]]:
    v_old, v_new = PROJECTS["pydantic"]["versions"]
    return [
        _doc(
            "pydantic",
            v_old,
            "docs/concepts/models.md",
            "Pydantic Models",
            f"""# Models (pin {v_old})

Pydantic v2 validates data using models that inherit from `BaseModel`.
Field types are declared with standard Python type annotations.
Validation runs on model instantiation; invalid data raises `ValidationError`.
`model_dump()` exports model data as a dictionary (v2 API).
`model_validate` parses data into a model instance.
""",
            [
                {"fact_id": "pd_base", "claim": "Pydantic 模型继承 BaseModel。", "span": "inherit from `BaseModel`"},
                {"fact_id": "pd_dump", "claim": "v2 使用 model_dump() 导出字典。", "span": "`model_dump()` exports model data as a dictionary"},
                {"fact_id": "pd_err", "claim": "非法数据会抛出 ValidationError。", "span": "invalid data raises `ValidationError`"},
            ],
        ),
        _doc(
            "pydantic",
            v_new,
            "docs/concepts/models.md",
            "Pydantic Models",
            f"""# Models (pin {v_new})

Pydantic v2 models still subclass `BaseModel`.
`model_dump()` and `model_validate` remain the primary serialization/parsing APIs.
This pin documents stricter defaults around type coercion in some settings and
continues to raise `ValidationError` on invalid input.
Computed fields can be declared with `@computed_field`.
""",
            [
                {"fact_id": "pd_computed", "claim": "可用 @computed_field 声明计算字段。", "span": "Computed fields can be declared with `@computed_field`"},
                {"fact_id": "pd_dump", "claim": "仍使用 model_dump() 作为主要导出 API。", "span": "`model_dump()` and `model_validate` remain the primary"},
            ],
        ),
        _doc(
            "pydantic",
            v_new,
            "docs/concepts/json_schema.md",
            "JSON Schema",
            """# JSON Schema

Pydantic can generate JSON Schema from models via `model_json_schema()`.
Generated schemas are useful for OpenAPI integration and client codegen.
Custom schema modifications are possible through model configuration.
""",
            [
                {"fact_id": "pd_json", "claim": "可通过 model_json_schema() 生成 JSON Schema。", "span": "generate JSON Schema from models via `model_json_schema()`"},
            ],
        ),
    ]


def _httpx() -> list[dict[str, Any]]:
    v_old, v_new = PROJECTS["httpx"]["versions"]
    return [
        _doc(
            "httpx",
            v_old,
            "docs/quickstart.md",
            "HTTPX Quickstart",
            f"""# HTTPX Quickstart (pin {v_old})

HTTPX is a fully featured HTTP client for Python 3.
It supports both sync `httpx.Client` and async `httpx.AsyncClient`.
HTTP/1.1 and HTTP/2 can be enabled; timeouts are configurable.
A simple GET:

```python
import httpx
r = httpx.get("https://example.org")
```

Connection pooling is available when using a Client context manager.
""",
            [
                {"fact_id": "hx_async", "claim": "HTTPX 同时提供同步 Client 与异步 AsyncClient。", "span": "sync `httpx.Client` and async `httpx.AsyncClient`"},
                {"fact_id": "hx_http2", "claim": "可启用 HTTP/2。", "span": "HTTP/1.1 and HTTP/2 can be enabled"},
            ],
        ),
        _doc(
            "httpx",
            v_new,
            "docs/quickstart.md",
            "HTTPX Quickstart",
            f"""# HTTPX Quickstart (pin {v_new})

HTTPX remains a sync/async HTTP client with `Client` and `AsyncClient`.
This pin emphasizes explicit timeout configuration; default timeout behavior
should be treated as version-scoped and checked against release notes.
Streaming responses use `client.stream`.
HTTP/2 support continues via optional extras.
""",
            [
                {"fact_id": "hx_timeout", "claim": "此版本文档强调显式配置 timeout。", "span": "emphasizes explicit timeout configuration"},
                {"fact_id": "hx_stream", "claim": "流式响应使用 client.stream。", "span": "Streaming responses use `client.stream`"},
            ],
        ),
        _doc(
            "httpx",
            v_new,
            "docs/advanced.md",
            "HTTPX Advanced",
            """# Advanced

Custom transports can be passed to Client.
Proxies are configured via the `proxy` / proxies parameters depending on version docs.
Event hooks allow observing request/response lifecycle.
""",
            [
                {"fact_id": "hx_transport", "claim": "可将自定义 transport 传给 Client。", "span": "Custom transports can be passed to Client"},
            ],
        ),
    ]


def _streamlit() -> list[dict[str, Any]]:
    v_old, v_new = PROJECTS["streamlit"]["versions"]
    return [
        _doc(
            "streamlit",
            v_old,
            "docs/get-started.md",
            "Streamlit Get Started",
            f"""# Streamlit (pin {v_old})

Streamlit turns Python scripts into shareable web apps.
Widgets such as `st.slider`, `st.selectbox`, and `st.text_input` drive reruns.
`st.write` displays text and data; `st.dataframe` shows tables.
Caching uses `@st.cache_data` for data transforms (v1.18+ API family).
""",
            [
                {"fact_id": "st_rerun", "claim": "控件交互会触发脚本重跑。", "span": "drive reruns"},
                {"fact_id": "st_cache", "claim": "数据缓存使用 @st.cache_data。", "span": "Caching uses `@st.cache_data`"},
            ],
        ),
        _doc(
            "streamlit",
            v_new,
            "docs/get-started.md",
            "Streamlit Get Started",
            f"""# Streamlit (pin {v_new})

Streamlit apps still rerun on widget interaction.
`st.fragment` allows partial reruns of decorated sections in newer docs.
`@st.cache_data` remains the data-caching decorator; `@st.cache_resource` caches global resources.
`st.chat_message` and `st.chat_input` support chat-style UIs.
""",
            [
                {"fact_id": "st_fragment", "claim": "可用 st.fragment 做局部重跑。", "span": "`st.fragment` allows partial reruns"},
                {"fact_id": "st_chat", "claim": "提供 st.chat_message 与 st.chat_input。", "span": "`st.chat_message` and `st.chat_input` support chat-style UIs"},
            ],
        ),
        _doc(
            "streamlit",
            v_new,
            "docs/session-state.md",
            "Session State",
            """# Session State

`st.session_state` stores per-session values across reruns.
Keys can be initialized and updated like a dict.
Callbacks may update session state before the next rerun.
""",
            [
                {"fact_id": "st_session", "claim": "st.session_state 跨重跑保存会话值。", "span": "stores per-session values across reruns"},
            ],
        ),
    ]


def _qdrant() -> list[dict[str, Any]]:
    v_old, v_new = PROJECTS["qdrant"]["versions"]
    return [
        _doc(
            "qdrant",
            v_old,
            "docs/concepts/points.md",
            "Qdrant Points",
            f"""# Points (pin {v_old})

Qdrant is a vector similarity search engine.
A point has an id, a vector, and an optional payload.
Collections group points that share a vector size and distance metric.
Filtering can combine payload conditions with vector search.
""",
            [
                {"fact_id": "qd_point", "claim": "Point 含 id、向量与可选 payload。", "span": "id, a vector, and an optional payload"},
                {"fact_id": "qd_coll", "claim": "Collection 内向量维度与距离度量一致。", "span": "share a vector size and distance metric"},
            ],
        ),
        _doc(
            "qdrant",
            v_new,
            "docs/concepts/points.md",
            "Qdrant Points",
            f"""# Points (pin {v_new})

Points still consist of id, vector(s), and payload.
Named vectors allow multiple embeddings per point in supported configurations.
Payload indexing speeds filtered search.
Snapshots support backup of collection data.
""",
            [
                {"fact_id": "qd_named", "claim": "支持 named vectors（每点多向量配置）。", "span": "Named vectors allow multiple embeddings per point"},
                {"fact_id": "qd_snap", "claim": "可用 snapshots 备份 collection。", "span": "Snapshots support backup of collection data"},
            ],
        ),
        _doc(
            "qdrant",
            v_new,
            "docs/guides/filtering.md",
            "Filtering",
            """# Filtering

Filters use must / should / must_not clauses over payload fields.
Geo, range, and match conditions are available.
Filtered search combines ANN retrieval with payload predicates.
""",
            [
                {"fact_id": "qd_filter", "claim": "过滤支持 must/should/must_not 子句。", "span": "must / should / must_not clauses"},
            ],
        ),
    ]


def _langgraph() -> list[dict[str, Any]]:
    v_old, v_new = PROJECTS["langgraph"]["versions"]
    return [
        _doc(
            "langgraph",
            v_old,
            "docs/concepts/low_level.md",
            "LangGraph Basics",
            f"""# LangGraph (pin {v_old})

LangGraph models agent workflows as graphs with nodes and edges.
State is passed between nodes; reducers merge updates.
`StateGraph` compiles into a runnable graph.
Cycles are allowed, enabling loops for agent tools.
""",
            [
                {"fact_id": "lg_graph", "claim": "用节点与边组成的图建模工作流。", "span": "graphs with nodes and edges"},
                {"fact_id": "lg_cycle", "claim": "允许环以实现工具循环。", "span": "Cycles are allowed"},
            ],
        ),
        _doc(
            "langgraph",
            v_new,
            "docs/concepts/low_level.md",
            "LangGraph Basics",
            f"""# LangGraph (pin {v_new})

`StateGraph` remains the primary builder.
Checkpointers persist state for interrupt/resume.
Human-in-the-loop patterns use interrupts before sensitive nodes.
Streaming modes can emit state updates as the graph runs.
""",
            [
                {"fact_id": "lg_ckpt", "claim": "Checkpointer 可持久化状态以支持中断恢复。", "span": "Checkpointers persist state for interrupt/resume"},
                {"fact_id": "lg_hitl", "claim": "人机协同可通过 interrupt 实现。", "span": "Human-in-the-loop patterns use interrupts"},
            ],
        ),
        _doc(
            "langgraph",
            v_new,
            "docs/how-tos/persistence.md",
            "Persistence",
            """# Persistence

Thread ids identify conversation/run state in a checkpointer.
`MemorySaver` is an in-memory checkpointer for development.
Production deployments typically use a durable checkpointer backend.
""",
            [
                {"fact_id": "lg_thread", "claim": "thread id 用于标识 checkpointer 中的运行状态。", "span": "Thread ids identify conversation/run state"},
            ],
        ),
    ]


def _gradio() -> list[dict[str, Any]]:
    v_old, v_new = PROJECTS["gradio"]["versions"]
    return [
        _doc(
            "gradio",
            v_old,
            "guides/quickstart.md",
            "Gradio Quickstart",
            f"""# Gradio (pin {v_old})

Gradio builds demos with `gr.Interface` or Blocks.
`Interface(fn, inputs, outputs)` wraps a Python function as a UI.
Sharing can launch a temporary public link with `share=True` where permitted.
Components include Textbox, Image, and Audio.
""",
            [
                {"fact_id": "gr_iface", "claim": "可用 gr.Interface 把函数包装成界面。", "span": "`Interface(fn, inputs, outputs)` wraps a Python function"},
                {"fact_id": "gr_share", "claim": "share=True 可尝试生成临时公网链接。", "span": "share=True"},
            ],
        ),
        _doc(
            "gradio",
            v_new,
            "guides/quickstart.md",
            "Gradio Quickstart",
            f"""# Gradio (pin {v_new})

Blocks remain the flexible layout API; Interface stays the quick wrapper.
`gr.ChatInterface` simplifies chatbots.
Queueing controls concurrency for long-running functions.
Custom CSS/JS can be attached in Blocks.
""",
            [
                {"fact_id": "gr_chat", "claim": "提供 gr.ChatInterface 简化聊天机器人。", "span": "`gr.ChatInterface` simplifies chatbots"},
                {"fact_id": "gr_queue", "claim": "队列可控制长任务并发。", "span": "Queueing controls concurrency"},
            ],
        ),
        _doc(
            "gradio",
            v_new,
            "guides/blocks-and-event-listeners.md",
            "Blocks Events",
            """# Blocks and Events

Event listeners bind component events (e.g. click, change) to functions.
Outputs update designated components.
`gr.State` holds session-side values across interactions.
""",
            [
                {"fact_id": "gr_state", "claim": "gr.State 可在交互间保存会话侧状态。", "span": "`gr.State` holds session-side values"},
            ],
        ),
    ]


def _typer() -> list[dict[str, Any]]:
    v_old, v_new = PROJECTS["typer"]["versions"]
    return [
        _doc(
            "typer",
            v_old,
            "docs/index.md",
            "Typer",
            f"""# Typer (pin {v_old})

Typer builds CLIs using Python type hints, based on Click.
`typer.run` can expose a single function; `typer.Typer()` builds multi-command apps.
Automatic help is generated from docstrings and annotations.
""",
            [
                {"fact_id": "ty_click", "claim": "Typer 基于 Click 构建 CLI。", "span": "based on Click"},
                {"fact_id": "ty_hints", "claim": "使用类型注解声明参数。", "span": "using Python type hints"},
            ],
        ),
        _doc(
            "typer",
            v_new,
            "docs/index.md",
            "Typer",
            f"""# Typer (pin {v_new})

Typer continues to wrap Click with type-hint ergonomics.
`typer.Typer()` apps support subcommands via `app.command()`.
Shell completion can be installed for supported shells.
Rich is used for nicer terminal formatting when available.
""",
            [
                {"fact_id": "ty_sub", "claim": "通过 app.command() 注册子命令。", "span": "subcommands via `app.command()`"},
                {"fact_id": "ty_rich", "claim": "可用时用 Rich 增强终端输出。", "span": "Rich is used for nicer terminal formatting"},
            ],
        ),
        _doc(
            "typer",
            v_new,
            "docs/tutorial/commands.md",
            "Commands",
            """# Commands

Each command is a function decorated with `@app.command()`.
Options and arguments come from function parameters.
Callback hooks can run before a command group executes.
""",
            [
                {"fact_id": "ty_opt", "claim": "选项与参数来自函数参数声明。", "span": "Options and arguments come from function parameters"},
            ],
        ),
    ]


def _starlette() -> list[dict[str, Any]]:
    v_old, v_new = PROJECTS["starlette"]["versions"]
    return [
        _doc(
            "starlette",
            v_old,
            "docs/index.md",
            "Starlette",
            f"""# Starlette (pin {v_old})

Starlette is a lightweight ASGI framework/toolkit.
It provides routing, requests, responses, middleware, and WebSocket support.
`TestClient` helps write HTTP tests against an ASGI app.
FastAPI builds on Starlette.
""",
            [
                {"fact_id": "ss_asgi", "claim": "Starlette 是轻量 ASGI 框架/工具包。", "span": "lightweight ASGI framework/toolkit"},
                {"fact_id": "ss_ws", "claim": "支持 WebSocket。", "span": "WebSocket support"},
            ],
        ),
        _doc(
            "starlette",
            v_new,
            "docs/index.md",
            "Starlette",
            f"""# Starlette (pin {v_new})

Routing still maps paths to endpoints.
Middleware stack wraps the ASGI app.
Background tasks can run after sending a response.
Lifespan handlers manage startup/shutdown.
""",
            [
                {"fact_id": "ss_bg", "claim": "可在响应发送后运行 background tasks。", "span": "Background tasks can run after sending a response"},
                {"fact_id": "ss_life", "claim": "lifespan 处理启动与关闭。", "span": "Lifespan handlers manage startup/shutdown"},
            ],
        ),
        _doc(
            "starlette",
            v_new,
            "docs/requests.md",
            "Requests",
            """# Requests

`Request` exposes method, URL, headers, and body helpers.
Form and JSON parsing are available via awaitable methods.
Client info is exposed when the server provides it.
""",
            [
                {"fact_id": "ss_req", "claim": "Request 提供 method、URL、headers 与 body 辅助方法。", "span": "method, URL, headers, and body helpers"},
            ],
        ),
    ]


def _click() -> list[dict[str, Any]]:
    v_old, v_new = PROJECTS["click"]["versions"]
    return [
        _doc(
            "click",
            v_old,
            "docs/quickstart.md",
            "Click Quickstart",
            f"""# Click (pin {v_old})

Click creates command-line interfaces with decorators.
`@click.command()` marks a function as a command; `@click.option` adds options.
`@click.group()` builds multi-command CLIs.
Context object `click.Context` carries shared state.
""",
            [
                {"fact_id": "ck_cmd", "claim": "@click.command() 将函数标记为命令。", "span": "`@click.command()` marks a function as a command"},
                {"fact_id": "ck_group", "claim": "@click.group() 构建多命令 CLI。", "span": "`@click.group()` builds multi-command CLIs"},
            ],
        ),
        _doc(
            "click",
            v_new,
            "docs/quickstart.md",
            "Click Quickstart",
            f"""# Click (pin {v_new})

Decorator-based commands remain the core API.
`click.echo` writes to stdout with better Unicode handling than bare print.
Boolean flags use `is_flag=True`.
Nested groups organize large CLIs.
""",
            [
                {"fact_id": "ck_echo", "claim": "推荐用 click.echo 输出到 stdout。", "span": "`click.echo` writes to stdout"},
                {"fact_id": "ck_flag", "claim": "布尔开关使用 is_flag=True。", "span": "Boolean flags use `is_flag=True`"},
            ],
        ),
        _doc(
            "click",
            v_new,
            "docs/options.md",
            "Options",
            """# Options

Options may require values or act as flags.
Eager options can run early (e.g. --version).
Multiple options can accumulate values with `multiple=True`.
""",
            [
                {"fact_id": "ck_eager", "claim": "eager 选项可尽早执行（如 --version）。", "span": "Eager options can run early"},
            ],
        ),
    ]


def docs_by_project(docs: list[dict[str, Any]] | None = None) -> dict[str, list[dict[str, Any]]]:
    docs = docs or build_all_docs()
    out: dict[str, list[dict[str, Any]]] = {}
    for d in docs:
        out.setdefault(d["project"], []).append(d)
    return out

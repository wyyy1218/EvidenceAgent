# EvidenceAgent HTTP API 契约（S09）

> 权威来源：项目说明 §12、§13.3、§18.2–18.3、附录 B。  
> 本文件固定对外协议；实现不得发明新终态或绕过鉴权。

## 1. 鉴权与健康检查

| 方法与路径 | 鉴权 | 说明 |
| --- | --- | --- |
| `GET /healthz` | 无 | 进程存活；不返回密钥或私有路径 |
| `GET /readyz` | Bearer | 报告 model / index / worker 是否就绪；缺项列入 `not_ready` |
| 其余 `/v1/*` | Bearer | `Authorization: Bearer <token>`；缺失或错误 → `401` |

Token 来自环境变量 `EVIDENCE_AGENT_API_TOKEN`（或兼容名 `API_BEARER_TOKEN`）。未配置时受保护端点返回 `503`。

## 2. 端点一览

| 方法与路径 | 输入 | 成功返回 |
| --- | --- | --- |
| `POST /v1/projects` | `name`, `description?` | `project_id` |
| `POST /v1/projects/{id}/documents` | multipart `file` | `document_id`, `version_id`, `ingest_job_id` |
| `GET /v1/documents/{id}` | — | 解析/索引/版本状态 |
| `POST /v1/runs` | `project_id`, `question`, `allow_web`, `budget_profile` | `run_id`, `status`（通常 `queued`） |
| `GET /v1/runs/{id}` | — | 状态、预算、错误、完成结果 |
| `GET /v1/runs/{id}/events` | `Last-Event-ID`（可选） | SSE 时间线；可重连 |
| `POST /v1/runs/{id}/cancel` | — | 取消确认 |
| `GET /v1/runs/{id}/evidence/{evidence_id}` | — | 原文摘录、位置、来源与快照 |
| `GET /v1/runs/{id}/export` | — | 答案、引用与轨迹摘要包 |
| `POST /v1/ask` | `question` | S08 短问（本地 base）；保留兼容 |

创建 run **异步**返回，不长时间阻塞 HTTP。`budget_profile` 对外仅允许 `standard`；`b4`/`b8`/`b12` 仅内部评测。

## 3. Run 生命周期状态

### 3.1 执行态（队列）

| 状态 | 含义 |
| --- | --- |
| `queued` | 已入队，等待 Worker 认领 |
| `running` | Worker 已认领，执行中 |

### 3.2 终态（对外）

| 状态 | 含义 |
| --- | --- |
| `answered` | 主要需求有受支持结论 |
| `partial` | 局部结论，仍有未解决项 |
| `insufficient_evidence` | 资料不足 |
| `conflicting_evidence` | 同条件冲突无法消解 |
| `cancelled` | 用户取消 |
| `timeout` | 墙钟耗尽 |
| `failed` | 模型/工具/存储/策略错误导致无法正常完成 |

### 3.3 `failed_policy`

策略非法动作二次失败等记入内部原因字段（如 `failure_reason=failed_policy` 或 `error_code=failed_policy`），**对外 `status` 仍为 `failed`**。模块不得新增未列出的终态名。

## 4. 错误码（HTTP）

| HTTP | 场景 |
| --- | ---: |
| `400` | 校验失败（空问题 T01、非法 `budget_profile`、不支持文件类型等） |
| `401` | 缺少或错误 Bearer |
| `403` | 跨项目读取拒绝（文档/run/evidence） |
| `404` | 资源不存在（且不暴露其他项目信息） |
| `409` | 幂等冲突：同 `Idempotency-Key`、不同请求体哈希 |
| `413` / `400` | 文件超限（大小/页数/文档数） |
| `422` | 语义不可接受（如 `needs_ocr` 拒绝标成功） |
| `429` | 队列已满（排队中 run ≥ `max_queue_size`，默认 10） |
| `503` | Token 未配置或关键依赖不可用 |

业务错误体建议：`{"error": {"code": "...", "message": "..."}}`。

## 5. 幂等（`Idempotency-Key`）

- 头：`Idempotency-Key`（创建 run 时建议必填；缺省则每次新建）。
- 绑定：**规范化请求体 JSON 的 SHA-256**（字段排序稳定）。
- 同 key + 同哈希 → 返回原 `run_id`（不新建）。
- 同 key + 不同哈希 → `409`。
- 用固定夹具验证（T17），不依赖付费调用。

## 6. 队列与 Worker

- 同时执行研究任务：**1**（`worker_concurrency=1`）。
- 排队上限：**10**（`queued` 计数）；超出 → `429`。
- Worker 经 SQLite 事务认领：`queued → running`，写入 `worker_lease` 与心跳。
- 取消：设 `cancel_requested`；不再派发新步骤；已发出的远端请求可能完成。

## 7. SSE

- `GET /v1/runs/{id}/events`：`text/event-stream`。
- 支持 `Last-Event-ID` 续传；事件来自持久化 `audit_events`。
- 窗口可截断最近条目，完整轨迹仍在库中。

## 8. 项目隔离

所有按 ID 读取的资源必须校验所属 `project_id`（经 run 或 document 关联）。跨项目或不存在 → `403`/`404`，禁止泄漏他项目内容（T20）。

## 9. 兼容端点

`POST /v1/ask` 保留 S08 最小联通，不创建研究 run、不计研究队列。

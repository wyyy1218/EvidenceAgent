# EvidenceAgent 存储设计（S09）

> 权威来源：项目说明 §9.1、§18.3。元数据 SQLite；大文件落数据盘。

## 1. 路径

| 用途 | 相对 WORK_ROOT |
| --- | --- |
| SQLite | `data/app/evidence_agent.sqlite` |
| 原文件 | `data/raw/<source_version_id>/` |
| 规范化文本与映射 | `data/normalized/<source_version_id>/` |
| 分块 / 索引（S12+） | `data/chunks/`、`data/indexes/` |

连接必须：`PRAGMA foreign_keys=ON`；`PRAGMA journal_mode=WAL`。  
**禁止**把原文件、模型权重、大型正文写入 BLOB。

## 2. 表结构（v0001）

### projects

| 列 | 类型 | 约束 |
| --- | --- | --- |
| id | TEXT | PK |
| name | TEXT | NOT NULL |
| description | TEXT | |
| created_at | TEXT | NOT NULL（ISO-8601 UTC） |

### documents

| 列 | 类型 | 约束 |
| --- | --- | --- |
| id | TEXT | PK |
| project_id | TEXT | FK → projects |
| display_name | TEXT | NOT NULL |
| status | TEXT | 上传/校验/解析/索引态 |
| created_at | TEXT | NOT NULL |
| updated_at | TEXT | NOT NULL |

### source_versions

| 列 | 类型 | 约束 |
| --- | --- | --- |
| id | TEXT | PK |
| document_id | TEXT | FK → documents |
| content_hash | TEXT | NOT NULL（SHA-256 hex） |
| parser_version | TEXT | NOT NULL |
| file_path | TEXT | 相对 WORK_ROOT 或绝对受控路径 |
| snapshot_time | TEXT | NOT NULL |
| byte_size | INTEGER | |
| mime_type | TEXT | |
| page_count | INTEGER | |
| parse_status | TEXT | |
| normalized_path | TEXT | |
| mapping_path | TEXT | |

同内容去重：按 `content_hash` 查找可复用的规范化产物；仍可为不同 `document_id`/`display_name` 建关联版本行，不制造虚假内容冲突。

### chunks / indexes

S09 建表；填充在 S12。`chunks`：`id, source_version_id, text, page, section, start, end, parent_id`。  
`indexes`：`id, project_id, version_set_hash, embedding_revision, index_path`。

### runs

| 列 | 类型 | 约束 |
| --- | --- | --- |
| id | TEXT | PK |
| project_id | TEXT | FK |
| question | TEXT | NOT NULL |
| status | TEXT | NOT NULL |
| policy_id | TEXT | |
| budget | TEXT | JSON |
| worker_lease | TEXT | |
| lease_expires_at | TEXT | |
| cancel_requested | INTEGER | 0/1 |
| allow_web | INTEGER | 0/1 |
| budget_profile | TEXT | |
| idempotency_key | TEXT | |
| request_hash | TEXT | |
| version_set_json | TEXT | 创建时锁定的 source_version_id 集合 |
| failure_reason | TEXT | 含 `failed_policy` 等内部原因 |
| error_code | TEXT | |
| result_json | TEXT | |
| created_at / updated_at | TEXT | |

幂等：`(idempotency_key)` 在非空时 UNIQUE；同 key 不同 `request_hash` 在应用层拒绝（409）。

### actions

| 列 | 约束 |
| --- | --- |
| id | PK |
| run_id | FK |
| step_no | INTEGER |
| state_hash | TEXT |
| action_json | TEXT |
| result_status | TEXT |
| result_json | TEXT | |
| UNIQUE(run_id, step_no) | |

### evidence / claims / claim_evidence

见 §18.3：evidence 绑 `run_id` + `source_version_id` + span/quote；claims 绑核验状态；`claim_evidence` 联合主键。

### usage_events / audit_events

用量与审计；SSE 读 `audit_events`。

## 3. 事务边界

固定顺序：

1. **登记**：写入待执行动作或 ingest 作业行（同事务可见）。
2. **结果提交**：动作结果、evidence/claims、状态推进在**同一事务**提交。
3. **禁止半条**：测试故意抛错时不得留下孤立 `actions` 而无匹配结果状态。

Worker 认领：`UPDATE runs SET status='running', worker_lease=?, lease_expires_at=? WHERE id=? AND status='queued'`，检查 `rowcount`。

## 4. 迁移与回退

- 正向：`storage/migrations/0001_init.sql`，由 `migrate.py` 应用并记入 `schema_migrations`。
- 回退：`0001_down.sql` 删除 v0001 表（**仅空库/测试**；生产历史数据不得靠删表掩盖问题）。
- 变更 schema 必须新增迁移编号，并更新本文件与 CHANGELOG。

## 5. 清洗与偏移（S11）

- 清洗前 / 清洗后文本与 `mapping.json` 分文件保存于 `data/normalized/<version_id>/`。
- MD/TXT：Unicode **码点**左闭右开 `[start,end)`，附行号与标题。
- PDF：页码 + 页内字符偏移；**不是**视觉坐标。
- BOM：UTF-8 BOM 在清洗后文本中去除；映射记录 `bom_stripped=true`，偏移相对清洗后串。
- 换行统一记录为 `\n`（清洗后）；原始字节保留在 raw 文件。
- 空白：不做破坏性折叠到影响区间语义；若规范化空白，映射表须可逆查原文。

## 6. 版本快照

- 更新文档 → 新 `source_version_id`。
- Run 创建时写入 `version_set_json`；此后文档更新不影响旧 run。
- 证据始终通过 `source_version_id` 回指不可变快照。

# 交付核对表（S49→S50）

> release_id: `rel_s50_e0_0001`（继承 S49 包 `rel_s49_e0_0001`）  
> 日期：2026-10-28  
> 规则：文件存在 ≠ PASS；须可打开、哈希可核、公开边界明确。  
> Git 标签：`v1.0.0-preview`（见 `completion_levels.md`）。

## 图例

| 标记 | 含义 |
| --- | --- |
| PASS | 已交付且核验 |
| COND | 条件未满足（原因已写） |
| PRIV | 仅私有备份，不可公开 |
| N/A | 本轮不适用 |

## 清单

| # | 项 | 位置 | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | 访客 README | `repo/README.md` | PASS | 问题/启动/功能/结果/限制；非整篇规格粘贴 |
| 2 | 数据卡 Hotpot | `repo/docs/data/data_card.md` | PASS | CC BY-SA 4.0；派生子集 |
| 3 | 数据卡中文来源 | `repo/docs/data/chinese_sources_card.md` | PASS | authored excerpt 边界 |
| 4 | 数据卡中文任务 | `repo/docs/data/chinese_tasks_card.md` | PASS | 240/60/100；单人审核声明 |
| 5 | 基座模型卡 | `repo/docs/models/base_model_card.md` | PASS | E0 发布 |
| 6 | SFT 模型卡 | `repo/docs/models/sft_model_card.md` | PASS | research_only；G 门槛 FAIL |
| 7 | DPO 模型卡 | `repo/docs/models/dpo_model_card.md` | PASS | 未入选；scale 未达标 |
| 8 | 演示脚本 | `repo/docs/delivery/demo_script.md` | PASS | 上传→导出全链路 |
| 9 | API 示例 | `repo/examples/requests/` | PASS | 无密钥 |
| 10 | 脱敏输出示例 | `repo/examples/outputs/sample_export/` | PASS | 夹具级；非评测 gold |
| 11 | 正式报告 | `artifacts/reports/rpt_s47_0001/` | PASS | 数值可追溯 |
| 12 | 复现/服务 | `runs/steps/S48/a001/` | PASS | 公开托管 NOT_PROVIDED |
| 13 | S49 Release | `artifacts/releases/rel_s49_e0_0001/` | PASS | manifest + checksums |
| 14 | 大文件索引 | `repo/artifacts/artifact_index.json` | PASS | 不含权重本体 |
| 15 | SFT adapter | `artifacts/adapters/sft/exp_sft_0001/` | COND | 研究产物；公开分发需另核许可与体积 |
| 16 | DPO adapter | `artifacts/adapters/dpo/exp_dpo_0001/` | COND | 同上；meets_target_scale=false |
| 17 | 盲审原始包 | `runs/audits/audit_blind_s46_0001/` | PRIV | 盲底 `private/blinding_key.json` 不可公开 |
| 18 | 密钥 / private.env | `runs/system/private.env` | PRIV | 永不入公开包 |
| 19 | 公开托管入口 | — | COND | **未提供**；默认录像+仓库+复现包 |
| 20 | 可调用应用 | UI/API via 隧道 | PASS | 截图不替代；S48 serve 抽验 |
| 21 | 完成等级判定 | `repo/docs/delivery/completion_levels.md` | PASS | 分项 YES/PARTIAL；总判定 preview |
| 22 | 面试笔记 | `repo/docs/delivery/interview_notes.md` | PASS | 问答绑定真实路径 |
| 23 | S50 Release | `artifacts/releases/rel_s50_e0_0001/` | PASS | 含完成等级+面试+checksums |
| 24 | Git 标签 | `v1.0.0-preview` | PASS | 本地 tag；远程 URL NOT_REGISTERED |

## 公开包 vs 私有备份

| 公开包可含 | 私有备份另含 |
| --- | --- |
| 源码、`examples/`、文档卡、报告表、探针摘要、checksums | 完整评测 jsonl、盲底、账单明细、SSH 身份、原始未脱敏导出 |
| 构建/复现说明、完成等级、面试笔记 | 全量 adapter 权重（若体积/许可限制则仅索引+哈希） |

**不得声称「全部开源」**：原始结果与盲审底未完全公开；原因见上表 PRIV/COND。

## 降级声明

- 产品路径与形式化评测：**已交付（E0）**。  
- 训练版发布门槛：**未过** → E1/E2 保留为负结果。  
- 目标偏好规模：**未达**（315/89）。  
- 公开在线服务：**未提供** → 不影响本地/本人隧道已验证事实。  
- 版本标签：**`v1.0.0-preview`**，不是无条件 v1.0.0。

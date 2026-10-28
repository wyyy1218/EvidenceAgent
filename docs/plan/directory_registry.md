# EvidenceAgent 目录与产物登记

> 建立步骤：S02｜更新日期：2026-10-26  
> 权威树：`docs/plan/execution_plan.md` 第 0 节（已含 Rule 四文件修订）  
> 新增公共目录或协议类别前须先更新本表。

## 1. 根路径记号

| 记号 | 相对 WORK_ROOT | 入 Git | 公开 | 可重建 |
| --- | --- | --- | --- | --- |
| R/ | repo/ | 是（仓库本身） | 代码与脱敏文档可公开 | 源码可重建；大文件索引不可替代实体 |
| E/ | envs/ | 否 | 否 | 是（按 locks） |
| M/ | models/ | 否 | 否（权重复制受限） | 是（按 revision 重下） |
| D/ | data/ | 否（整目录）；小夹具可进 R/tests/fixtures | 按许可逐项 | 部分可重建 |
| A/ | artifacts/（WORK_ROOT） | 否 | 发布包脱敏后可部分公开 | 检查点通常不可廉价重建 |
| L/ | runs/ | 否（整目录）；步骤验收摘要可引用 | 脱敏后部分 | 日志不可伪造重建 |

本地准备区 WORK_ROOT：`d:\1-实习\项目\EvidenceAgent`（local_prep）。AutoDL WORK_ROOT（2026-10-26 挂载已核）：`/root/autodl-tmp/evidence-agent`；数据盘仅 **50GiB**，S05 容量门禁 FAIL，见 `paths.yaml` 与 `L/steps/S05/a001/`。

## 2. Rule 入口（固定）

| 路径 | 用途 | 入 Git | 公开 |
| --- | --- | --- | --- |
| R/Rule/README.md | 规范入口（替代 project_rules.md） | 是 | 内部；公开包需脱敏审查 |
| R/Rule/HANDOFF.md | 当前交接快照 | 是 | 同上 |
| R/Rule/CHANGELOG.md | 变更与 provenance | 是 | 同上 |
| R/Rule/REMOTE.md | 远程实例登记 | 是 | 敏感字段公开前脱敏 |

不得再建 `rule/`、`rules/` 或第五份总规则正文。

## 3. 仓库内主要类别

| 类别 | 目录／命名模板 | 入 Git | 公开 | 可重建 |
| --- | --- | --- | --- | --- |
| 业务配置 | R/configs/project.yaml | 是 | 是（无密钥） | 是 |
| 路径配置 | R/configs/paths.yaml | 是 | 是（无绝对私有密钥） | 是 |
| Schema／提示 | R/configs/schemas/、prompts/ | 是 | 是 | 是 |
| 环境锁 | R/locks/{app,infer,train,judge}.txt | 是 | 是 | 用于重建 E/ |
| 应用源码 | R/src/evidence_agent/** | 是 | 是 | 是 |
| 基线 | R/baselines/{static_rag,react,deepagents_research}.py | 是 | 是 | 是 |
| 训练／评测代码 | R/training/**、R/evaluation/** | 是 | 是 | 是 |
| 上游快照 | R/third_party/deepagents/ | 是 | 保留 MIT 声明 | 是（按固定 commit） |
| 第三方声明 | R/THIRD_PARTY_NOTICES.md | 是 | 是 | 是 |
| 大文件索引 | R/artifacts/artifact_index.json | 是 | 是（仅索引） | 索引可重建，实体在 A/ |
| 文档计划 | R/docs/plan/* | 是 | 是 | 是 |
| 原说明归档 | R/docs/source/project_spec_v1.0.md | 是 | 是 | 否（原字节归档） |
| 决策 | R/docs/decisions/* | 是 | 审查后 | 是 |
| 架构说明 | R/docs/architecture/* | 是 | 是 | 是 |
| 示例 | R/examples/** | 是 | 仅已脱敏 | 是 |
| 测试夹具 | R/tests/fixtures/** | 是 | 仅公开小样本 | 是 |
| 私有密钥 | L/system/private.env | **否** | **否** | 否 |
| 步骤验收 | L/steps/<step_id>/<attempt_id>/{acceptance.md,evidence_index.json,failure.md} | 否（在 L/） | 可摘录到文档 | 否 |
| 探针 | L/probes/<probe_id>/ | 否 | 脱敏后 | 部分 |
| 轨迹／分支 | L/trajectories|branches/<collection_id>/ | 否 | 脱敏后 | 否 |
| 训练日志 | L/training/<experiment_id>/ | 否 | 摘要可公开 | 否 |
| 评测原始 | L/evaluation/<evaluation_id>/ | 否 | 脱敏后 | 否 |
| 账本 | L/billing/ | 否 | 否（金额敏感） | 否 |
| 原文／索引 | D/{raw,snapshots,normalized,chunks,indexes}/<id>/ | 否 | 按许可 | 部分 |
| 任务数据 | D/tasks/{hotpotqa,chinese}/<dataset_id>/ | 否 | 按许可 | 构建脚本可重建 |
| SFT/DPO 数据 | D/sft|dpo/<dataset_id>/ | 否 | 按许可 | 否（轨迹派生） |
| Manifest | D/manifests/<manifest_id>.json | 建议同步副本到 R 或发布包 | 是 | 是 |
| 模型权重 | M/<component>/<revision>/ | 否 | 否 | 是（重下） |
| 适配器实体 | A/adapters/{sft,dpo}/<experiment_id>/ | 否 | 按发布授权 | 需训练重跑 |
| 报告／发布 | A/reports|releases/<id>/ | 否 | 发布包审查后 | 部分 |

## 4. ID 命名

- 步骤：`S01`—`S50`；尝试：`a001`、`a002`
- 其他：类型前缀 + 固定宽度序号，如 `exp_sft_0001`、`eval_main_0001`、`mf_upstream_0001`
- 禁止：`final_final`、`new_results`、以聊天轮次或机器用户名命名正式对象

## 5. 禁止的同义平行目录

不得新建未登记的 `results/`、`output/`、`new_data/`、`latest2/` 等。确需调整：先写 decision_log，更新本表与 paths.yaml，再迁移。

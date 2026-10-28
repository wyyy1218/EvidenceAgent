# EvidenceAgent

面向文档与网页的**可追溯证据研究助手**：上传语料 → 受控多步检索/阅读 → 证据台账与引用 → 在预算内给出可导出答案（或明确无答案/冲突）。

工程规格见 `docs/source/project_spec_v1.0.md`；步骤进度见 `docs/plan/progress.md`。本文件面向**首次来访者**，不复制整篇执行方案。

本目录是 `WORK_ROOT/repo/` 下的唯一源码树。环境、模型、数据与运行记录在仓库外：`envs/`、`models/`、`data/`、`artifacts/`、`runs/`。

## 当前真实状态（2026-10-28）

| 项 | 事实 |
| --- | --- |
| 步骤 | **S01—S50 PASS**（执行链结束） |
| 发布系统 | **E0**（基座路由；Writer/Verifier 不走决策 adapter） |
| 版本标签 | **`v1.0.0-preview`**（非无条件 v1.0.0；见完成等级） |
| E1 / E2 | 已训练并评测，**未入选发布**（research_only / evaluated_not_released） |
| 主实验 | 6×300；正式报告 `artifacts/reports/rpt_s47_0001/` |
| 公开托管 | **未提供**；默认交付 = 仓库 + 复现说明 + 脱敏录像 |
| 本人访问 | SSH 隧道转发 UI `6006` / API `6008`；vLLM 仅 `127.0.0.1:8001` |
| 完成等级 / 面试 | `docs/delivery/completion_levels.md`、`interview_notes.md` |

## 真实功能（可调用，非截图）

- 上传与解析 PDF/文本；版本集锁定与去重  
- 混合检索 + 五动作受控循环 + 证据台账 / 冲突标记  
- 硬预算与取消/恢复；结果导出（`answer.json` + 引用 + Markdown）  
- 统一 CLI：`python -m evidence_agent.cli`（ingest / serve / evaluate / report / backup）

演示顺序见 `docs/delivery/demo_script.md`；API 烟测见 `examples/requests/`。

## 统一 CLI

```bash
export WORK_ROOT=/root/autodl-tmp/evidence-agent   # AutoDL 数据盘示例
cd "$WORK_ROOT/repo"
"$WORK_ROOT/envs/app/bin/python" -m evidence_agent.cli --help
```

| 命令 | 作用 |
| --- | --- |
| `… init` | 建目录、迁移 SQLite、检查 `private.env` 模板 |
| `… doctor --all` | 环境/模型探针（付费外部探针会先提示） |
| `… ingest --project demo --path examples/docs` | 解析入库 |
| `… serve start\|stop\|status` | UI/API/Worker；默认同管 vLLM |
| `… data build\|trajectories\|preferences` | 数据入口（正式集已冻结，慎重建） |
| `… train sft\|dpo` | 训练入口（正式训练有门槛；默认 dry-run 说明） |
| `… evaluate --split dev` / `… evaluate --split test --frozen` | 评测契约 |
| `… report` | 从原始结果出报告（不手填） |
| `… backup` | SQLite 一致快照 + 关键产物哈希 |

## 干净环境启动

1. 准备 `WORK_ROOT`，同步本仓库到 `$WORK_ROOT/repo`。  
2. `bash scripts/setup_envs.sh`（锁文件 `locks/*.txt`；可复用 `envs/cache/`）。  
3. `scripts/download_models.py` 或离线核验 `models/<role>/<revision>`。  
4. 写入 `runs/system/private.env`（`EVIDENCE_AGENT_API_TOKEN`、`EVIDENCE_AGENT_UI_PASSWORD`；**勿提交**）。  
5. `python -m evidence_agent.cli init`  
6. `python -m evidence_agent.cli serve start`  
7. 本人访问：`ssh -N -L 6006:127.0.0.1:6006 -L 6008:127.0.0.1:6008 evidence-agent-autodl` → 浏览器 `http://127.0.0.1:6006`。

关机：先 `serve stop`，再按云厂商流程关机；访问说明见 `docs/operations/access.md`。`Dockerfile` 仅为应用层补充，不以 Docker-in-Docker 为 AutoDL 假设。

## API 示例

```bash
curl -s http://127.0.0.1:6008/healthz
curl -s -H "Authorization: Bearer $EVIDENCE_AGENT_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d @examples/requests/ask.json \
  http://127.0.0.1:6008/v1/ask
```

完整烟测：`bash examples/requests/demo_smoke.sh`。

## 实验结果与限制（摘要）

正式数字以 `artifacts/reports/rpt_s47_0001/report.md` 为准（由原始评测重算，不手填）。

| 系统 | Auto Q (n=300) | 发布 |
| --- | ---: | --- |
| B0 | 0.279 | 对照 |
| B1 | 0.000（300 failed_policy） | 对照 |
| B2 | 0.127 | 对照 |
| **E0** | **0.247** | **发布** |
| E1 | 0.244 | 否（G 门槛） |
| E2 | 0.245 | 否（门槛 + 偏好规模） |

限制（完整见 `docs/evaluation/limitations.md`）：

- 单人盲审、无独立复标；B1 全失败使盲审差距偏「能否跑通」。  
- 预训练污染无法完全排除；DRBench/live 为小规模自定义子集。  
- 公开托管未提供；不得把 AutoDL 私人入口写成公网演示。  
- 不得宣称目标偏好规模 600/100 已完成，或训练版已入选发布。

## 数据与模型卡

| 卡 | 路径 |
| --- | --- |
| 数据（Hotpot 派生） | `docs/data/data_card.md` |
| 中文来源 / 任务 | `docs/data/chinese_sources_card.md`、`chinese_tasks_card.md` |
| 基座 / SFT / DPO | `docs/models/base_model_card.md`、`sft_model_card.md`、`dpo_model_card.md` |
| 交付清单 | `docs/delivery/delivery_checklist.md` |
| 完成等级 | `docs/delivery/completion_levels.md` |
| 面试笔记 | `docs/delivery/interview_notes.md` |
| Release | `artifacts/releases/rel_s50_e0_0001/`（WORK_ROOT） |

## 文档入口

| 入口 | 路径 |
| --- | --- |
| 工程规则 | `Rule/README.md` |
| 交接 | `Rule/HANDOFF.md` |
| 访问 / 备份 / 复现 | `docs/operations/{access,backup_restore,reproduce}.md` |
| 发布选择 | `docs/evaluation/release_selection.md` |
| 第三方 | `THIRD_PARTY_NOTICES.md` |

## 许可

代码计划 Apache-2.0；上游见 `THIRD_PARTY_NOTICES.md`。数据与模型许可以各数据卡 / 模型卡与 `data/manifests/` 为准，**不得**用项目许可证覆盖上游。

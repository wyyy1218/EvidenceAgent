# 基线与优化版比较矩阵（S03 边界 + S22 可运行状态）

> 建立步骤：S03｜可运行更新：S22｜更新日期：2026-10-26  
> 上游钉扎：`deepagents==0.7.32` @ `e85c6b98087861512d2c5240305e16cfac68a746`  
> 本文件固定“谁负责什么”，并记录 B0/B1/B2/E0 实测可运行状态。

## 1. 六系统角色

| ID | 路径 | 控制器 | 证据管理 | 策略训练 | 比较性质 | S22 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| B0 | `baselines/static_rag.py` | 无（静态 Top-6） | 最终引用最低能力 | 无 | 动态循环必要性 | **可运行** |
| B1 | `baselines/react.py` | 基座 + 滚动历史 ReAct | 最低来源日志与最终引用 | 无 | 策略基线 | **可运行** |
| B2 | `baselines/deepagents_research.py` | 官方 deep_research **适配版** | 适配后统一工具与计账 | 无 | 应用级 vs 开源起点 | **可运行（适配循环）** |
| E0 | `baselines/e0_runner.py` → `agent/graph.py` | 自建受控 LangGraph | 可追溯台账 + 确定性打包 | 无 | 隔离证据管理 | **可运行** |
| E1 | 同上 + SFT adapter | E0 图 | 同 E0 | QLoRA SFT | 隔离监督训练 | 未完成（S32+） |
| E2 | 同上 + DPO adapter | E0 图 | 同 E0 | SFT 后 DPO | 隔离偏好训练 | 未完成（S38+） |

严格模块消融链：**B1 → E0 → E1 → E2**。B2 内部组织可不同，属应用级比较，不强制改成单控制器。**禁止用 E0 别名冒充 B2。**

## 2. 公平比较：共同冻结 vs 允许差异

### 2.1 共同冻结（可比运行中必须一致）

| 项 | 约定 |
| --- | --- |
| 外部工具 | 仅 `local_search` / `web_search` / `read_evidence`（`tools/dispatch.py`） |
| 检索器 | HybridRetriever（BM25+dense+RRF+rerank）；夹具可用 HashEmbedder |
| Writer / Verifier | 固定提示 `configs/prompts/{writer,verifier}.md`；`adapter_id=None`（base） |
| 硬预算 | `BudgetState` / `BudgetConfig`（工具次数、Token、墙钟、最终输出预留 1536） |
| 资料 / 快照 | 同一 `project_id` 与 `version_set` |
| 权限 | 无 shell；网页受 `allow_web` + 三模式约束 |

### 2.2 允许差异（必须可定位）

| ID | 控制器输入 | 记忆管理 | 内部组织 |
| --- | --- | --- | --- |
| B0 | 无策略循环 | 无 | 单次检索→读 Top-6→写 |
| B1 | 滚动 action/observation 历史 JSON | **无** `pack_visible_state`；`source_log` 最低日志 | 单控制器 ReAct |
| B2 | 编排提示 + 子任务主题 | 子代理发现汇总；非 E0 台账打包 | 编排器 + research 子代理（应用级） |
| E0 | `pack_visible_state` 确定性打包（证据卡等） | 持久证据台账 + VisibleState | 单控制器 LangGraph |

## 3. 上游（B2）与个人实现分界

### 保留／适配（上游）

- 固定提交下 `third_party/deepagents/examples/deep_research/` 作为 B2 起点
- Harness、子任务/委托、示例提示意图 → **不得**写成个人从零原创
- B2 适配：三工具统一、去 shell、硬预算与完整内部协调计账（`b2_meter`：编排 LLM、子代理 LLM、子任务数、协调步、工具调用）

### 个人实现

状态与动作协议、受控图、证据台账、确定性打包、混合检索、预算账本、Writer/Verifier、训练与评测、UI/API — 见仓库 `src/evidence_agent/`。

### B2 上游修改清单（S22）

1. 外部工具 → 统一三工具  
2. 移除 shell / 无关能力  
3. 模型路由 → 本项目 `LLMClient`（base）  
4. 全部内部协调与子任务计入 `b2_meter` + `UsageLedger`  
5. 最终答案经共享 Writer/Verifier 以保留可核对引用  
6. `deepagents` 包若未安装：仍运行忠实多阶段适配循环；**不**回退为 E0

## 4. 输出协议（四系统探针核对）

每系统结果至少包含：`system`、`status`、`run_id`、`usage`（逻辑工具 / Token / 预算快照）。  
B1 另含 `source_log`、`memory_mode=rolling_history`。  
B2 另含 `adapter`、`upstream`、`b2_meter`、`memory_mode=deep_research_subagents`。  
E0 另含 `memory_mode=evidence_ledger_packed`。

## 5. S22 验收边界

| 项 | 状态 |
| --- | --- |
| 固定提交可定位且文件来自该提交 | 已完成（S03） |
| 借鉴与重写边界成文 | 本文件 + THIRD_PARTY_NOTICES |
| B0/B1/B2/E0 代码可运行 | **已完成（S22；Mock 夹具 + 入口 CLI）** |
| 四系统同夹具协议字段一致、成本不漏算 | 见 `tests/integration/test_s22_baselines.py`、`L/probes/s22/` |
| 六系统主实验 | **未完成（S42）** |

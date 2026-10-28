# Third-Party Notices — EvidenceAgent

> 更新日期：2026-10-25｜对应步骤：S03  
> 项目代码计划采用 Apache-2.0；下列上游与数据/模型许可不得被统一抹平。

## 1. Deep Agents（上游研究示例）

| 项 | 值 |
| --- | --- |
| 仓库 | https://github.com/langchain-ai/deepagents |
| 包版本 | `deepagents==0.7.32` |
| 固定提交 | `e85c6b98087861512d2c5240305e16cfac68a746` |
| 许可 | MIT（Copyright (c) LangChain, Inc.） |
| 快照位置 | `third_party/deepagents/` |
| 钉扎说明 | `third_party/deepagents/UPSTREAM_PIN.txt` |
| 文件清单哈希 | `D/manifests/mf_upstream_deepagents_0001.json` |

### 本项目采用的文件（仅该提交）

- `examples/deep_research/agent.py`
- `examples/deep_research/utils.py`
- `examples/deep_research/research_agent/`（prompts、tools、`__init__`）
- `examples/deep_research/README.md`、`pyproject.toml`、`langgraph.json`、`.env.example`
- `examples/deep_research/research_agent.ipynb`、`uv.lock`（上游示例附带）
- 上游根 `LICENSE`、`README.md`（同提交副本）

**不从 `main` 或其他标签混入文件。**

### 上游原有功能（不得写成个人从零实现）

规划/编排入口、`create_deep_agent` harness、子 Agent 委托、示例内 Tavily 搜索与 think 工具、示例提示与 LangGraph 部署配置。

### 本项目拟修改意图（B2 适配版）

适配位置：`baselines/deepagents_research.py`（**S22 已实现**）。

- 将外部工具接入统一的 `local_search` / `web_search` / `read_evidence`
- 移除任务不需要的 shell 等能力
- 外部调用计入同一硬预算与用量账本（含编排器/子代理 LLM 与子任务 `b2_meter`）
- 保留为应用级比较基线；不强制改成 E0 单控制器结构；禁止用 E0 别名冒充 B2

完整 MIT 许可正文见 `third_party/deepagents/LICENSE`。分发含上游实质内容时须保留版权与许可声明。

## 2. 借鉴边界（不直接复制未明确许可的代码）

| 来源 | 用法 | 复制代码？ |
| --- | --- | --- |
| A-RAG（Ayanami0730/arag） | 仅借鉴分层检索与阅读接口边界 | **否**（许可结论不足） |
| Search-R1 | 阅读轨迹/掩码原则与面试学习 | **否**；不安装其旧 veRL/训练栈 |
| Open Deep Research 等归档示例 | 架构阅读 | **否**作为必装依赖 |
| ALCE / MiniCheck 等方法 | 指标与英文辅助评分定义 | 按各自许可引入评测环境，不迁移论文分数 |

论文用于方法解释；**不**将其榜单分数作为本项目预期成绩。

## 3. 其他将单独登记的许可对象

模型（Qwen、bge、MiniCheck）、HotpotQA（CC BY-SA 4.0）、中文技术文档仓库等，在 S06 / S25 / S26 的 manifest 与数据卡/模型卡中记录；本文件在引入时追加条目。

## 4. 个人实现边界（摘要）

本项目自行完成：状态与动作协议、证据台账、混合检索接入、预算执行器、训练数据、SFT/DPO、受控 LangGraph 循环（E0+）、评测适配器、应用界面与部署。详见 `docs/architecture/baseline_matrix.md`。

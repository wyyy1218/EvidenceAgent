# 标注协议（S24 冻结）

> 冻结日期：2026-10-26｜在出题与查看模型最终测试结果之前冻结  
> 依据：项目说明 §14、§17.3；执行方案 S24

## 1. 每题字段

| 字段 | 说明 |
| --- | --- |
| `task_id` | 稳定唯一 ID（含来源前缀，如 `hpqa_…` / `zh_…`） |
| `split` | `train` / `dev` / `test` |
| `question` | 面向策略的问题文本 |
| `requirements` | **在线**需求项（由问题与固定流程抽出；**不含答案**） |
| `allowed_snapshot_ids` | 允许检索的资料/快照集合 |
| `answerability` | `answerable` / `partial` / `unanswerable` |
| `gold_claims` | 离线金标准原子事实（**永不入策略输入**） |
| `gold_support_spans` | 支持原文位置（版本/页/行/句号） |
| `expected_status` | `answered` / `partial` / `insufficient_evidence` / `conflicting_evidence` |
| `rubric` | 判分细则（中文逐项；英文可引用 EM/F1 绑定） |
| `difficulty` | `easy` / `medium` / `hard` |
| `source_versions` | 资料版本指纹 |
| `generation_model` | 出题所用模型（若人工则为 `human`） |
| `review_status` | `draft` / `reviewed` / `sealed` |
| `license_refs` | 数据许可引用（如 HotpotQA CC BY-SA 4.0） |

### Gold 与策略边界

- **在线 `requirements`**：仅描述需核实的问题侧面，不得粘贴 gold 答案或支持句正文作为“需求”。  
- **`gold_*` 字段**：只交给离线评测适配器与轨迹过滤；训练/开发/测试封存流程见 §5。  
- 教师出题与最终评分使用**分离模板**（`configs/prompts/task_generation.md` vs `offline_scoring.md`）。

## 2. 标注类型

### 2.1 原子事实

一条 gold claim = 一个可独立核对的事实陈述 + 至少一个 `gold_support_spans`。联合多文档结论的 claim 绑定**完整 evidence set**，不要求单篇独自蕴含。

### 2.2 版本 / 适用范围

冲突或版本题必须在 claim.scope 或 rubric 中保留双方条件；不得擅自消解为唯一事实。

### 2.3 联合证据

多来源比较题：rubric 列出每个需求项及最少来源数；漏引关键来源扣覆盖分。

### 2.4 无答案 / 部分回答

- `unanswerable`：允许语料内无法支持；期望 `insufficient_evidence`；伪造确定结论 → Q=0。  
- `partial`：仅部分需求可答；期望 `partial`；超范围编造扣分。

## 3. 判分示例（≥2）

### 示例 A — 可回答英文事实（HotpotQA 风格）

- Question: “Which company founded X also owns Y?”  
- Gold claims: 两条原子事实 + 支持句位置。  
- Expected: `answered`；EM/F1 对规范化答案；G 按引用是否落在 gold spans（允许人工复核替代 span）。

### 示例 B — 中文证据不足

- Question: 问资料中不存在的门店地址。  
- Allowed snapshots: 故意移除关键段落后的包。  
- Expected: `insufficient_evidence`；若模型给出确定地址 → 失败；正确报告不足 → Q=1。

## 4. 近重复检查（分割前冻结）

| 规则 | 阈值 | 处理 |
| --- | --- | --- |
| 问题规范化（NFKC、小写、去多余空白与首尾标点）后字符 **3-gram Jaccard** | ≥ **0.85** 视为近重复 | 后抽中的样本跳过 |
| 短题（规范化后 ≤20 字符） | ≥ **0.75** + **强制人工复核** | 默认跳过或复核后保留一条 |
| 支持标题集合跨 split 交集 | 非空 | 后抽样本跳过 |
| Context 段落规范化哈希碰撞 | 跨 split 同段 | 记入泄漏报告；按隔离规则处理 |

阈值**不得**在看到测试效果后放宽。小样本校验记录见 `L/steps/S24/`。

## 5. 访问流程

1. **题目隔离**：按 split 目录分置；测试包默认只读权限给离线评测。  
2. **金标准审核**：开发/测试人工核验；训练分层抽查。双审争议保留争议记录与裁决依据。  
3. **训练过滤**：轨迹结束后用 gold 过滤，不在策略输入中暴露。  
4. **开发选型**：仅用开发集选发布候选（S40）。  
5. **测试封存**：最终测试 gold 只交离线评测适配器；禁止用于提示调试或模型选择。

## 6. 规模目标（提醒）

| 来源 | train | dev | test |
| --- | ---: | ---: | ---: |
| HotpotQA 派生 | 600 | 100 | 200 |
| 中文技术核验 | 240 | 60 | 100 |
| 合计 | 840 | 160 | 300 |

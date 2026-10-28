# S33 开发筛选预登记

> 状态：CANDIDATES_FROZEN（2026-10-27，S32 PASS 后、任何 S33 评分前补录实际 step）  
> 原则：候选清单、40 题子集和选择规则在看到任何 S33 分数前登记；之后不得追加有利候选。

## 1. 候选检查点

S32 使用 `save_steps=100`、`save_total_limit=2`，并在训练结束保存最终 adapter。`save_total_limit` 仅保留了 `checkpoint-600` 与 `checkpoint-616`；`checkpoint-400`/`checkpoint-500` 已被 trainer 清理，**不得**事后追加为候选。

冻结候选集（评分前登记）：

| 系统名 | 路径 | adapter SHA-256 | vLLM LoRA 名 |
| --- | --- | --- | --- |
| `e0` | 同一基座、无 adapter；Writer/Verifier 均走 base | — | — |
| `e1_ckpt_600` | `runs/training/exp_sft_0001/checkpoint-600/` | `8307f2e46149d92f4a53e35bb0f369a13f281a528efdb179f42e97b98ad73a12` | `e1_ckpt_600` |
| `e1_final` | `artifacts/adapters/sft/exp_sft_0001/`（与 `checkpoint-616` 字节相同） | `4e8b60a07b8d65f7e66fb547a71d1658bfb94531d4e0c0156589e748fe6391ce` | `sft_e1` |

说明：`checkpoint-616` 与 `e1_final` 哈希一致，只保留正式 `e1_final`，不重复跑两个同权重点。不把 S31 探针 adapter、临时 probe LoRA 或未保存中间 step 作为候选。

## 2. 40 题开发子集

- 中文 dev 60 题中取 24 题：`direct_fact`、`multi_source`、`version_conflict`、`insufficient_evidence` 各 6 题。
- HotpotQA dev 100 题中取 16 题。S25 distractor dev 的 difficulty 实际以 `medium` 为主；若 easy/hard 桶不足，按 `sha256("s33_dev40:"+task_id)` 排序的剩余 dev 题补足，并在 `subset.json` 的 `fallback` 中登记。
- 精确 task_id 列表由 `run_tasks` 在评分前写入 `runs/evaluation/eval_dev40_s33_0001/subset.json`；本文件登记规则，不因分数修改规则。
- 160 题完整 dev 使用全部 60 中文 + 100 HotpotQA dev 题，不另选子集。

## 3. 选择规则

1. 在 40 题上比较所有预登记候选与 E0 的 `Q_mean`。
2. 取 `Q_mean` 距最高值不超过 0.01 的候选。
3. 在其中取 `G_gold_anchored_mean` 距最高值不超过 0.01 的候选；若 gold-anchored G 全为空，改用 `G_verifier_mean`。
4. 在其中取平均输入+输出 Token 最少者。
5. 完全同分优先正式 `e1_final`，再按系统名排序。

选择结果写入 `runs/evaluation/eval_dev40_s33_0001/selection.json` 与 `selection.md`；随后只对选中的 E1 和 E0 跑 160 题完整 dev。

## 4. 指标与边界

- Q：中文用 S24/S28 rubric；英文用 EM/F1（同时报告 answer-contains-gold）。
- G：报告 `G_verifier` 与 `G_gold_anchored`；后者要求 claim 与 quote 有词汇重叠且引用命中 gold support span 的 doc/title。最终 G 仍按 S40 的独立 judge/人工协议，不把本筛选 G 冒充最终 G。
- 成本：policy/writer/verifier token、工具调用、墙钟时间。
- 本阶段是模型级端到端 dev harness：真实语料、真实工具、同一 packer、同一 Writer/Verifier、代码内引用完整性检查；不经过 UI/DB，不等同于 S40 产品级主实验。
- 不查看 test，不针对 test 调参；若效果下降保留真实结果。

## 5. 结果（S33 a001，2026-10-27）

- 40 题：`runs/evaluation/eval_dev40_s33_0001/` — e0 Q=0.317；e1_ckpt_600/e1_final Q=0.3503。
- 选中 E1：`e1_final`（`selection.json`）；adapter `sft_e1` / SHA `4e8b60a0…`。
- 160 题：`runs/evaluation/eval_dev160_s33_0001/` — e0 Q=0.2479；e1_final Q=0.2512；action_valid 0.9469 / 0.9625。
- 效果门槛与发布选择留给 S34/S40；本步只确认可运行、可追溯的 E1 候选及同集 E0 对照。
- 备注：首轮 E0 因基座把散文写入 `reason_code` 导致几乎全 `failed_policy`，已用产品侧 coerce + 提示修正后重跑；损坏结果归档在 `runs/evaluation/_broken_e0_pre_fix_*`。

---

# S39 DPO 候选预登记（评分前）

> 状态：CANDIDATES_FROZEN（2026-10-27，S38 产物就绪后、任何 S39 评分前登记）  
> 原则：候选、40 题子集规则与选择规则在看到任何 S39 分数前冻结；不得追加有利候选。  
> `meets_target_scale=false`（train=315 ≠ 600）。

## S39.1 候选检查点

| 系统名 | 路径 | 说明 | vLLM LoRA 名 |
| --- | --- | --- | --- |
| `e0` | 同一基座、无 adapter | 对照；可复用 `eval_dev160_s33_0001` 若快照未变 | — |
| `e1_final` | `artifacts/adapters/sft/exp_sft_0001/` | S34 `research_only`；同条件对照 | `sft_e1` |
| `e2_final` | `artifacts/adapters/dpo/exp_dpo_0001/` | S38 正式 DPO 最终 adapter | `dpo_e2` |

不把 S37 探针 adapter、未保存中间 step 或未预登记 checkpoint 作为候选。DPO 最多 2 个训练 checkpoint；若实际保留且哈希已在评分前写入本表，方可加入，否则仅 `e2_final`。

## S39.2 子集与选择规则

- 40 题 / 160 题规则与 S33 相同（`sha256("s33_dev40:"+task_id)` 子集；完整 60 中文 + 100 HotpotQA）。
- 40 题上比较预登记候选；选出 E2 后与同条件 E0（及需要时的 E1）跑 160。
- 选择次序（40 题）：Q 距最高 ≤0.01 → G 距最高 ≤0.01 → 更少 token；全同优先 `e2_final`。
- 发布门槛与唯一发布选择留给 S40；本步不要求 E2 优于 E1。

## S39.3 结果（S39 a001，2026-10-27）

- 40 题：`eval_dev40_s39_0001/` — e0 Q=0.3295；e1_final Q=0.3705；e2_final Q=0.3655 → 选中 `e2_final`。
- 160 题：`eval_dev160_s39_0001/` — e0 Q=0.2614 G=0.3971；e1_final Q=0.2613 G=0.2892；e2_final Q=0.2616 G=0.3269；action_valid 0.9969 / 0.9875 / 0.9925。
- 备注：首轮 `--subset 160` 非法退出后改为 `--subset all` 续跑；不要求 E2 优于 E1。

---

# S40 唯一发布选择（决策）

> 状态：DECIDED（2026-10-27，`runs/steps/S40/a001/`）  
> 原则：相对 E0 门槛（Q/G/false_answer Δ≤0.02，合法率≥0.98）；再 Q≤0.01 → G≤0.01 → 更少 token；全同优先 SFT→DPO→E0。不看 test。

## 决策

| 系统 | 门槛 | 结果 |
| --- | --- | --- |
| `e0` | 基线 | **发布** |
| `e1_final` | research_only（S34）且 G↓0.1079 | 淘汰 |
| `e2_final` | G↓0.0702（>0.02） | 淘汰 |

**chosen_system = e0**。证据：`runs/steps/S40/a001/selection.json`；源 `eval_dev160_s39_0001/summary.json`。

## S39.3 结果（S39 a001，2026-10-27）

- 40 题：`runs/evaluation/eval_dev40_s39_0001/` — e0 Q=0.3295；e1_final Q=0.3705；e2_final Q=0.3655。选中 E2：`e2_final` / `dpo_e2`。
- 160 题同条件：`runs/evaluation/eval_dev160_s39_0001/`

| 系统 | Q | G_gold | answered_false | action_valid | tokens(in+out) |
| --- | ---: | ---: | ---: | ---: | ---: |
| e0 | 0.2614 | 0.3971 | 0.3063 | 0.9969 | 6059.6 |
| e1_final | 0.2613 | 0.2892 | 0.2562 | 0.9875 | 8348.4 |
| e2_final | 0.2616 | 0.3269 | 0.2687 | 0.9925 | 5370.5 |

- `meets_target_scale=false`；`t24` 路由探针 PASS。E2 可运行且与 E0/E1 同条件；不要求优于 E1。
- 备注：160 题为同批次重跑（见 `reuse_note.json`），非仅引用 S33 摘要。

---

# S40 唯一发布选择（仅开发集）

> 状态：PASS（2026-10-27，`runs/steps/S40/a001/`）  
> 原则：只看 160-dev；不看 test；E0 始终回退基线。

## S40.1 门槛与淘汰

相对 E0：Q 降幅 ≤0.02；G_gold 降幅 ≤0.02；错误确定作答增幅 ≤0.02；动作合法率 ≥0.98；无越权/预算绕过（本轮由 T24/路由探针覆盖）。

| 系统 | 门槛 | 说明 |
| --- | --- | --- |
| e0 | 基线 | 始终合格回退 |
| e1_final | 淘汰 | S34 `research_only` + G↓0.1079 |
| e2_final | 淘汰 | G↓0.0702（>0.02）；Q/false/valid 均过 |

合格池仅 `['e0']` → **chosen_system = e0**。未查看 test。

## S40.2 结论

- 产品发布策略：**E0**（基座 + 公共 Writer/Verifier）。
- E1/E2 保留为研究候选与负结果证据；DPO 实验在数据/训练/开发评估齐全前提下视为完成，**不因未入选发布而删产物**。
- 证据：`runs/steps/S40/a001/selection.json`、`acceptance.md`；指标源 `eval_dev160_s39_0001/summary.json`。
- 下一步（已完成）：S41 最终冻结（以 E0 为发布策略）→ 见 `mf_s41_freeze_0001`；进入 S42。

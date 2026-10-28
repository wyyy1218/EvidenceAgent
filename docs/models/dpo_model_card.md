# DPO 模型卡（E2 候选）

> 状态：S39_EVALUATED_S40_NOT_SELECTED（2026-10-27）  
> 偏好规模：`dpo_s36_v1` train=315 / dev=89；**meets_target_scale=false**（≠600/100）。  
> Reference：冻结 SFT `exp_sft_0001`（非 base）。产品发布选择见 S40 → **E0**。

## 1. 标识

| 字段 | 值 |
| --- | --- |
| experiment_id | `exp_dpo_0001` |
| base | `Qwen/Qwen3-4B-Instruct-2507` |
| init SFT adapter | `artifacts/adapters/sft/exp_sft_0001/` SHA `4e8b60a0…` |
| DPO adapter 路径 | `artifacts/adapters/dpo/exp_dpo_0001/` |
| adapter SHA-256 | `011f3c14544ebb96762b6c77a818b5b6fd44d2ea670772630608836d8849ecbc` |
| vLLM adapter id | `dpo_e2` |
| preference_scope | 动作 JSON only（非整段轨迹） |

## 2. 数据与 reference

| 字段 | 值 |
| --- | --- |
| dataset_id | `dpo_s36_v1` |
| train / dev | 315 / 89 |
| reference | 双 adapter：`policy` + 冻结 `reference`，均自 SFT 初始化（PEFT 禁名 `train`） |
| cache | `data/dpo/dpo_s36_v1/reference_cache/`；键含 SFT SHA / tokenizer / 样本 / 掩码 |
| atol | `1e-3`（S37 抽检） |

## 3. 训练配置摘要

β=0.1、sigmoid、lr=5e-6、2 epoch、micro=1 / accum=8、prompt≤2880、completion≤192、seed=42、`precompute_ref_log_probs=true`。超参严格读 `training.dpo`。

## 4. 开发集结果（S39）

| 系统 | Q_mean | G_gold_anchored | answered_false | action_valid |
| --- | --- | --- | --- | --- |
| e0 | 0.2614 | 0.3971 | 0.3063 | 0.9969 |
| e1_final | 0.2613 | 0.2892 | 0.2562 | 0.9875 |
| e2_final | 0.2616 | 0.3269 | 0.2687 | 0.9925 |

证据：`eval_dev40_s39_0001/`、`eval_dev160_s39_0001/`。不要求优于 E1；同条件对照已跑。

## 5. 边界与发布

- 不得宣称目标偏好规模 600/100 完成。
- E1 为 `research_only`（S34 G 门槛 FAIL）。
- S40：E2 相对 E0 的 G 降幅 ≈0.070 > 0.02 → **不入选**；产品发布 **E0**。

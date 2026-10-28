# SFT 模型卡（E1 候选）

> 状态：S34_SETTLED_RESEARCH_ONLY（2026-10-27）  
> S34 四轴已结算：数据/训练/可调用通过；**效果门槛 FAIL**（G 相对 E0 降幅超限）。  
> 产品回退 **E0**；E1 仅作研究参考。DPO 允许在同一固定 SFT 上继续研究。

## 1. 标识

| 字段 | 值 |
| --- | --- |
| experiment_id | `exp_sft_0001` |
| base | `Qwen/Qwen3-4B-Instruct-2507` @ `cdbee75f17c01a7cc42f958dc650907174af0554` |
| adapter 路径 | `artifacts/adapters/sft/exp_sft_0001/` |
| adapter SHA-256 | `4e8b60a07b8d65f7e66fb547a71d1658bfb94531d4e0c0156589e748fe6391ce` |
| 训练步 | 616（2 epoch，有效 batch 16） |
| 保留检查点 | `checkpoint-600`（`8307f2e4…`）、`checkpoint-616`=final |
| vLLM adapter id | `sft_e1` |

## 2. 数据

| 字段 | 值 |
| --- | --- |
| dataset_id | `sft_s30_v1` |
| train / dev | 4917 / 930 |
| 掩码 | completion-only；S30 掩码审计 PASS |
| 泄漏 | S30 检查通过；不含 test 轨迹 |

## 3. 训练配置摘要

QLoRA 4-bit NF4 double-quant；LoRA r16/alpha32/dropout0.05；target q/k/v/o/gate/up/down；lr 1e-4；paged_adamw_8bit；max_length 3072。

## 4. 推理导出（S33）

- vLLM 0.10.2，BF16 基座，`--enable-lora --max-lora-rank 16`
- policy 请求 adapter ID；Writer/Verifier 明确走 base（T24）
- 量化训练路径 vs vLLM 路径动作级差异见 `runs/evaluation/eval_quant_probe_s33_0001/compare.json`

## 5. 开发集结果（S33 a001）

- 40 题筛选：选中 `e1_final`（Q=0.3503；E0=0.317；e1_ckpt_600 同分）
- 160 题完整 dev：E1 Q=0.2512 / action_valid=0.9625；E0 Q=0.2479 / action_valid=0.9469
- G_gold：E0 0.4043 → E1 0.2792（降幅 0.1251 > 0.02）
- answered_false：E0 0.2562 → E1 0.2313（改善）
- 详情：`runs/evaluation/eval_dev40_s33_0001/selection.json`、`eval_dev160_s33_0001/summary.json`

## 6. S34 结算

| 轴 | 结论 |
| --- | --- |
| data_target | PASS（4917 ≥ 2000） |
| training_process | PASS（S32） |
| adapter_callable | PASS（T24 + e1_final） |
| effect_gate | **FAIL**（G 降幅超限；Q/伪答/合法率可接受） |
| dpo_allowed | true（研究） |
| product_fallback | E0 |
| e1_release_status | research_only |

证据：`runs/steps/S34/a001/acceptance.md`、`evidence_index.json`。

# S41 正式运行清单（冻结）

- created_at: 2026-10-27T12:49:48.156952+00:00
- release_system: **e0**
- planned_formal_runs: **2544** (target 2544)
- looked_at_test_scores: false
- config_bundle_hash: `3c8df0d2dc80ff2c94d7d15273a11158c3fade6e6b3800b5af6065fa4a16e259`

## 批次

| batch | step | runs | notes |
| --- | --- | ---: | --- |
| `main_test300` | S42 | 1800 | Six systems × full test300; failures remain in denominator |
| `ablation_no_source_anchor` | S43 | 100 | Server keeps real sources for audit/scoring; only policy-visible anchors removed |
| `ablation_hide_visible_budget` | S43 | 100 | Hide budget fields in policy input; executor hard budget unchanged |
| `budget_curve_b4_b12` | S44 | 240 |  |
| `stability_seed43_44` | S44 | 240 | Not same-distribution replicates of temperature-0 main rows |
| `drbench12` | S45 | 24 | External custom subset; do not mix into main aggregates |
| `live20` | S45 | 40 | Live web; AB/BA adjacent; not mixed into main aggregates |

## 不含在 2544 内

- checkpoint screening
- DPO branch collection (≥2800 or more)
- pilot / probes
- dev evaluation (S33/S39)
- training runs
- infrastructure failure reruns (logged separately)

## 故障补跑

- **valid_low_score**: do_not_rerun_for_better_score
- **infrastructure_fault**: may_rerun_under_rule; keep original failure + extra cost
- **system_timeout_or_tool_fail**: remain_in_denominator; not silently dropped
- **missing_system_version**: report column incomplete; do not fill from other systems

## 子集前缀

- ablation100: `s41_ablation100`
- budget_stability60: `s41_budget_stability60`
- blind60: `s41_blind60`
- drbench12: `s41_drbench12` (IDS_PENDING_CATALOG)
- live20: `s41_live20` (PROTOCOL_FROZEN_TASKS_PENDING)


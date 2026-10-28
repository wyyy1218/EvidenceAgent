# Evaluation results (S47 rollup)

Authoritative report: `artifacts/reports/rpt_s47_0001/report.md`

# EvidenceAgent formal report (`rpt_s47_0001`)

- generated_at: `2026-10-28T07:17:54.136840+00:00`
- release_system (frozen): **e0**
- rule: all numeric tables recomputed from raw evaluation artifacts; no hand-filled scores
- scopes separated: frozen main test / ablations / budget-stability / external DRBench+live / blind human review

## 1. Main formal matrix (S42, n=300/system)

| system | n | Q | G_gold | G_ver | false_ans | tools | tokens | wall_s | errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| b0 | 300 | 0.2793 | 0.3367 | 0.7604 | 0.3167 | 4.83 | 1502.4 | 3.858 | 0 |
| b1 | 300 | 0.0 | None | None | 0.0 | 0.0 | 765.7 | 1.713 | 300 |
| b2 | 300 | 0.1273 | 0.1818 | 0.8545 | 0.03 | 3.75 | 798.0 | 4.061 | 5 |
| e0 | 300 | 0.2469 | 0.3816 | 0.8219 | 0.3233 | 4.1 | 6381.1 | 6.466 | 55 |
| e1 | 300 | 0.2444 | 0.312 | 0.7836 | 0.3267 | 4.82 | 8503.8 | 8.269 | 1 |
| e2 | 300 | 0.2446 | 0.3697 | 0.8564 | 0.2933 | 3.03 | 5286.6 | 5.924 | 0 |

Statuses are retained in `tables/main_s42_systems.json`. B1 is all-failed on this run.

## 2. Preregistered deltas (auto Q, task-paired)

- **main_auto_b1_to_e0**: mean=0.246921 95%CI=[0.223285, 0.271632] (n=300)
- **main_auto_e0_to_e1**: mean=-0.002484 95%CI=[-0.024552, 0.017492] (n=300)
- **main_auto_e1_to_e2**: mean=0.000152 95%CI=[-0.014681, 0.016855] (n=300)

Do not read a CI covering 0 as proven equivalence. E1/E2 remain non-release under S40 gate.

## 3. Ablations / budget / stability / external

- S43 ablation summary bound to `runs/evaluation/eval_ablation_s43_0001`
- S44 budget/stability tables: `artifacts/reports/rpt_s44_0001`
- S45 DRBench/live: not mixed into main; drbench systems=['b1', 'e0'], live systems=['b1_live']

## 4. Blind human review (S46)

- reviewer_mode: **single_author** (human); no inter-annotator agreement claimed
- input_human_q Δ(E0−B1)=0.3649383333333333 95%CI=[0.29490787500000004, 0.4362396666666665]
- author_audit_q Δ(E0−B1)=0.6333333333333333 95%CI=[0.55, 0.7166666666666667] (ordinal supplemental scale)
- B1 blind60: 60/60 failed_policy-style failures dominate the gap

## 5. Contribution vs phenomenon

- **ledger_packaging**: Evidence ledger / packing / citation anchors are part of the product path (E0).
  - evidence: S16-S18 steps, E0 main metrics in eval_main_s42_0001
- **SFT**: SFT adapter trained and evaluated; did not pass release gate vs E0 (research_only).
  - evidence: S32-S34, S40 release selection, main e1 vs e0 auto delta near 0 / not selected
- **DPO**: DPO run completed below target preference scale; not selected for release.
  - evidence: S35-S40, meets_target_scale=false history, e2 vs e1 auto delta ~0
- **negative_result**: Under frozen formal test, trained E1/E2 do not improve Q over E0 enough to release; B1 failed_policy dominates blind60 and large parts of main.
  - evidence: eval_main_s42_0001 summary, audit_blind_s46_0001 human review, S34/S40 acceptance

## 6. Negative result (honest)

- Training versions E1/E2 did not clear the frozen release gate against E0; formal auto Q deltas vs E0 are near zero.
- Preference/DPO scale remained below the original target; do not claim completed target-scale DPO.
- B1 policy failures are an experimental outcome to keep visible, not a silent drop from the denominator.

## 7. Limitations

- Single-author human blind review only.
- Pretraining contamination cannot be fully excluded.
- External DRBench/live are small custom subsets, not official full leaderboards.
- Live web pages can differ across adjacent AB/BA runs.
- Token proxy prices ≠ invoice; see billing index.
- Public hosting may be unavailable; personal SSH/tunnel access is a separate claim.

## 8. Provenance bindings

- `eval_main_s42`: `runs/evaluation/eval_main_s42_0001` sha256=`None`
- `eval_ablation_s43`: `runs/evaluation/eval_ablation_s43_0001` sha256=`None`
- `eval_budget_s44`: `runs/evaluation/eval_budget_s44_0001` sha256=`None`
- `eval_stability_s44`: `runs/evaluation/eval_stability_s44_0001` sha256=`None`
- `rpt_s44`: `artifacts/reports/rpt_s44_0001` sha256=`None`
- `eval_drbench_s45`: `runs/evaluation/eval_drbench_s45_0001` sha256=`None`
- `eval_live_s45`: `runs/evaluation/eval_live_s45_0001` sha256=`None`
- `s46_human_bootstrap`: `runs/evaluation/eval_blind_s46_0001/human_bootstrap_summary.json` sha256=`3afb62c9f011e3e4a203860c33ab3d15b93c14ee728a63e00008cceb1a813512`
- `s46_paired_bootstrap`: `runs/evaluation/eval_blind_s46_0001/paired_bootstrap.json` sha256=`654c433d3943e68d653f3467c15c6c48d51aa1876f785fa7156bad3338125788`
- `s46_attribution`: `runs/evaluation/eval_blind_s46_0001/error_attribution_summary.json` sha256=`322b1e181249028d8720bceb36dabe6db0b4c3e6ef5093bc6d265efc757eaa14`
- `acceptance_S42`: `runs/steps/S42/a001/acceptance.json` sha256=`c9deac881ab0842cfcd378b06bc0b480c81035495f8af268bcd30e9f62a8c3ae`
- `acceptance_S43`: `runs/steps/S43/a001/acceptance.json` sha256=`7cb3ae880e5ddcf13daeafdccf168dfbd99bc3d82c2531268c32e2b2ee468bd6`
- `acceptance_S44`: `runs/steps/S44/a001/acceptance.json` sha256=`e779e7cb0b64cf9a86659810e350ef3914274ea053aef9a3cb9e88444cc9db1f`
- `acceptance_S45`: `runs/steps/S45/a001/acceptance.json` sha256=`9adceb5d7accfed367d5e8345e0799f051751ad872f3ff73672878b59902f896`
- `acceptance_S46`: `runs/steps/S46/a001/acceptance.json` sha256=`aa27b8799a43d7e7b9f1a33be5bba5c73b281810bcbde7585d8e4836b8758df4`
- `mf_s41_freeze`: `data/manifests/mf_s41_freeze_0001.json` sha256=`43fb3f67ae978059dfcdf0de047b9607ab679187d5d990b1903163bc14cf291a`

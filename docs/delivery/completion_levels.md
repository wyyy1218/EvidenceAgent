# 完成等级判定（S50）

> release_id: `rel_s50_e0_0001`  
> 判定日：2026-10-28  
> 规则：附录 D.3 / `docs/plan/acceptance_registry.md` §8；**不把「应用可用」写成「全项目完成」**。  
> 发布标签：`v1.0.0-preview`（非完整 v1.0.0；原因见下表未完成项）。

## 1. 分项状态

| 完成等级 | 判定 | 依据（验收/产物） | 仍不能声称 |
| --- | --- | --- | --- |
| 产品可用 | **YES** | S23 U01–U10 PASS；S48 本人隧道可调用；导出 U10 | 不等于训练或完整评测完成 |
| SFT 实验完成 | **YES** | S30 数据目标达标；S32 正式训练；S33 导出；S34 四轴结算（效果门槛 FAIL） | 不等于发布版必须采用 SFT；E1=`research_only` |
| DPO 实验完成 | **YES** | S36 train≥300；S37 reference；S38 正式 DPO；S39 开发评测 | 不等于 DPO 提升或在线 RL；`meets_target_scale=false` |
| 目标数据规模完成 | **PARTIAL** | SFT 4917/930 达目标；中文任务 240/60/100；DPO **315/89 ≠ 600/100** | 不得宣称目标偏好规模完成 |
| 完整评测完成 | **YES** | S41 冻结；S42 1800/1800；S43–S45；S46 盲审+bootstrap；S47 报告 | B1 大量 failed_policy 已保留；单人盲审无复标 |
| 完整交付完成 | **YES（条件清楚）** | S48 复现；S49 清单+checksums；本步 release manifest | **公开托管 NOT_PROVIDED** → 不能写全天在线公共服务 |
| 降级交付（训练路径） | **适用** | 发布系统固定 **E0**；E1/E2 负结果保留 | 不能把未入选训练版包装成发布提高 |

## 2. 总判定

| 字段 | 值 |
| --- | --- |
| overall | **E0 产品 + 形式化评测 + 交付包 已完成**；训练提升路径为**有效负结果**；目标偏好规模**未达** |
| release_system | `e0` |
| git_tag | `v1.0.0-preview` |
| public_hosting | `NOT_PROVIDED` |
| remote_git_url | `NOT_REGISTERED`（本地 tag；未替用户开公开远程） |

## 3. 未完成 / 边界清单（写入发布说明）

1. DPO 目标偏好规模 600/100 未达成（实际 315/89）。  
2. E1/E2 未过发布门，不进入产品默认路由。  
3. 公开托管入口未提供；本人访问依赖 SSH 隧道。  
4. 盲审为单人真人；盲底与 `private.env` 不公开。  
5. 原始全量评测 jsonl 默认不入公开包（见 S49 PRIV）。  
6. 未声称工业级高并发、多卡、在线 Agent RL、原创全部框架。

## 4. 证据指针

| 主题 | 路径 |
| --- | --- |
| 产品 | `runs/steps/S23/a001/`、`runs/steps/S48/a001/` |
| SFT | `runs/steps/S30|S32|S33|S34/a001/`、`docs/models/sft_model_card.md` |
| DPO | `runs/steps/S36|S37|S38|S39/a001/`、`docs/models/dpo_model_card.md` |
| 发布选择 | `runs/steps/S40/a001/`、`docs/evaluation/release_selection.md` |
| 主实验/报告 | `runs/steps/S42/a001/`、`artifacts/reports/rpt_s47_0001/` |
| 交付 | `artifacts/releases/rel_s49_e0_0001/`、本 release |
| 面试绑定 | `docs/delivery/interview_notes.md` |

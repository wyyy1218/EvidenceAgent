# 面试 / 答辩笔记（S50）

> 规则：每条声明绑定真实文件或运行记录；**未测数字不填**；负结果不包装成提高。  
> 发布系统：**E0**｜标签：`v1.0.0-preview`｜完成等级见 `completion_levels.md`。

## A. 简历可写的三类事实（有证据）

### A1. 系统与证据能力

| 可写事实 | 绑定证据 |
| --- | --- |
| 文档问答：上传→混合检索→五动作受控循环→证据台账/冲突→可导出答案 | S10–S19；`docs/delivery/demo_script.md`；S23 U01–U10 |
| 硬预算、取消/恢复、SQLite 备份 | S20–S21；S48 `backup_restore_check` |
| 本人可调用 UI/API（隧道），非截图替代 | S48；`docs/operations/access.md` |
| Writer/Verifier 固定基座提示，不走决策 adapter | S17；T24；`docs/models/base_model_card.md` |

### A2. 状态—动作数据与 SFT/DPO

| 可写事实 | 绑定证据 |
| --- | --- |
| SFT：completion-only 掩码；train/dev 4917/930；正式 QLoRA 616 步 | S30–S32；`docs/models/sft_model_card.md` |
| 决策 LoRA 可调用；效果门槛相对 E0 的 G 降幅超限 → research_only | S33–S34；`runs/steps/S34/a001/acceptance.md` |
| 同状态双分支偏好；DPO reference=冻结 SFT；正式 DPO 315 对 | S35–S38；`docs/models/dpo_model_card.md` |
| **不可写**：目标偏好 600/100 已完成；训练版已入选发布 | S36 `meets_target=false`；S40 仅 e0 eligible |

### A3. 固定条件下的质量、支持与成本

| 可写事实 | 绑定证据 |
| --- | --- |
| 六系统主实验 6×300；正式数字由原始结果重算 | S42；`artifacts/reports/rpt_s47_0001/report.md` |
| 发布选择在看 test 前锁定 E0；E1/E2 门槛未过 | S40；报告 §2/§6 |
| 单人盲审 120；B1 盲审子集大量失败需保留 | S46；报告 §4 |
| 消融/预算/DRBench+live 分表，不混主聚合 | S43–S45 |
| Token 代理价 ≠ 发票；费用账本另见 | S20；报告 limitations |

## B. 预设问答（绑定文件）

### Q1. 为何做 Agent，而不是单次 RAG？

多跳检索、引用约束、冲突/证据不足、硬预算与可取消；单次检索不足以覆盖用户故事 U03–U07。  
**证据：** `docs/source/project_spec_v1.0.md` 场景；S19 五动作；`demo_script.md`。

### Q2. 相比 Deep Agents 上游改了什么？

固定提交 `e85c6b98…`（0.7.32）作 B2 起点；自建顺序控制器：证据台账、确定性打包、五动作、Writer/Verifier 节点、统一计账。不声称原创全部框架。  
**证据：** S03；`docs/architecture/baseline_matrix.md`；`third_party/` / THIRD_PARTY_NOTICES。

### Q3. 训练了谁？谁不训练？

只训决策 LoRA（E1→E2）；Writer/Verifier 始终 base 路由（T24）。  
**证据：** S17、S33、S39；模型卡。

### Q4. DPO 的 reference 为何是 SFT 而不是 base？

离线 DPO 在同一 SFT 策略上继续；reference 冻结为 `exp_sft_0001`，双 adapter `policy`+`reference`。  
**证据：** S37；`docs/models/dpo_model_card.md`。

### Q5. 为何不用在线 GRPO / PPO？

首版固定「QLoRA SFT → 一次离线 DPO」；单卡预算与可靠奖励取舍；不做在线 Agent RL。  
**证据：** `acceptance_registry.md` 训练行；S01 首版排除；执行方案附录 A.1。

### Q6. 如何防评测泄漏？

split 隔离、近重复、prompt 无 gold/test id；在线包无金标；盲底私有；S41 冻结后看 test。  
**证据：** S24–S30 审计；S41 `mf_s41_freeze_0001`；S46 `private/blinding_key.json`（PRIV）。

### Q7. 会不会只是「少回答」刷分？

假答率与 G 一并报告；发布门含 G 降幅与 answered_false；E1/E2 未过门是负结果。  
**证据：** S34/S40 gates；`rpt_s47_0001` 主表 false_ans 列。

### Q8. 主实验里 B1 为什么是 0？

本轮 B1 300/300 `failed_policy`（实现/策略失败），保留在分母与盲审，不静默剔除。  
**证据：** S42 acceptance；报告 §1/§6；S46。

### Q9. 能否说做成了工业级服务？

不能。Worker=1、队列≤10；公开托管未提供；本人隧道 ≠ 公网 SLA。  
**证据：** 附录 A.1 并发；S48 `public_hosting=NOT_PROVIDED`；`access.md`。

### Q10. 最终交付是什么版本？

产品默认 **E0**；Git 标签 **`v1.0.0-preview`**；完成等级见 `completion_levels.md`。  
**证据：** 本文件；`artifacts/releases/rel_s50_e0_0001/`。

## C. 禁止话术（对照）

| 禁止 | 原因 |
| --- | --- |
| 「DPO/SFT 显著提升已上线」 | E1/E2 未入选；主实验 ΔQ≈0 |
| 「完成 600/100 偏好」 | 实际 315/89 |
| 「在线 RL / GRPO」 | 未做 |
| 「公开 7×24 演示」 | 托管 NOT_PROVIDED |
| 「多标注者一致性」 | 单人盲审 |
| 「全部开源含盲底与全量 jsonl」 | PRIV/COND 见交付清单 |

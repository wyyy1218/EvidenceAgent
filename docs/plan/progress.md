# EvidenceAgent 步骤进度索引（S01—S50）

> 更新日期：2026-10-28（S01–S50 PASS；执行链结束）  


> 验收证据统一目录：`L/steps/<step_id>/<attempt_id>/`（acceptance.md、evidence_index.json、失败时 failure.md）  
> 只有必需检查通过且证据可打开后，才可将验收列标为 PASS。文件存在 ≠ PASS。

| 步骤 | 任务 | 执行状态 | 验收 | 尝试 | 证据路径 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| S01 | 需求基线和完成范围 | COMPLETED | PASS | a001 | L/steps/S01/a001/ | 本轮建立 |
| S02 | 目录、命名和产物登记 | COMPLETED | PASS | a001 | L/steps/S02/a001/ | 本轮建立 |
| S03 | 上游冻结与个人工作边界 | COMPLETED | PASS | a001 | L/steps/S03/a001/ | 本轮建立；B2 可运行实现仍待后续 |
| S04 | 费用、账号与访问条件 | COMPLETED | PASS | a001 | L/steps/S04/a001/ | 账本骨架；价 UNKNOWN；访问=隧道/映射方案 |
| S05 | 实例、数据盘与初始备份 | COMPLETED | PASS | a002 | L/steps/S05/a002/ | a002 扩容后重启：100.00GiB PASS；4080S 接受；a001 的 50GiB FAIL 已被 a002 取代 |
| S06 | 四环境与冻结模型 | COMPLETED | PASS | a001 | L/steps/S06/a001/ | 四环境+锁+四模型 manifest；盘余量≈56GiB |
| S07 | 环境、模型、训练探针 | COMPLETED | PASS | a001 | L/steps/S07/a001/ | 核心1–6+8 PASS；外部密钥回退登记 |
| S08 | 最小 UI→API→模型 | COMPLETED | PASS | a001 | L/steps/S08/a001/ | healthz/鉴权/短问 e2e；vLLM 仅本机；serve 统一启停 |
| S09 | API、任务和数据库事务 | COMPLETED | PASS | a001 | L/steps/S09/a001/ | 契约+SQLite+幂等/队列/事务；pytest 20 |
| S10 | 上传校验与解析 | COMPLETED | PASS | a001 | L/steps/S10/a001/ | pypdf/pdfplumber；T02/T03；UI 状态 |
| S11 | 原文位置、去重和版本 | COMPLETED | PASS | a001 | L/steps/S11/a001/ | T04–T06；version_set 锁定 |
| S12 | 分块和版本化索引 | COMPLETED | PASS | a001 | L/steps/S12/a001/ | chunker+BM25+FAISS；HashEmbedder 本地验收 |
| S13 | 混合检索 | COMPLETED | PASS | a001 | L/steps/S13/a001/ | RRF+rerank；夹具+T07；冷热缓存 |
| S14 | 网页、快照和三模式 | COMPLETED | PASS | a001 | L/steps/S14/a001/ | off/replay PASS；live 无密钥已登记 |
| S15 | 工具契约、权限和失败 | COMPLETED | PASS | a001 | L/steps/S15/a001/ | T10/T11；dispatch；schema |
| S16 | 证据台账与冲突 | COMPLETED | PASS | a001 | L/steps/S16/a001/ | 台账+校验+冲突；迁移0002 |
| S17 | 固定 Writer/Verifier 与 B0 | COMPLETED | PASS | a001 | L/steps/S17/a001/ | B0+mock；base 路由 |
| S18 | 可见状态与打包 | COMPLETED | PASS | a001 | L/steps/S18/a001/ | 确定性打包+gold隔离 |
| S19 | 五动作与受控循环 | COMPLETED | PASS | a001 | L/steps/S19/a001/ | LangGraph结构+执行器循环 |
| S20 | 硬预算与费用账本 | COMPLETED | PASS | a001 | L/steps/S20/a001/ | 预留1536+逻辑工具账本 |
| S21 | 取消、日志、恢复和备份 | COMPLETED | PASS | a001 | L/steps/S21/a001/ | VACUUM备份+SSE+取消恢复 |
| S22 | B1/B2/E0 与比较矩阵 | COMPLETED | PASS | a001 | L/steps/S22/a001/ | B1/B2/E0+矩阵；Mock 四系统探针 |
| S23 | 产品基础验收 | COMPLETED | PASS | a001 | L/steps/S23/a001/ | 五页UI+U10导出；可采集门槛 OPEN |
| S24 | 评测与标注协议 | COMPLETED | PASS | a001 | L/steps/S24/a001/ | 协议+指标+近重复阈值冻结 |
| S25 | HotpotQA 子集 | COMPLETED | PASS | a001 | L/steps/S25/a001/ | 600/100/200；隔离+data_card；CC BY-SA 4.0 |
| S26 | 中文来源与 replay 库 | COMPLETED | PASS | a001 | L/steps/S26/a001/ | 十项目隔离；三套 replay；authored excerpt |
| S27 | 中文题与人工金标准 | COMPLETED | PASS | a001 | L/steps/S27/a001/ | 240/60/100；replay 120/30/50；audit |
| S28 | 评分器与 20 题 pilot | COMPLETED | PASS | a001 | L/steps/S28/a001/ | 夹具 PASS；pilot20；forecast gpu_ok |
| S29 | 真实轨迹与过滤 | COMPLETED | PASS | a001 | L/steps/S29/a001/ | 启发式回退；80 traj；179 states |
| S30 | SFT 数据与掩码 | COMPLETED | PASS | a001 | L/steps/S30/a001/ | 4917/930 target_met；动作最大 47.53%；掩码 4/4 |
| S31 | 32 样本训练探针 | COMPLETED | PASS | a003 | L/steps/S31/a001/ | a001/a002 lm_head dtype 失败；a003 PASS，VRAM 6.28GiB，reload OK |
| S32 | 正式 SFT | COMPLETED | PASS | a001 | L/steps/S32/a001/ | 616 步、2 epoch、有效 batch16；adapter 4e8b60a0；VRAM 7.30GiB；checkpoint-600/616（400/500 被 save_total_limit 清理） |
| S33 | vLLM 导出与开发筛选 | COMPLETED | PASS | a001 | L/steps/S33/a001/ | 选中 e1_final；40 Q 0.3503 vs E0 0.317；160 Q 0.2512 vs 0.2479；E0 coerce 修复后重跑 |
| S34 | SFT 结算和 DPO 准入 | COMPLETED | PASS | a001 | L/steps/S34/a001/ | 四轴：数据/训练/可调用 PASS；效果门槛 FAIL（G↓0.125）；dpo_allowed=true；回退 E0；E1 research_only |
| S35 | 同状态双分支 | COMPLETED | PASS | a001 | L/steps/S35/a001/ | 2 对短探针 PASS；seed 不独立已声明；导出 prompt 为 chat template |
| S36 | 偏好规则与 seed 复核 | COMPLETED | PASS | a001 | L/steps/S36/a001/ | train315/dev89；dpo_s36_v1；目标600/100未达；review=not_independent |
| S37 | reference、缓存与探针 | COMPLETED | PASS | a001 | L/steps/S37/a001/ | validate-cache/T23/probe PASS；adapter=`policy`+`reference` |
| S38 | 正式 DPO | COMPLETED | PASS | a001 | L/steps/S38/a001/ | exp_dpo_0001；315 对、80 updates；meets_target_scale=false |
| S39 | E2 导出和开发评估 | COMPLETED | PASS | a001 | L/steps/S39/a001/ | T24 OK；dev40→e2_final；dev160 e0/e1/e2 完整；不要求优于 E1 |
| S40 | 开发集发布选择 | COMPLETED | PASS | a001 | L/steps/S40/a001/ | 发布 E0；E1 research_only；E2 G↓0.070 未过门槛；未看 test |
| S41 | 最终冻结 | COMPLETED | PASS | a001 | L/steps/S41/a001/ | 发布 E0；2544 清单；`mf_s41_freeze_0001`；DRBench/live 规则冻、ID/题干 pending |
| S42 | 六系统主实验 | COMPLETED | PASS | a001 | L/steps/S42/a001/ | 远端 PASS；1800/1800；eval_main_s42_0001；未看 test 选发布 |
| S43 | 锚点和预算消融 | COMPLETED | PASS | a001 | L/steps/S43/a001/ | 200/200；nsa+hvb 各100；control_e0=100；eval_ablation_s43_0001 |
| S44 | 预算曲线和稳定性 | COMPLETED | PASS | a001 | L/steps/S44/a001/ | budget 240+stab 240+b8 reuse 120；rpt_s44_0001；b1 紧预算多 failed_policy（记录） |
| S45 | DRBench 与 live 测试 | COMPLETED | PASS | a001 | L/steps/S45/a001/ | 24+40；eval_drbench/live_s45_0001；未混入主聚合 |
| S46 | 盲审、统计和归因 | COMPLETED | PASS | a001 | L/steps/S46/a001/ | 120 单人真人盲审；zip→human_review；bootstrap1e4；B1 blind60 全 failed |
| S47 | 原始结果生成报告 | COMPLETED | PASS | a001 | L/steps/S47/a001/ | rpt_s47_0001；数值可追溯；发布仍 E0 |
| S48 | 干净复现和服务验收 | COMPLETED | PASS | a001 | L/steps/S48/a001/ | 统一 CLI；cache_reused；公开托管未提供；备份本机哈希一致 | |
| S49 | 交付包、卡片和演示 | COMPLETED | PASS | a001 | L/steps/S49/a001/ | rel_s49_e0_0001；访客 README；base/SFT/DPO 卡；演示脚本；公开托管仍 NOT_PROVIDED |
| S50 | 完成等级、发布和面试 | COMPLETED | PASS | a001 | L/steps/S50/a001/ | rel_s50_e0_0001；v1.0.0-preview；完成等级分项；面试笔记绑定证据 |

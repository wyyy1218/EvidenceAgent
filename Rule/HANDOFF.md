# EvidenceAgent 当前交接状态

> 快照版本：1.9.16｜更新日期：2026-10-28 16:20 +08  
> 当前唯一活动快照：`S50_PASS`｜阶段：`执行链结束`  
> 关联变更：S50 完成等级 + `rel_s50_e0_0001` + 本地标签 `v1.0.0-preview`；公开托管仍未提供。

## 1. 接手后先看这里

**SSH OK（`:28394`）；S01—S50 PASS。发布：E0；标签：`v1.0.0-preview`。**

**S50：** 完成等级分项判定（产品/SFT/DPO/评测/交付）；面试笔记绑定真实路径；release `artifacts/releases/rel_s50_e0_0001/`；Git 本地 tag；远程 URL **NOT_REGISTERED**（未替用户开公开远程）。

**关键事实：** B1 主实验/盲审大量 `failed_policy`；E1/E2 未过发布门；不得宣称目标偏好规模 600/100 或训练版入选发布；公开托管 NOT_PROVIDED。

## 2. 当前状态总表

| 对象 | 状态 |
| --- | --- |
| S01—S50 | PASS（本机 acceptance 已同步） |
| 发布 | **E0** |
| Git 标签 | **`v1.0.0-preview`** |
| 交付包 | `rel_s49_e0_0001` → `rel_s50_e0_0001` |
| 盲审 | 单人真人；`audit_blind_s46_0001` |
| 报告 | `rpt_s47_0001` |
| 复现/服务 | `probe_s48_a001`；`bak_s48_a001` |
| 下一步 | 无强制步骤；新功能/重训练开新版本，不回写旧实验 |

## 3. 续跑要点（若再开工作）

1. 不删 `results_*.jsonl`；不改冻结子集 / E0 / 2544  
2. 盲底 `private/blinding_key.json` 保持私有  
3. 不把 AutoDL 个人入口写成公开托管  
4. 若公开远程：先登记 URL 到 decision_log U-12，再 push tag  

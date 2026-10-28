# EvidenceAgent 决策日志

> 建立步骤：S01｜更新日期：2026-10-25  
> 规则：已决策 / 待决策 / 变更影响分开记录；不能凭本文件推翻用户明确指令或原说明归档。  
> 关联权威：`docs/source/project_spec_v1.0.md`、`docs/plan/execution_plan.md`、`Rule/README.md`

---

## 1. 已决策（本轮导入与布局）

| ID | 决策 | 依据 | 影响 |
| --- | --- | --- | --- |
| D-20261025-01 | 本地文档准备区 `WORK_ROOT` = `d:\1-实习\项目\EvidenceAgent`；正式 AutoDL 根目录待 S05 确认 | 执行方案第 0 节：服务器未定可用同一相对结构 | S05 需整体迁移/同步到数据盘 |
| D-20261025-02 | Git 仓库仅 `WORK_ROOT/repo/` | 执行方案 / Rule README | 大文件与环境不在 Git 根外误提交 |
| D-20261025-03 | `Rule/` 四文件布局（README/HANDOFF/CHANGELOG/REMOTE）替代 `project_rules.md` | 用户授权 + CHANGELOG `change_20261025_rule_init_001` | 已修订 `execution_plan.md` Rule 子树 |
| D-20261025-04 | 原说明只读归档为 `docs/source/project_spec_v1.0.md`（字节哈希见 HANDOFF） | S01 要求 | 后续更正进本日志，不改写归档掩盖差异 |
| D-20261025-05 | 根级导入源副本保留在 `runs/work/import_sources_20261025/` | 避免与 `R/docs/` 双源混淆 | 权威路径以 `R/docs/` 为准 |
| D-20261026-4080 | 接受 GPU 偏离：RTX 4080 SUPER 32GB（目标为 RTX 4090 24GB） | 用户扩容后明确“继续”；计划「完成 S06-S08」已锁定“接受 4080 SUPER” | 训练/推理显存按 32GB 记账；型号与目标不同，正式报告不得写成 4090；公平性/成本口径仍按实测 |

---

## 2. 待决策 / 运行时未知（须在指定步骤解决）

| ID | 未知项 | 解决步骤 | 当前状态 | 备注 |
| --- | --- | --- | --- | --- |
| U-01 | AutoDL 实际实例型号、区域、小时价 | S04、S05 | PARTIAL｜**须对新实例重验** | 2026-10-28 SSH 换口至 `28394`/hostname `…r2xe8ht31g-00882b05`；旧 4080S/价结论不可直接继承；克隆结束后重探针 |
| U-02 | 账号是否具备 6006/6008 开放端口映射条件 | S04、S08 | DOC_VERIFIED_NEED_ACCOUNT | 官方要求企业认证；本账号是否已认证未点选确认 |
| U-03 | 本人访问方式（映射 vs SSH 隧道 vs 阻塞） | S04 | VERIFIED_PLAN | 文档方案：企业映射优先，否则 SSH 隧道；见 access.md |
| U-04 | 是否允许获准方式的公开托管 | S04、S48 | NOT_REGISTERED | 标“未提供公开托管” |
| U-05 | 百炼教师账号地域、权限、当日价格 | S04、S07 | NOT_PROBED | private.env 无密钥；回退本地 base |
| U-06 | Tavily 账号剩余额度 | S04 | NOT_PROBED | 密钥未配置 |
| U-07 | 数据盘实际挂载路径与可用容量 | S05 | **CLOSED_2026-10-26（旧实例）**｜**新实例 PENDING_REPROBE** | 旧 a002 100GiB；2026-10-28 再换机后未重测（克隆中） |
| U-08 | HotpotQA / 中文语料官方 revision 与文件哈希 | S25、S26 | NOT_REGISTERED | 构建时冻结 |
| U-09 | 模型完整 revision SHA（Qwen/bge/MiniCheck） | S06 | **CLOSED_2026-10-26** | base=`cdbee75f…`；emb=`5617a9f6…`；rer=`953dc6f6…`；judge=`96eafd01…`；见 `data/manifests/mf_model_*.json` |
| U-10 | 四环境锁文件解析结果 | S06 | **CLOSED_2026-10-26** | uv 0.13.5；`repo/locks/{app,infer,train,judge}.txt`；见 environment.md |
| U-11 | 存储实际占用相对 100GiB 控制值 | S05 起持续 | UNKNOWN | 超配额先核算再按预算规则 |
| U-12 | Git 远程仓库 URL（若公开） | S49—S50 | NOT_REGISTERED | 本地 init ≠ 已发布远程 |
| U-13 | Deep Agents 固定提交文件是否可从此机拉取 | S03 | VERIFIED（2026-10-25） | 已快照；B2 代码适配仍待 S22 |

未提供实时账号信息不阻断本轮规划文档（S01—S03），但必须保留上表核验步骤，不能删掉训练或恢复验收来缩小项目。

---

## 3. 变更与影响（追加）

| 日期 | 变更 | 原因 | 影响 |
| --- | --- | --- | --- |
| 2026-10-28 | SSH 重绑端口 `28394`；新容器 hostname 观测登记 | 用户提供新 SSH；远端克隆进行中，禁止深度核验 | 别名/`private.env`/`REMOTE`/`access`/`HANDOFF` 已更新；资源字段 PENDING_REPROBE；见 `change_20261028_ssh_rebind_001` |
| 2026-10-27 | SSH 重绑端口 `35832`；新容器 hostname 观测登记 | 用户提供新 SSH；远端克隆进行中，禁止深度核验 | 别名/`private.env`/`REMOTE`/`access`/`HANDOFF` 已更新；资源字段 PENDING_REPROBE；见 `change_20261027_ssh_rebind_001` |
| 2026-10-26 | S09—S11 a001 PASS：API/DB/解析/版本 | 契约+pytest 20；pypdf/pdfplumber 入 app lock | 可进 S12；索引仍未建；Agent 仍 stub |
| 2026-10-26 | S07/S08 a001 PASS：探针与最小联通 | doctor+vLLM路由+LoRA+分时；API/UI/鉴权 e2e | 可进 S09；教师/Tavily 仍无密钥回退 |
| 2026-10-26 | S06 a001 PASS：四环境+锁+四模型冻结 | AutoDL 安装完成；HF 镜像+禁 Xet；MiniCheck 用 tarball | U-09/U-10 关闭；开 S07 探针 |
| 2026-10-26 | 数据盘扩容至100GiB并重启；S05 a002 PASS；接受4080S | 用户控制台扩容并重启实例，要求继续 S06-S08 | 容量门禁解除；S06 解锁；GPU 记 DEVIATION_ACCEPTED；实例价按 ¥1.66/时登记（待账单核销） |
| 2026-10-26 | 登记 AutoDL 实例 SSH；GPU=4080S；盘=50GiB | 用户提供 SSH 并批准 S04/S05 | S05 容量门禁 FAIL，阻断 S06 大下载；需扩容或换机。GPU 偏离记 DEVIATION，不静默改目标规格 |
| 2026-10-25 | `execution_plan.md` Rule 子树改为四文件 | 已授权布局修订 | 输入哈希 `0acf70f5…` → 修订后哈希见 IMPORT_MANIFEST；技术/预算/验收门槛不变 |

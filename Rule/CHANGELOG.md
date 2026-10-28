# EvidenceAgent 变更控制、Provenance 与变更记录

> 初始化日期：2026-10-25｜记录规则：只追加，不改写历史事实。  
> 当前状态和下一步见 [HANDOFF.md](HANDOFF.md)；总规则见 [README.md](README.md)；远程事实见 [REMOTE.md](REMOTE.md)。

## 1. 本文件的作用

记录“什么发生了变化、为何允许、依据是什么、影响哪些产物、如何验证、接下来如何执行”。不保存全部stdout，不替代原始运行日志，也不把缺失证据补写成当时已完成。

最新实际状态维护在HANDOFF；本文件保留按change_id追溯的历史。新增记录放在第5节现有记录上方，保留原记录相对次序；“追加式”指不覆盖、删除旧记录，允许按最新在前展示。

## 2. 变更分类与处理

### A. DESIGN_CHANGE：设计、评测或资源边界变化

包括模型/训练方法替换、五动作或状态语义改变、数据划分、gold与标注口径、偏好判定、reference定义、指标分母、统计方法、发布门槛、核心预算、首版功能范围和测试后的定向调参。

处理要求：

1. 先写具体修订、旧新差异、原因、影响和可验证方案。
2. 检查用户是否已明确授权该范围。已经授权的变更按授权执行并引用，不重复索要同一确认；未授权的实质变更在执行相关动作前请求确认。
3. 仅有Agent在decision_log中的自述不构成用户授权；记录要指出具体指令、已批准方案或授权change_id。
4. 指明哪些数据、轨迹、缓存、模型、结果失效，哪些保留为历史；必要时整体重建受影响集合，不能只修答错样本。
5. 原说明归档保留原字节；执行配置和文档以有记录的修订对齐，正式实验使用新的manifest。

### B. REPRO_IMPLEMENTATION_CHANGE：影响复现的实现变化

包括依赖补丁、接口适配、序列化、数据库迁移、路径映射、兼容性、部署引擎以及不改语义的性能修复。

处理要求：保存差异、版本、影响范围、最小探针和前后对照。在现有授权内的常规可逆修复可以直接做；若实测改变输出、截短、可见信息或评分含义，升级为A类处理。

### C. STATE_UPDATE：事实和运行状态变化

包括已核实路径、Git提交、实例切换、缓存清单、任务启动/完成、费用、备份、验收与交接更新。可以按真实观察直接更新，不能借状态更新修改技术设计。

### D. CORRECTION：勘误与证据补充

旧记录不删改，新增更正条目，引用被更正change_id，说明旧结论错在哪里、依据和影响。后来查到的锁文件或版本只能标为后来观察，不能回填成生成/训练当时已验证的环境。

### 原定回退与停止

教师不可用改本地base、SFT规定的OOM长度降级、既定学习率重试、DPO数据不足停止、开发选择回退E0等，均是原方案已允许的条件分支；满足条件即可执行，记录触发证据和影响，不因分类为设计影响就额外发明审批环节。

## 3. Provenance最低记录

| 对象 | 最低要素 |
| --- | --- |
| 代码/配置 | branch、commit、工作区差异、配置/提示/Schema哈希 |
| 原文与网页 | 来源、许可、revision/版本、抓取时间、原文SHA-256、位置映射 |
| 数据 | dataset_id、任务ID、split、来源manifest、生成/审核角色、过滤与去泄漏结果 |
| 轨迹 | task/state/run ID、可见状态、真实动作/观察、模型、工具、预算与失败 |
| SFT | 基座/数据/tokenizer/模板、掩码检查、参数、更新步、日志、adapter哈希 |
| DPO | 同状态双分支、Q/G/C与规则、seed复核、SFT reference哈希和缓存键 |
| 评测 | 系统、冻结manifest、任务子集、原输出、失败分母、成本与统计口径 |
| 人工审核 | 审核协议、真实审核者数量、盲化、原始标签、争议与更正 |
| 费用/运行 | 实例与环境、run、起止、Token/调用、已知/未知费用与账单核销 |
| 交付 | release_id、代码/模型/数据/报告版本、哈希、许可、公开范围与未完成项 |

不能凭空填commit、模型SHA、实验数量、PASS数量或性能。哈希必须来自对应文件字节，目录或记录不存在时写UNKNOWN/NOT_REGISTERED，不能写一个看似完整的值。

## 4. 记录格式与更新联动

每条记录至少包含下表字段。没有发生的动作明确写“未执行”，不使用模板暗示已发生。

| 字段 | 记录内容 |
| --- | --- |
| change_id / date / type | 唯一编号、日期、A/B/C/D类；时间戳注明时区 |
| authority | 用户已给的授权或原执行方案固定分支；无授权则写待确认 |
| scope | 所涉S步骤、模块、数据/模型/评测ID |
| before → after | 原来状态、实际变化、保持不变的设计边界 |
| reason | 问题与证据，不把“结果更好看”作为依据 |
| artifacts / provenance | 规范路径、输入输出版本、哈希或manifest |
| validation | 检查方法、真实结论、缺失或失败项 |
| invalidation / recovery | 影响哪些下游，是否重跑，如何恢复 |
| cost / remote | 实际新增用量、未知计费、实例/进程是否需要继续 |
| next / related | 下一步、关联旧记录、更正对象及HANDOFF/REMOTE更新 |

每次实质进展后更新HANDOFF；实例、环境、模型或运行事实变化同步REMOTE；设计/目录变化同步decision_log、directory_registry和受影响配置。只有已验收步骤才能在progress标PASS。

不要为每次小标点编辑制造冗长历史；可以在同一明确范围的记录中归并。正式运行、设计变化、冻结、恢复、更正和发布必须能单独追溯。

## 5. 变更记录（最新在前）

### change_20261028_s50_completion_001｜S50 完成等级、preview 标签与面试材料 PASS
- **Type：** C. STATE_UPDATE
- **Authority：** 用户「继续」；执行方案 S50 / 附录 D.3。
- **Scope：** `docs/delivery/{completion_levels,interview_notes,delivery_checklist}.md`；`scripts/run_s50.py`；`artifacts/releases/rel_s50_e0_0001/`；`runs/steps/S50/a001`；Git `v1.0.0-preview`；progress/HANDOFF/README。
- **Before：** S49 PASS；无完成等级分项、无面试绑定笔记、无最终 preview 标签。
- **After：** S50 PASS；分项判定写入 completion_levels；面试笔记绑定真实路径；release manifest 含已知问题与访问条件；本地 tag `v1.0.0-preview`（远程 NOT_REGISTERED）。
- **Validation：** `run_s50.py` 必需检查 PASS；完成等级含 DPO PARTIAL / 托管 NOT_PROVIDED。
- **Next：** 执行链结束；后续按新版本推进，不回写旧实验。

### change_20261028_s49_delivery_001｜S49 交付包、卡片与演示 PASS
- **Type：** C. STATE_UPDATE
- **Authority：** 用户「继续」；执行方案 S49。
- **Scope：** `README.md`；`docs/models/base_model_card.md`；`docs/data/README.md`；`docs/delivery/*`；`examples/requests|outputs`；`scripts/run_s49.py`；`artifacts/releases/rel_s49_e0_0001/`；`runs/steps/S49/a001`。
- **Before：** S48 PASS；交付清单/演示脚本/基座模型卡未齐。
- **After：** S49 PASS；`rel_s49_e0_0001` manifest+checksums；公开边界标明 NOT_PROVIDED / PRIV 盲底；E1/E2 卡保留负结果。
- **Validation：** 本机与远端 `run_s49.py` 必需检查 PASS；远端 adapter_config 在场。
- **Next：** S50 完成等级、发布标签与面试材料。

### change_20261028_s48_repro_001｜S48 干净复现与服务验收 PASS
- **Type：** B/C. REPRO_IMPLEMENTATION_CHANGE + STATE_UPDATE
- **Authority：** 用户「继续」；执行方案 S48。
- **Scope：** `evidence_agent.cli`；`scripts/ea.py`/`run_s48.py`；`Dockerfile`；`README.md`；`docs/operations/reproduce.md`；`backup.py` 同标签重备；`runs/steps/S48/a001`；`bak_s48_a001` 拉本机。
- **Before：** S47 PASS；无统一 CLI / Dockerfile；公开托管未验收。
- **After：** S48 PASS；CLI 契约+ingest/serve/鉴权/base/取消/T24/备份恢复；公开托管如实 NOT_PROVIDED；`cache_reused=true`。
- **Validation：** 远端 acceptance 全 PASS；本机备份 SHA256=`424b0721…` 与远端一致。
- **Next：** S49 交付包、卡片与演示。

### change_20261028_s46_human_s47_001｜S46 真人盲审定稿；S47 报告 PASS
- **Type：** C. STATE_UPDATE
- **Authority：** 用户确认盲审为真人并要求去除 AI 辅助口径后继续。
- **Scope：** `S46_blind60_review_results.zip` → `audit_blind_s46_0001/human_review/`；labels/disputes/protocol；`run_s47.py`；`rpt_s47_0001`。
- **Before：** S46 曾标 assisted；S47 未开始。
- **After：** S46 单人真人盲审 120/120；S47 PASS（原始结果重算，不手填）。
- **Validation：** AI 口径关键字抽检 clean；S47 acceptance required_checks 全 true。
- **Next：** S48 干净复现与服务验收。

### change_20261028_s45_s46_pass_001｜formal_chain 收尾；S45/S46 PASS
- **Type：** C. STATE_UPDATE
- **Authority：** 用户「继续」；执行方案 S45→S46 固定分支。
- **Scope：** S45 DRBench/live；S46 盲审/bootstrap/归因；`repo/scripts/run_s46.py`；`evaluation/stats|review`；progress/HANDOFF。
- **Before：** S45 RUNNING；S46 未开始。
- **After：** S45 PASS（24+40）；S46 PASS（120 单人辅助盲审 + bootstrap1e4）；formal_chain ALL DONE。
- **Validation：** 远端 `acceptance.json` result=PASS；本机 `runs/steps/S45|S46/a001/` 已同步；pytest `test_s46_bootstrap` 3 passed。
- **Notes：** B1 blind60 全 failed；发布仍为 E0；盲审为 assisted first pass，已写 limitations。
- **Next：** S47 从原始结果生成报告。

### change_20261027_s42_pause_001｜S42 过夜暂停；55/1800 已备份可 resume
- **Type：** C. STATE_UPDATE
- **Authority：** 用户要求保存 S42 进度并关闭远程、明日继续。
- **Scope：** 远端优雅停止 `tmux s42` / `dev_eval` / vLLM；`runs/evaluation/eval_main_s42_0001/`；`runs/steps/S42/a001/{acceptance,pause_snapshot}.*`；本机同步同路径；HANDOFF/REMOTE/progress。
- **Before：** S42 RUNNING（刚启动主实验）。
- **After：**
  - `result=PAUSED`；`n_runs_observed=55`（`b0`=55，其余 0）；`resume_safe=true`。
  - GPU 空闲；可控制台关机；数据盘与本机双端保留 jsonl。
  - 续跑：`tmux new-session -d -s s42 bash repo/scripts/run_s42.sh`（内含 `--resume`）。
- **Next：** 明日开机续跑 S42 至 1800；不删 results、不改冻结协议。

### change_20261027_s41_freeze_001｜S41 PASS；最终冻结 E0 + 2544 清单

- **Type：** B类步骤验收；B类实现（`run_s41_freeze.py`、子集哈希、run plan）；C类交接状态。
- **Authority：** HANDOFF/进度指向 S41；用户要求继续。
- **Scope：** `repo/scripts/run_s41_freeze.py`；`data/splits/s41_test_subsets.json`；`data/manifests/mf_s41_freeze_0001.json`；`repo/evaluation/protocols/s41_run_plan.*`；`runs/billing/forecast_s41.json`；`runs/steps/S41/a001/`；`preregistered_protocol.md`；artifact_index；HANDOFF/progress/REMOTE。
- **Before → After：**
  - 冻结发布策略 E0、六系统矩阵、配置包哈希、test 子集（ablation100 / budget_stability60 / blind60）。
  - 正式运行计划核对 **2544**；故障补跑与「不含项」成文。
  - DRBench=`IDS_PENDING_CATALOG`；live20=`PROTOCOL_FROZEN_TASKS_PENDING`（不阻断 S42）。
- **Validation：** unit `test_s41_freeze.py` 4 passed；`acceptance.json` PASS；`looked_at_test_scores=false`。
- **Next：** S42 六系统主实验。不得宣称 600/100 目标规模完成；不得宣称 DPO/SFT 入选发布。

### change_20261027_s37_s40_pass_001｜S37–S40 PASS；发布选择 E0

- **Type：** B类步骤验收；B类实现（DPO trainer / 评估编排 / 发布选择）；C类交接状态。
- **Authority：** 用户批准并要求执行 S37–S40 计划；并要求盯 S39 至完成。
- **Scope：** `training/dpo/`；`run_s37–39*.sh`；`run_s40_select.py`；`runs/steps/S37|S38|S39|S40/a001/`；`eval_dev*_s39_0001/`；`artifacts/adapters/dpo/exp_dpo_0001/`；HANDOFF/progress/REMOTE/release_selection/dpo_model_card。
- **Before → After：**
  - S37：缓存一致、T23 阻断、探针 PASS；PEFT 禁止 adapter 名 `train` → 改为 `policy`。
  - S38：`exp_dpo_0001` PASS；train=315；`meets_target_scale=false`。
  - S39：T24 PASS；dev40 选 `e2_final`；dev160 同条件完整（`--subset all` 修正后 resume）。
  - S40：相对 E0 门槛后仅 E0 合格；E1 research_only；E2 G↓≈0.070 淘汰 → **发布 E0**；未看 test。
- **Validation：** S37–S40 acceptance PASS；远端 `eval_dev160_s39_0001/summary.json`。
- **Next：** S41 最终冻结。不得宣称 600/100 目标规模完成。

### change_20261027_s36_pass_001｜S36 验收 PASS；导出 dpo_s36_v1（train315/dev89）

- **Type：** B类步骤验收；B类调度修补（dev 填配额也推迟低产类目；opening 回填）。
- **Authority：** 用户要求继续 S34–S36；train≥300 后采 dev、导出、写验收。
- **Scope：** `collect_branches.py`；`test_preference_sampling.py`；`br_s36_dev_0001`；`data/dpo/dpo_s36_v1/`；`runs/steps/S36/a001/`；HANDOFF/progress。
- **Before → After：**
  - train kept=315（≥300）；dev kept=89（目标 100 未达，规模透明）。
  - `_SKIP_WHILE_FILLING` 对 train/dev 当前 split 均生效；dev mid 耗尽后 opening 回填几乎无增量。
  - 合并导出 `dpo_s36_v1`：`meets_min_train=true`，`meets_target=false`；review=`not_independent`。
- **Validation：** unit `test_preference_sampling.py` 6 passed；`quality_report.json`；S36 acceptance PASS。
- **Next：** S37（停推理 → reference/缓存/T23 → DPO 短探针）。不得宣称 600/100 目标规模完成。

### change_20261027_s36_cat_priority_001｜优先 mul/dir，推迟 ver/ins/hpqa；无证据不配 stop

- **Type：** B类调度/采样修补（不改标签规则）。
- **Authority：** 监控发现 kept 卡在 154，`zh_train_ver_*`/`ins_*` 连续 discard；用户要求继续。
- **Scope：** `collect_branches.py`；`test_preference_sampling.py`；`br_s36_train_0001` resume。
- **Before → After：**
  - 排序：mul→dir→其他→ver→ins→hpqa。
  - 无 `evidence_cards` 时不配 finish/abstain（stop 侧常 `G=None` → `g_incomparable`）；改配 search/read 跨类型。
- **Validation：** unit 含类目优先级与 `allow_stop_contrast=False`；远端 resume。
- **Next：** kept≥300。

### change_20261027_s36_resume_hash_001｜修复 wall 污染 state_hash 与 HPQA 空转

- **Type：** B类实现修补（resume/去重/调度；不改 Q/G/C 阈值）。
- **Authority：** 用户要求排查 kept 卡住并解决。
- **Scope：** `collect_branches.py`；`test_preference_sampling.py`；`br_s36_train_0001`。
- **Before → After：**
  - 根因：`visible.budget = visible_budget()` 刷新 `remaining_wall_seconds` → `state_hash` 每次不同 → resume 无法跳过；重启后重采并产生重复 keep；短预算排序把大量 HPQA 插在中文前，HPQA 几乎全 `both_wrong`/`g_incomparable`，kept 卡在 ~228。
  - `_preference_state_hash` 忽略 wall；resume 增加 `(task_id, step)` 与 action-pair 去重；启动时压缩 pairs 逻辑重复；工作序改为 **chinese 优先** 再短预算。
- **Validation：** unit 4 passed；远端 deduped `230→128`；PID 16715 resume 后约 1 分钟 kept 128→136（`zh_train_mul_*` quality/cost）。
- **Next：** kept_train≥300 → 采 dev → 导出 `dpo_s36_v1`。

### change_20261027_s36_score_scope_001｜修复 claim.scope 为 dict 时评分崩溃

- **Type：** B类实现修补（评分健壮性；不改标签阈值本身）。
- **Authority：** 扩采崩溃后恢复；用户通知跟进。
- **Scope：** `evaluation/metrics/chinese_q.py`；`collect_branches.py` `_side_metrics`；`br_s36_train_0001` resume。
- **Before → After：** pred claim `scope` 偶发为 dict → `str+dict` TypeError 中断整批；现 `_as_text` 规范化，且单条评分异常记为 `score_error` 不杀进程。
- **Validation：** 崩溃停在 kept=145；修复后重新 `--resume`。
- **Next：** 继续至 kept_train≥300。

### change_20261027_s36_speed_002｜偏好扩采再提速：同对双分支并行 + 短预算优先

- **Type：** B类实现修补（不改 Q/G/C 标签规则与合法动作集合）。
- **Authority：** 用户要求「再加速」并确认继续执行。
- **Scope：** `collect_branches.py`；`tests/unit/test_preference_sampling.py`；`br_s36_train_0001` resume。
- **Before → After：**
  - 同偏好对的 `branch_a`/`branch_b`（及 seed43 复核）用 `ThreadPoolExecutor(max_workers=2)` 并行；仍是一对内双分支，不是两条独立研究任务。
  - stop 首动作（finish/abstain）`max_steps=1`；continue 侧仍为 `remaining_tools+2`。
  - 采样：iid 最多 1 次 → 立刻确定性跨类型；nudge 最多 1 次。
  - `work_items` 按剩余工具预算升序，短分支优先。
- **Validation：** 远端 unit `test_preference_sampling.py` 3 passed；旧 PID 12282 已停；新 PID 13255 `--resume`；约 2 分钟内 kept 66→81（~7–8 keep/min，高于 speed_001 的 ~1.9）。
- **Next：** 继续至 kept_train≥300。

### change_20261027_s36_speed_001｜偏好扩采提速：剩余工具预算 max_steps + 跨类型采样

- **Type：** B类实现修补（不改标签语义；缩短分支步数并优先协议内跨动作类型）。
- **Authority：** 用户要求继续扩量并「将 max_steps 改为剩余工具预算，并优先跨动作类型采样以提速」。
- **Scope：** `collect_branches.py`；`dev_harness.py`；`tests/unit/test_preference_sampling.py`；`br_s36_train_0001` resume。
- **Before → After：**
  - `max_steps`：`cfg.tool_calls+2` → `remaining_tools+2`；每分支 `_fresh_budget` 重置墙钟（修复后跑分支继承前支耗时导致 timeout）。
  - 采样：少次 iid 后立刻确定性跨类型配对（继续搜索 vs stop 优先）；timeout 类 discarded 允许 resume 重试。
  - 实测约 3 分钟内 kept 5→9，新 keep 多为 `read_evidence|local_search` vs `finish`；旧批次 55 条 timeout 不再主导新日志。
- **Validation：** 远端 unit `test_preference_sampling.py` 2 passed；PID 12282 `--resume` 运行中。
- **Next：** 继续至 kept_train≥300。

### change_20261027_s34_s35_pass_001｜S34 结算与 S35 短探针 PASS；S36 扩采启动

- **Type：** B类步骤验收；C类运行状态。
- **Authority：** 执行已批准的 S34–S36 计划。
- **Scope：** `runs/steps/S34|S35/a001/`；`runs/branches/br_probe_s35_0001`；`br_s36_train_0001`（进行中）；`sft_model_card.md`；`progress.md`。
- **Before → After：**
  - S34：四轴结算 PASS；effect_gate FAIL（G↓0.125）；`dpo_allowed=true`；产品回退 E0；E1 `research_only`。
  - S35：2 对短探针链路 PASS；vLLM seed 不独立 → `review=not_independent`；DPO 导出 prompt 为 chat template。
  - S36：`br_s36_train_0001` 后台扩采（目标 kept≥300，配额 400）。
- **Validation：** `probe_s35_preflight_a001`；`runs/steps/S35/a001/probe_checks.json` 26/26 PASS。
- **Next：** train≥300 后采 dev、合并 `data/dpo/dpo_s36_v1/`、写 S36 验收。

### change_20261028_ssh_rebind_001｜SSH 重绑新实例端口 28394（克隆进行中，未资源核验）

- **Type：** C类远程与交接状态更新；无安装、无模型下载、无 UI/API 部署、无深度探针。
- **Authority：** 用户提供 `ssh -p 28394 root@connect.westc.seetacloud.com`，要求建立稳定连接并更新远程记录；明确「还在克隆不用核验里面的文件」。
- **Scope：** 本机 `~/.ssh/config` 别名 `evidence-agent-autodl`；`runs/system/private.env` 的 `SSH_PORT`；`REMOTE.md` / `access.md` / `HANDOFF.md` / `decision_log.md`。
- **Before → After：**
  - SSH 端口 `35832` → `28394`；旧口作废。
  - 密钥 `BatchMode` 登录 OK；Keepalive：`ServerAliveInterval 30` + `TCPKeepAlive yes`。
  - 连接时 hostname 观测 `autodl-container-r2xe8ht31g-00882b05`（上一实例 `…8f1147b36e-e494c777` 记为历史）。
  - Host key ED25519 指纹与此前登记相同：`SHA256:EPstg8jNN+u3Bs1JyQOqlBeq3w+a4VynoJAe48YnIV0`；资源/环境字段标 `PENDING_REPROBE`。
  - 本机 S42 暂停备份（55/1800）仍保留；远端对齐待克隆结束。
- **Validation：** `ssh -o BatchMode=yes evidence-agent-autodl "echo OK"` 成功；未跑磁盘/GPU/服务/文件探针（按用户要求）。
- **Cost / remote：** 实例开机可达即计费；本变更未启停服务。克隆结束后需重验再决定 serve/续跑 S42/关机。
- **Next：** 克隆完成后更新 REMOTE 资源表并视需要同步/探针；相关见 HANDOFF 快照 `SSH_REBIND_CLONE_PENDING`。

### change_20261027_clone_reprobe_001｜克隆完成重验并启动 sft_e1 推理（S34–S36）

- **Type：** C类远程与运行状态；B类实现修补（S34 结算、偏好采集链路，为短探针与 ≥300 扩量）。
- **Authority：** 用户确认「克隆已完成，可立刻重验并开推理」，并批准执行 S34–S36 计划（短探针后扩到 train≥300）。
- **Scope：** `REMOTE.md` / `HANDOFF.md`；`serve.py` vLLM+`sft_e1`；`run_s34_settle.py`；`collect_branches.py` / `label_rules.py` / `policy.py` / `dev_harness.py`。
- **Before → After：**
  - 资源字段 `PENDING_REPROBE` → VERIFIED（WORK_ROOT 46G；盘 100G/55G avail；4080S 32GB；adapter+S33 证据齐）。
  - vLLM 仅推理模式加载 `sft_e1`；`/v1/models` 200。
  - S34 结算改为四轴分写、效果门槛读 `project.yaml` release、forecast 合并而非覆盖。
  - 偏好采集：SFT 中间态、cand_store、温度/seed 透传、真实 prompt 导出、both_wrong、resume/配额。
- **Validation：** SSH 只读 `df`/`nvidia-smi`/`ls`；serve status + HTTP 200。
- **Next：** 跑 S34 → 2 对短探针 → 扩到 ≥300；相关 HANDOFF 快照 `CLONE_REPROBED_S34_READY`。

### change_20261027_ssh_rebind_001｜SSH 重绑新实例端口 35832（克隆进行中，未资源核验）

- **Type：** C类远程与交接状态更新；无安装、无模型下载、无 UI/API 部署、无深度探针。
- **Authority：** 用户提供 `ssh -p 35832 root@connect.westc.seetacloud.com`，要求建立稳定连接并更新远程记录；明确「不用核验信息因为还在克隆」。
- **Scope：** 本机 `~/.ssh/config` 别名 `evidence-agent-autodl`；`runs/system/private.env` 的 `SSH_PORT`；`REMOTE.md` / `access.md` / `HANDOFF.md`。
- **Before → After：**
  - SSH 端口 `36512` → `35832`；旧口作废。
  - 密钥 `BatchMode` 登录 OK；Keepalive：`ServerAliveInterval 30` + `TCPKeepAlive yes`。
  - 连接时 hostname 观测 `autodl-container-8f1147b36e-e494c777`（上一实例 `…12ce4dade8-72ec6d56` 记为历史）。
  - Host key ED25519 指纹与 2026-10-26 登记相同；资源/环境字段标 `PENDING_REPROBE`。
- **Validation：** `ssh -o BatchMode=yes evidence-agent-autodl "echo OK"` 成功；未跑磁盘/GPU/服务探针（按用户要求）。
- **Cost / remote：** 实例开机可达即计费；本变更未启停服务。克隆结束后需重验再决定 serve/关机。
- **Next：** 克隆完成后更新 REMOTE 资源表并视需要同步/探针；相关见 HANDOFF 快照 `SSH_REBIND_CLONE_PENDING`。

### change_20261026_s26_s29_001｜S26—S29 PASS（中文来源/任务/评分器/轨迹）

- **Type：** B类实现（chinese_catalog/corpus、freeze/build/score/pilot/collect 脚本、metrics）；C类步骤状态。
- **Authority：** 用户指令「继续完成 S26–S29」。
- **Scope：** 中文资料冻结与 replay；400 题金标准；离线 Q 评分与 20 题 pilot；train/dev 轨迹过滤。
- **Before：** S25 PASS；无中文任务集与轨迹。
- **After：**
  - S26 a001 **PASS**：十项目 split 隔离；30 文档；三套 replay；authored_local_use_excerpt。
  - S27 a001 **PASS**：`zh_tech_s27_v1` 240/60/100；replay 120/30/50；audit span 核验。
  - S28 a001 **PASS**：中文 Q 夹具 8/8；pilot 20；`forecast.json` gpu_ok。
  - S29 a001 **PASS**：Bailian 空→启发式回退；80 accepted / 179 state-actions；测试排除。
- **未声称：** 完整上游文档镜像；真人多人标注 IAA；教师 API 实采全量；SFT 就绪规模（≥2000）。
- **下一步：** S30 SFT 数据与掩码。

### change_20261026_s22_s25_001｜S22—S25 PASS（基线矩阵/产品验收/评测协议/HotpotQA 子集）

- **Type：** B类实现（baselines、UI 五页、export、data/near_dup、HotpotQA 构建脚本）；C类步骤状态；文档协议冻结。
- **Authority：** 用户批准并执行计划「完成 S22–S25」。
- **Scope：** B1/B2/E0 公平比较；产品 U01–U10 与导出；标注/评测预登记；HotpotQA distractor 派生子集隔离。
- **Before：** S21 PASS；仅 B0；四页残缺 UI；无评测协议文档；无 HotpotQA 子集。
- **After：**
  - S22 a001 **PASS**：`react.py` / `e0_runner.py` / `deepagents_research.py`；`baseline_matrix.md`；`test_s22_baselines` 6 passed。
  - S23 a001 **PASS**：五页面 UI；`export/package.py`（answer.json/引用/MD/zip）；可采集门槛 OPEN。
  - S24 a001 **PASS**：annotation/metric/preregistered 协议；近重复 Jaccard 0.85/0.75 冻结。
  - S25 a001 **PASS**：`hotpotqa_distractor_s25_v1` 600/100/200；CC BY-SA 4.0；隔离无违规。
- **未声称：** 六系统主实验（S42）；正式轨迹采集（S29）；官方 fullwiki 成绩；deepagents 包已安装（B2 为适配循环）。
- **下一步：** S26 中文来源与 replay 库。

### change_20261026_s12_s15_001｜S12—S15 PASS（分块索引/混合检索/网页三模式/工具契约）

- **Type：** B类实现（ingestion/chunker、retrieval/*、tools/*、api/indexes、schemas）；C类步骤状态。
- **Authority：** 用户指令「完成S12-S15」（依据执行方案与项目说明）。
- **Scope：** 分块双限制、BM25+FAISS 版本化索引、RRF+rerank 流水线、web off/replay/live、SSRF/candidate 权限、契约与边界测试。
- **Before：** S11 PASS；无索引、无混合检索、无网页工具契约。
- **After：**
  - S12 a001 **PASS**：chunker + 版本化索引 + 原子指针；`POST /v1/projects/{id}/indexes`。
  - S13 a001 **PASS**：固定混合检索；夹具期望位置；T07 零结果；冷/热缓存。
  - S14 a001 **PASS**：off 无外呼、replay 可重复；live 无密钥明确失败；T09 摘要不升证据。
  - S15 a001 **PASS**：统一 ToolResult；T10/T11；dispatch 仅三工具；schema 落盘。
  - 本地 pytest：**36 passed**（`runs/probes/pytest_s12_s15_a001.txt`）。
- **未声称：** 真 bge-m3 线上索引已在 AutoDL 重建；Tavily live 已联通；证据台账（S16）与 Agent 循环。
- **下一步：** S16 证据台账与冲突表达；AutoDL 安装 jieba 并用真实 embedding 建索引探针。

### change_20261026_s09_s11_001｜S09—S11 PASS（API/SQLite/解析/位置与版本）

- **Type：** B类实现（storage/api/ingestion/worker/UI）；C类步骤状态。
- **Authority：** 用户批准计划「S09—S11：API、解析与原文版本」并要求执行到底。
- **Scope：** 契约文档、SQLite 迁移与仓储、FastAPI 项目/文档/run、上传校验解析、locators/去重/版本、契约与边界测试、locks/app 增 pypdf/pdfplumber、HANDOFF/progress。
- **Before：** S08 最小联通；无持久任务表、无解析流水线。
- **After：**
  - S09 a001 **PASS**：api_contract/storage_design；12 表+WAL；T01/T17/队列/事务/T20；worker stub。
  - S10 a001 **PASS**：MIME/签名/大小/页数；needs_ocr；SHA-256；UI 状态页。
  - S11 a001 **PASS**：Unicode/页偏移；改名去重；旧 run 锁定 version_set。
  - AutoDL+本地 pytest：**20 passed**（`runs/probes/pytest_s09_s11_a001.txt`）。
- **未声称：** 分块/索引（S12）、真实研究 Agent、检索就绪。
- **下一步：** S12 分块与版本化索引。

### change_20261026_s06_s08_001｜S05 a002 重验 + S06—S08 PASS（四环境/探针/最小联通）

- **Type：** C类状态；B类实现（envs/locks/scripts/最小 API·UI）；无正式 SFT、无完整五页产品。
- **Authority：** 用户批准计划「完成 S06–S08」；扩容后确认继续；接受 4080 SUPER（D-20261026-4080）。
- **Scope：** S05 a002、四环境与冻结模型、S07 探针、S08 UI→API→base、REMOTE/HANDOFF/progress/locks/manifests。
- **Before：** S05 a001 FAIL（50GiB）；S06 BLOCKED；无项目四环境/模型；无 UI/API。
- **After：**
  - S05 a002 **PASS**：盘 `/root/autodl-tmp` **100.00GiB**；4080S DEVIATION_ACCEPTED。
  - S06 a001 **PASS**：`envs/{app,infer,train,judge}` Python 3.11.17；`locks/*.txt`；四模型 revision 冻结（见 manifests）。
  - S07 a001 **PASS**：CUDA/tokenizer/vLLM guided JSON+临时 LoRA+Writer→base/训练 LoRA/embed-rerank/app/外部回退/分时。
  - S08 a001 **PASS**：FastAPI `:6008` + Streamlit `:6006` + vLLM `127.0.0.1:8001`；未鉴权 401；短问 e2e 真实回答；本机隧道可开。
  - U-07/U-09/U-10 关闭；HANDOFF 快照 `S06_S08_MIN_LINK`。
- **未声称：** 完整研究助手、索引/Worker ready、教师/Tavily 已通、公开托管、正式 SFT。
- **费用：** 控制台价约 ¥1.66/时；S08 后服务可能仍占 GPU≈26GiB——不用时 `serve.py stop` 或关机。
- **下一步：** S09（API、任务和数据库事务）。

### change_20261026_s04_s05_001｜SSH 稳定连接与 S04 PASS / S05 FAIL（容量）

- **Type：** C类远程与步骤状态更新；无四环境安装、无模型下载、无 UI/API 部署。
- **Authority：** 用户批准计划「SSH 稳定连接 + S04/S05」；提供 AutoDL SSH（密码仅入 `private.env`）。
- **Scope：** SSH 密钥与别名、REMOTE、S04 费用/访问、S05 数据盘与小备份、HANDOFF/progress。
- **Before：** 快照 `S01_S03_LOCAL_PREP`；REMOTE 无实例；S04—S50 未开始。
- **After：**
  - SSH：`evidence-agent-autodl` 密钥登录 VERIFIED；host key ED25519 已登记。
  - 实例：`autodl-container-12ce4dade8-72ec6d56`；GPU=RTX 4080 SUPER 32GB（偏离 4090）；驱动 580.142；盘 `/root/autodl-tmp` **50GiB**。
  - WORK_ROOT=`/root/autodl-tmp/evidence-agent` 已建树并同步 repo；`paths.yaml` active 指向远端。
  - S04 a001 **PASS**：`runs/billing/`、`docs/operations/{access,cost_control}.md`、`web_verification.md`。
  - S05 a001 **FAIL**：容量门禁；小备份 `bak_s05_0001` 本机/远端 SHA 一致且恢复抽查通过。
  - HANDOFF 快照 `S04_S05_REMOTE_BOOTSTRAP`；S06 **BLOCKED** 直至扩容≥100GiB 并重验。
- **未声称：** 小时价已知、企业端口映射已开通、教师/Tavily 可用、四环境/模型就绪。
- **费用：** 实例探针时在线；金额 UNKNOWN；未付费 API。建议控制台轮换曾在聊天暴露的 root 密码；空闲请关机。
- **下一步：** 扩容或换机 → 新 probe → 接受/拒绝 4080 偏离 → 再进 S06。

### change_20261025_s01_s03_001｜本地导入与 S01—S03 验收 PASS

- **Type：** B类工程落位＋C类状态更新；无训练/租机/模型下载。
- **Authority：** 用户要求按执行方案完成 S01—S03；Rule 四文件布局沿用已授权修订。
- **Scope：** WORK_ROOT 本地准备区 `d:\1-实习\项目\EvidenceAgent`；`repo/` Git；S01—S03 文档与上游冻结。
- **Before：** 仅根级 Rule 四文件与两份中文说明；S01—S50 未验收；无 repo 树。
- **After：**
  - 相对目录树已建；Rule 位于 `repo/Rule/`。
  - 原说明归档哈希匹配；执行方案导入后修订 Rule 子树为四文件（输入 `0acf70f5…` → 修订后 `6cd1bb01…`）。
  - S01：`acceptance_registry`、`progress`、`decision_log`；`L/steps/S01/a001/` PASS。
  - S02：`directory_registry`、`paths.yaml`、`.gitignore`、`git init -b main`（无 commit、无远程）；`L/steps/S02/a001/` PASS。
  - S03：上游 commit `e85c6b98…` 快照于 `third_party/deepagents/`；`THIRD_PARTY_NOTICES.md`、`baseline_matrix.md`、`mf_upstream_deepagents_0001.json`；`L/steps/S03/a001/` PASS。
- **未声称：** 产品可用、环境安装、GPU 探针、训练、公开托管、六系统可运行。
- **远程／费用：** 无 AutoDL 实例操作；无付费 API。
- **HANDOFF：** 快照改为 `S01_S03_LOCAL_PREP`；下一步 S04。
- **关联：** decision_log D-20261025-01…05；U-13（上游可拉取）已在本机验证。

### change_20261025_rule_init_002｜四文件文档检查通过

- **Type：** C类文档验证状态更新；承接 `change_20261025_rule_init_001`，不改技术设计。
- **已执行检查：** 四个规范文件恰好齐全；UTF-8可读；四文件相对链接有效；Markdown表格列数一致；代码围栏配对；HANDOFF的S01—S50完整且有序；两份输入SHA与实际字节一致；未带入旧项目标识、服务器或个人路径。
- **结果：** 上述文档检查PASS。这里只是Rule文档质量检查，不是S01/S02、GPU、产品、训练或正式评测PASS。
- **交付：** 四个独立Markdown，可另提供仅含 `Rule/` 与四文件的ZIP；压缩包需在生成后核对成员和字节。
- **远程／费用：** 无项目远程执行、模型下载或训练；现有账号/实例状态仍未知。
- **下一步：** HANDOFF的导入清单保持有效；导入后登记实际路径与Git，再按步骤验收。

### change_20261025_rule_init_001｜EvidenceAgent 四文件 Rule 初始化

- **Type：** B类工程控制面初始化＋C类文档状态登记；没有执行项目训练或实验。
- **Authority：** 用户明确要求“仿照这几个文件的功能，为我初始化并生成新项目的四个md文件”，并已确认此前EvidenceAgent按步骤执行方案与目录要求。
- **Scope：** `repo/Rule/{README,HANDOFF,CHANGELOG,REMOTE}.md`；与执行方案第0节Rule入口相关的布局修订。
- **Before：** 已有原项目说明与S01—S50执行方案；执行方案为Rule预留 `project_rules.md`，尚未在本次任务中初始化新项目四文件。
- **After：** 四文件分别承担总规则、当前交接、变更追溯、远程登记；Rule规范正文以README为唯一入口，不另建第五份project_rules正文。
- **关键适配：** 保留旧文件的职责、读取顺序、reuse-first、变更分类、证据与交接方式；新项目使用S01—S50、单卡分时、真实工具轨迹、SFT/DPO、固定评测与费用上限。
- **未沿用：** 旧项目的服务器、用户名、SSH信息、研究锁、论文版本、实验分数、数据数量、历史PASS和关机结论。
- **输入：** 原《项目说明.md》、已交付《EvidenceAgent_执行方案.md》与用户本轮提供的四份旧Rule附件；前两份字节哈希见HANDOFF第3节。
- **产物：** `Rule/README.md`、`Rule/HANDOFF.md`、`Rule/CHANGELOG.md`、`Rule/REMOTE.md`；可打包为只包含这四文件的Rule目录。
- **网页核验：** 复核AutoDL端口/自定义服务条件及固定vLLM文档；链接和事实边界写入REMOTE，不代表账号、实例或模型已可用。
- **当前工程状态：** DOCUMENTATION_ONLY。代码仓库、实例、环境、数据和实验进度NOT_REGISTERED或NOT_REPORTED；S01—S50没有在本次任务中取得工程验收PASS。
- **目录修订：** 导入时将execution_plan和directory_registry中的 `Rule/project_rules.md` 改为四文件布局；原先交付的执行方案本次未直接改写。该修订只影响规则落位，不改变技术、预算或实验目标。
- **验证范围：** 四文件名称与职责、相互链接、目录约定、S步骤映射、输入SHA和未知事实标记。文档校验与工程验收必须分开；当前实例状态、Git和运行结果尚待实测。
- **成本/远程：** 本次未启动AutoDL任务、模型下载、正式训练、批量API或项目实验；账号既有费用和其他运行未知，不能据此标“所有实例可关机”。
- **下一步：** 按HANDOFF第5节导入→登记→S01/S02核验；后续只在真实前置证据通过后推进。
- **关联：** HANDOFF活动快照 `INIT_RULE_FILES`；README规则版本1.0；REMOTE实例登记状态NOT_REGISTERED。

后续记录按本文件规则新增。不能把此条“文档初始化”复制为S01—S50已完成的依据。

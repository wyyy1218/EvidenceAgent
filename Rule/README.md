# EvidenceAgent 项目总规则

> 规则版本：1.0｜初始化日期：2026-10-25  
> 适用范围：EvidenceAgent 开发、数据、训练、评测、运行、复现和交付。  
> 本文件是 `Rule/` 的规范入口；它不是仓库根目录面向访客的产品 README。

## 1. 四个文件的职责与读取顺序

`Rule/` 是项目的持久化工程控制面。新的开发者或 Agent 应能够仅凭项目内文件定位当前状态、有效设计和下一步，不依赖某个聊天窗口的记忆。

| 文件 | 负责什么 | 不负责什么 |
| --- | --- | --- |
| [README.md](README.md) | 权威顺序、目录、设计锁、执行、同步与数据治理规范 | 不堆积每次运行日志 |
| [HANDOFF.md](HANDOFF.md) | 唯一当前交接快照、已知状态、阻塞和下一步 | 不将全部历史追加成多个“当前版本” |
| [CHANGELOG.md](CHANGELOG.md) | 变更分类、授权依据、影响范围、追加式历史和provenance | 不通过写一条记录就自行授权设计变更 |
| [REMOTE.md](REMOTE.md) | 新项目实例、环境、模型、运行、用量和恢复登记 | 不继承旧项目服务器与实验结论 |

每个新会话先读本文件和 HANDOFF。涉及远程、环境、模型、GPU、下载、数据同步时，再读 REMOTE；涉及设计、训练、正式实验、版本冻结或发布时，读 CHANGELOG 的规则和相关记录。之后读取所涉执行步骤及原始证据。

不要为了形式反复扫描全部历史或重装环境。已有有效记录且输入、环境和作用范围没有变化时直接复用；有失效信号才重新核验。

## 2. 文档权威与冲突处理

### 2.1 权威顺序

1. 用户最新明确指令，包括已在本项目会话中给出的持续授权。
2. 有明确授权依据和覆盖范围的设计修订记录；只在其指定范围覆盖旧规格。
3. `docs/source/project_spec_v1.0.md`：原《项目说明.md》的归档，保留原始设计与来源。
4. `docs/plan/execution_plan.md`：已确认的执行依赖、验收、失败分支与明示的执行补充。
5. `docs/decisions/decision_log.md`：落实上述设计的具体决策；不能凭内部记录推翻用户要求。
6. 本 `Rule/` 的工程治理规则。
7. 代码、配置、锁、manifest和实际验收记录；它们证明实现与观察，不自动成为新的设计授权。
8. 历史草稿、旧产物、临时文件和未核实聊天描述。

原说明归档不直接改写。实际运行唯一业务配置为 `configs/project.yaml`；路径配置为 `configs/paths.yaml`。配置与权威设计或正文出现冲突，先阻断相关运行、统一版本，不允许不同模块各猜一套。

### 2.2 文件存在不代表工程已经验收

这次只初始化四个 Rule 文件。不能因此把 S01/S02、环境、GPU、数据、训练或部署标为 PASS。其他文档在交接快照中有输入记录，但导入项目路径、Git状态和工程完成情况尚需执行时确认。

## 3. 目录规范与本次布局修订

### 3.1 唯一项目根目录

工作根目录记为 `WORK_ROOT`，在确认过的数据盘上选定，默认候选为 `/root/autodl-tmp/evidence-agent`。真正 Git 仓库是 `WORK_ROOT/repo/`；不能把整个数据盘工程误当仓库。

```text
evidence-agent/
├── repo/
│   ├── Rule/
│   │   ├── README.md
│   │   ├── HANDOFF.md
│   │   ├── CHANGELOG.md
│   │   └── REMOTE.md
│   ├── configs/                 project.yaml、paths.yaml、schemas/、prompts/
│   ├── locks/                   app.txt、infer.txt、train.txt、judge.txt
│   ├── src/evidence_agent/      api、ui、ingestion、retrieval、tools等模块
│   ├── baselines/
│   ├── training/                data、sft、preferences、dpo
│   ├── evaluation/              adapters、metrics、protocols、review、reporting
│   ├── scripts/
│   ├── tests/                   unit、contract、integration、boundary、probes、fixtures
│   ├── examples/                docs、requests、outputs
│   ├── third_party/deepagents/
│   ├── docs/                    source、plan、decisions、architecture等
│   └── artifacts/               仅大文件索引artifact_index.json
├── envs/                        app、infer、train、judge、cache
├── models/                      base、embedding、reranker、judge，按revision分目录
├── data/                        原始资料、快照、解析、索引、任务、SFT/DPO数据、manifest
├── artifacts/                   实际检查点、适配器、导出、报告、发布包
└── runs/                        验收、探针、轨迹、训练、评测、账本、系统、备份与临时区
```

完整层级继承执行方案第0节；本树只浓缩职责，不授权随意新增目录。根目录README、LICENSE、pyproject.toml等文件仍按执行方案保留。

**本次已授权的布局修订：** 用户指定采用上述四文件体系，因此由 `Rule/README.md` 承担此前 `Rule/project_rules.md` 的规范职责，不再另建第五个规则入口。导入时同步修订 `docs/plan/execution_plan.md` 的 Rule 子树和 `directory_registry.md`，记录至CHANGELOG；只改目录与规范入口，不改S01—S50的技术或验收内容。此前交付的执行方案原文件本次未被直接改写。

### 3.2 路径与命名

| 记号 | 指向 |
| --- | --- |
| R | WORK_ROOT/repo |
| E | WORK_ROOT/envs |
| M | WORK_ROOT/models |
| D | WORK_ROOT/data |
| A | WORK_ROOT/artifacts |
| L | WORK_ROOT/runs |

- `Rule` 大小写固定，四个文件名固定大写；不要建 `rule/`、`rules/` 或另一份总规则。
- 其他目录、模块、配置键使用小写 `snake_case`。模型/工具等必要外部标识保持官方拼写。
- S01—S50、attempt_id、dataset_id、run_id、experiment_id等是执行方案允许的标识，不套用旧项目禁止步骤编号的规则。
- 不用 `final_final`、`new_results`、`latest2` 等不明名称；不以聊天轮次、个人姓名或机器用户名命名正式对象。
- `agent`、`prompt` 等属于本项目必要技术术语，可以出现在已登记的模块和配置名中；不能把旧论文匿名规范误用为禁止技术术语。
- 代码通过根目录相对路径或配置寻址；私有绝对路径只在私有运行配置登记。
- 每类新增产物先核对 `docs/plan/directory_registry.md`，放入既有目录或其已登记ID子目录；新增公共目录先登记再使用。
- 用户上传原名只作显示字段，磁盘存储用系统ID；不要将原文件名当路径执行。

## 4. 当前技术与研究设计锁

下表是原说明和已确认执行方案的摘要，不替代完整参数表。首次实机兼容性仍必须验证。

| 主题 | 当前锁定要求 |
| --- | --- |
| 产品 | 文档/网页可追溯证据研究助手，网页＋HTTP API；中文为主、中英文资料 |
| 架构 | 单个顺序研究控制器，固定Writer与Verifier；自建受控LangGraph图 |
| 上游 | Deep Agents0.7.32，提交e85c6b98087861512d2c5240305e16cfac68a746；B2明确为适配版 |
| 策略 | Qwen/Qwen3-4B-Instruct-2507＋经开发集选择的LoRA |
| Writer/Verifier | 同一base，独立固定提示，不加载策略adapter；核验是模型判断 |
| 教师 | 百炼北京qwen3.8-max-0902非思考；不可用时本地base回退并显式登记 |
| 训练 | QLoRA SFT后一次离线动作DPO；不做PPO/GRPO，不称在线Agent RL |
| 检索 | bge-m3 dense CPU、BM25、RRF、bge-reranker-v2-m3 CPU、FAISS IndexFlatIP |
| 应用 | FastAPI/Pydantic、Streamlit、SQLite WAL；Worker并发1，队列10 |
| 工具 | local_search、web_search、read_evidence；结束动作为finish或abstain |
| 证据 | 搜索摘要仅候选；成功读取的版本化原文才可引用；页码/行号/区间可核对 |
| 数据 | HotpotQA600/100/200；中文240/60/100；gold永不进入策略输入、工具和索引 |
| 训练最低门槛 | SFT训练状态≥2000，目标4000/800；DPO训练偏好≥300，目标600/100 |
| 评测 | B0/B1/B2/E0/E1/E2；dev选型，test300题只运行与报告；计划最终2544次 |
| 资源 | 单RTX4090 24GB，CPU≥12核、RAM≥64GiB、数据盘≥100GiB；训练推理分时 |
| 费用 | 总1500元；GPU600/120小时且采购≤5元每小时；教师评分300、搜索100、存储100、预留400 |
| 产品边界 | 不做OCR、任意代码执行、多卡、在线RL、跨用户权限系统等首版排除项 |

以下变化属于设计影响：替换训练目标/模型、改变划分/金标准/偏好规则、改预算或发布门槛、用新Writer破坏对比、测试后调参、扩展首版范围。按CHANGELOG分类处理。

## 5. 执行、复用和验收协议

### 5.1 开始工作

1. 明确当前S步骤、目标、输入、输出、通过与失败分支，先核对HANDOFF是否有有效前置证据。
2. 核对Git分支、HEAD与工作区差异；远程相关再核对当前实例和active run。
3. 遵守“登记→manifest/交接→必要的只读核验→复用”。仅在对象缺失、失效或不合格时重新下载、安装、采集、训练或评测。
4. 阅读已有文件可回答的问题，继续在已授权范围执行，不重复把常规实现选择交给用户。
5. 新环境、适配器、模板、截短、训练器或关键流水线先做最小探针；探针通过不等于正式实验完成。

### 5.2 结果、数据与失败

- 状态/动作/结果使用统一Schema；状态不含gold，completion只学动作JSON，不学习外部工具正文。
- 保留来源版本、哈希和原文位置；更新资料不能覆盖旧运行引用。
- 所有模型、工具、重试、修复、失败、固定核验节点均计资源；缓存命中与实际API费用分开。
- 不静默丢行，不将失败记成功，不把无claim支持率记100%，不把未找到等同不存在。
- NaN、OOM、超时和非法输出按执行方案固定分支处理；已有长度/教师回退无需重复申请同一授权，但要登记并重验受影响部分。
- 不覆盖原始轨迹、偏好、检查点、人工标注和正式测试输出；更正产生新记录、新版本及影响说明。
- 效果不理想不是改测试集、阈值、分母或设计的理由；模型评分不能自动升级为人工真值。

### 5.3 完成工作

1. 核对进程退出、输出数量、覆盖范围、异常与实际费用。
2. 产物与验收证据写入规定目录，步骤记录为 `L/steps/<step_id>/<attempt_id>/`。
3. 更新 `docs/plan/progress.md`；HANDOFF只维护一个当前快照，旧状态留CHANGELOG与原始记录。
4. 触发变更或重要provenance时追加CHANGELOG；远程事实改变同步更新REMOTE。
5. 备份唯一产物，按Git和同步规则保存源码；需要关机时核对具体实例和活动进程后再操作。

## 6. 状态标签：事实、步骤与准备度分开

| 类型 | 标签与含义 |
| --- | --- |
| 事实 | VERIFIED当前作用范围已实测；OBSERVED材料或历史观测；EXPECTED设计目标；MUST_VERIFY_ONCE首次相关操作前检查；UNKNOWN未知；NOT_REGISTERED未登记；STALE已出现失效信号；DEPRECATED历史停用 |
| 执行 | NOT_REPORTED尚无实际执行报告；NOT_STARTED已确认未开始；IN_PROGRESS进行中；COMPLETED动作结束但未必过验收 |
| 验收 | NOT_EVALUATED未验收；PASS通过；REWORK返工；BLOCKED前置缺失；DEGRADED回退/降级；STOPPED条件触发停止 |
| 阶段 | DOCUMENTATION_ONLY仅文档就绪；PRODUCT_READY产品门槛通过；TRAINING_COMPLETED正式训练及评测证据齐全；RELEASE_READY交付通过 |

VERIFIED必须附环境、输入版本、时间及证据。实例迁移、输入哈希变化、环境锁改变、重启后服务状态等需按影响重验；不能把历史VERIFIED当作当前在线证明。

训练完成、效果通过、发布入选、目标规模达到四个结论分开记录。发布E0不代表DPO实验完成；DPO不入选也不代表实验一定失败。

## 7. 数据隔离、训练与正式评测约束

1. 先按项目/官方split划分再出题。训练/开发/测试的题目近重复、支持文档与来源哈希按协议检查，不能生成全部任务后随便随机分割。
2. 轨迹工具真实执行，教师看与学生相同状态。尝试次数受执行方案上限约束，不能无限采到成功或复制补量。
3. 中文开发/测试金标准人工核验；证据不足题必须有移除关键证据的构建记录，replay并集也不能泄漏答案。
4. SFT核验prompt标签-100、动作JSON目标、EOS/padding和模板。训练集低于最低规模不跑正式训练。
5. DPO仅同状态不同合法动作；同快照/历史/预算，固定SFT后续策略，第二seed复核；reference是冻结同一SFT，不是关闭LoRA的base。
6. 导出到实际vLLM再次核验base/adapter路由，Writer与Verifier保持base；训练端量化推理不能替代部署探针。
7. 发布选择只用160开发题。相对E0，Q/G下降各≤0.02，无答案错误确定作答增幅≤0.02，动作参数合法率≥0.98且无越权/预算绕过。
8. 合格候选按Q距最高≤0.01、再G距最高≤0.01、再平均总Token更少选；完全相同优先SFT、DPO、E0。
9. 最终测试冻结前预登记系统、子集、统计、失败分母与补跑规则。超时和工具失败不从分母偷偷移除；测试后修复用新版本并声明测试已见。
10. 单人盲审就写单人，不虚构一致性、实验、已安装版本或显存性能。所有图表可从实际原始结果重算。

## 8. Git、文件与公开交付

源码、Rule、配置模板、锁、Schema、文档和小型可公开夹具可用Git管理；模型、环境、原始用户资料、大型输出和私有配置不入Git。

- Git地址、仓库是否存在、默认分支均需核实，不因为命名了repo目录就声称已建远程仓库。
- 同步前看branch/HEAD/diff；工作区有未整合变更、分支分叉或detached HEAD时先保留差异，不强制覆盖或force push。
- 原方案以AutoDL JupyterLab开发为主，不强制套用旧项目“Windows编辑后推远程”的流程。在哪里编辑，就登记哪里的工作区与提交。
- 代码提交不等于获准公开发布；实际向外发布按用户已给授权和平台条件执行。
- Rule默认作内部交接材料；公开仓库或发布包只放逐文件审查过的脱敏版本。新项目是开源作品，不机械继承旧论文匿名要求。
- 不在Rule、Git、脚本、日志、公共配置或发布包写密码、私钥正文、token、cookie。真实密钥只在受权限保护的 `L/system/private.env` 或运行环境；不回显到日志。
- 可按必要范围登记host/port/user、公钥指纹、已核实key路径，公开前评估是否需要脱敏。
- 公开代码许可不覆盖数据、模型和上游代码许可；保留第三方声明与分发限制。

## 9. 预算、实例和公开访问

价格、余额、实例地址和权限是运行时事实，不预填成VERIFIED。总额与各项上限以配置和账本为准，定期按实际账单核销未知计费。

预算不够先停止live与超目标采集，再按预登记减少允许停止的补充项；主测试不得按结果删题，训练最低规模和必要安全/掩码/reference验收不降低。仍不够就停止长任务、备份并报告未完成，不自动充值或上多卡。

AutoDL有端口账号条件，自定义服务链接的使用与转发也有约束；本人访问、录屏展示、公开在线托管是不同交付项。具体核验与官方来源见REMOTE。不能因存在6006/6008映射就宣称已可公开展示。

## 10. Rule维护权限和首轮导入

- README核心规范、设计锁或发布规则仅在用户已明确授权的范围变更；未获授权的实质设计变更先提出具体修订及影响。
- 原方案明确的自动回退、已授权例外、可逆修复和事实更新可直接执行并登记，不反复索要同一确认。
- HANDOFF每次实质进展后更新当前快照；REMOTE按新事实更新；CHANGELOG只追加新记录，纠错不改旧历史。
- 四文件之间通过change_id、step_id、run_id和manifest互相指向，不在多个文件复制大量日志。

首次导入：把本四文件放入 `repo/Rule/` → 核对原说明/执行方案并导入各规范路径 → 更新Rule目录修订 → 登记实际Git和工作根目录 → 按HANDOFF从S01开始验收；若已有工作，先复用其真实证据再标状态。

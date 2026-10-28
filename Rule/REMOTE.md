# EvidenceAgent 远程、环境、模型与运行登记

> 初始化日期：2026-10-25｜登记版本：1.5  
> 当前接入实例：`autodl-container-r2xe8ht31g-00882b05`｜SSH：`2026-10-28` 端口 `28394`；远端克隆进行中，资源未重验  
> 上一实例（历史）：`autodl-container-8f1147b36e-e494c777`｜SSH：`2026-10-27` 端口 `35832`；曾完成克隆重验与 S42 暂停  
> 更早实例（历史）：`autodl-container-12ce4dade8-72ec6d56`｜实机核验：`2026-10-26`（`probe_s05_host_a002`）  
> 本文件区分“设计目标”“真实观测”“当前运行”，不能把计划参数当已部署事实。密码与密钥只在 `runs/system/private.env`，不写入本文件。

## 1. 当前远程结论

**2026-10-28 15:40（当前）：** hostname `autodl-container-r2xe8ht31g-00882b05`；S01—S48 PASS；vLLM:8001 + API:6008 + UI:6006 服务抽验 OK；公开托管未提供；`bak_s48_a001` 已拉本机。

**2026-10-28 14:35（历史）：** S42–S44 PASS；tmux `formal_chain` 跑 S45（DRBench12 + live20）；vLLM:8001；Tavily 已设；本机 ~30s 快照环 OK。

**2026-10-28 14:04（历史）：** S42/S43 PASS；`formal_chain` 跑 S44（budget≈69/240）。

**2026-10-28 11:26（Gate0+续跑，历史）：** 盘 `/root/autodl-tmp` ≈71G/25G avail；4080 SUPER；WORK_ROOT 齐；S42 tmux `s42` 续跑中（b0≈270+/300）；看门狗 `formal_chain` 串跑至 S45。

**2026-10-28 10:56（连接重绑，历史）：** 端口 `28394`；密钥 OK；当时克隆中未做资源核验。

**2026-10-27 21:05（S42 过夜暂停，历史／上一实例）：** S42 `eval_main_s42_0001` 已优雅停止；**55/1800**（`b0`=55）写入 `results_b0.jsonl`，`--resume` 可续。tmux/vLLM 已停。本机已同步同目录备份。

**2026-10-27 20:50（S41 最终冻结后，历史）：** S01—S41 PASS。发布策略 **E0**；冻结 `mf_s41_freeze_0001` / 2544 清单 / `config_bundle_hash=3c8df0d2…`。

**2026-10-27 13:50（克隆完成重验，历史）：** 上一实例上确认克隆完成并重验：WORK_ROOT≈46G；盘 100G/55G avail；4080S 32GB；四环境与 adapter 就绪。

**2026-10-27 11:43（连接重绑，历史）：** 端口曾改 `35832`；当时克隆进行中未做资源核验。

**2026-10-26 13:07（更早实例历史）：** S05→S08 PASS；4080S / 100GiB。

| 字段 | 当前记录 | 状态 |
| --- | --- | --- |
| Provider | AutoDL（seetacloud westc 接入） | CONNECTION_OK（2026-10-28） |
| 地域／区域 | SSH 主机名含 `westc`；控制台精确区域码未核 | PARTIAL |
| Instance ID / name | hostname `autodl-container-r2xe8ht31g-00882b05` | OBSERVED_ON_CONNECT |
| 控制台电源状态／计费模式 | SSH 可达=开机中；小时价未读控制台 | RUNNING_OBSERVED；价 UNKNOWN |
| SSH host / port / user | `connect.westc.seetacloud.com` / `28394` / `root` | CONNECTION_OK |
| SSH别名／key路径 | `evidence-agent-autodl`；`~/.ssh/evidence_agent_ed25519`；Keepalive 开 | CONNECTION_OK |
| Host公钥指纹 | ED25519 `SHA256:EPstg8jNN+u3Bs1JyQOqlBeq3w+a4VynoJAe48YnIV0` | CONNECTION_OK（与旧口相同） |
| 本人访问方式 | 6006/6008 需企业认证；个人可用 SSH 隧道 | DOC_VERIFIED |
| 公共演示方式 | 默认录像/复现包 | NOT_REGISTERED |
| WORK_ROOT实际路径 | 预期 `/root/autodl-tmp/evidence-agent`（克隆中未核） | PENDING_REPROBE |
| Git仓库／branch／HEAD／diff | 克隆完成后核 | PENDING_REPROBE |
| 数据盘挂载／可用空间 | 上一实例曾 100G；本机未重测 | PENDING_REPROBE |
| GPU／显存／驱动／CUDA | 上一实例曾 4080S；本机未重测 | PENDING_REPROBE |
| CPU／RAM 配额 | 未重测 | PENDING_REPROBE |
| 实例小时价 | 未读控制台 | UNKNOWN |
| 当前env/模型/cache | 克隆中；继承结论不可用 | PENDING_REPROBE |
| tmux／服务进程／active run | 未查进程（克隆中） | UNKNOWN |
| 最近同步／备份／账单核对 | 本机仍有 S42 55 条备份；远端克隆结束后再对齐 | SSH_REBIND_CLONE_PENDING |

更新VERIFIED时填写“实际值、时间、核验方法、证据路径、作用范围”；不只把状态标签翻转。真实密码与 API 密钥只放私有配置。

## 2. 目标资源与采购门槛

以下都是原方案目标，不是本次观测结果。

| 对象 | 目标／门槛 | 实测记录位置 |
| --- | --- | --- |
| 实例 | 普通容器、按量、单卡；不买包月 | L/probes、L/billing |
| GPU | RTX4090 24GB×1 | L/probes |
| CPU / RAM | ≥12逻辑核／≥64GiB | L/probes |
| 系统 | Ubuntu22.04、x86_64、Python3.11 | L/probes |
| 驱动 | 原方案保守门槛≥570.26，CUDA12.8 wheel须实测 | L/probes |
| 数据盘 | 可用总容量≥100GiB，确认真实挂载 | R/configs/paths.yaml、L/probes |
| 采购 | 满足条件后按小时价升序；≤5元/小时，同价先内存、再实例标识 | L/billing |
| GPU费用/小时 | ≤600元、≤120实例小时，均为控制上限 | L/billing/ledger.jsonl |
| 不满足 | 保存筛选条件等待或修前置，不擅自上多卡/突破预算 | HANDOFF、CHANGELOG |

24GB可运行所选训练/推理属于工程预期，必须探针确认，不能从模型参数量推断完整显存保证。

## 3. 路径、隔离、缓存与容量

R/D/E/M/A/L定义见README。先确认WORK_ROOT所在真实数据盘，再将项目落位；禁止只凭目录名字认定是数据盘。

| 目录 | 用途 | 原方案容量控制值 |
| --- | --- | ---: |
| WORK_ROOT/repo | Git源码和小型文档/配置 | 2GiB |
| WORK_ROOT/envs | app/infer/train/judge、wheel缓存 | 35GiB |
| WORK_ROOT/models | base/embedding/reranker/judge，按完整revision | 20GiB |
| WORK_ROOT/data | 原文、快照、位置、索引、任务、训练数据、SQLite | 15GiB |
| WORK_ROOT/artifacts | 检查点、adapter、导出、报告、发布 | 10GiB |
| WORK_ROOT/runs | 实际日志、验收、费用、临时与备份暂存 | 8GiB |
| 余量 | 临时下载与操作空间 | 10GiB |

总计100GiB是控制值，不是已占用量。实际超配额先核总空间和预算，清理可重建缓存前先保证唯一产物已有独立备份；不能删除唯一adapter或原始实验输出腾盘。

环境、HF、pip/wheel和转换临时区按paths.yaml落到已登记位置，不在系统盘和数据盘各缓存一份。临时下载/转换放 `L/work/<operation_id>/`。任何旧项目目录都不作为默认运行依赖；要复用必须核路径、版本、哈希、许可，登记后作为输入，不修改旧项目。

SQLite位于 `D/app/`，WAL/SHM与一致性备份一起考虑；原文件和模型不塞BLOB。代码仓库内 `R/artifacts/` 只有索引，真实大文件在A，不能混放。

## 4. 环境登记：目标与安装事实分开

| 环境 | 固定目标 | 当前安装状态 |
| --- | --- | --- |
| E/app | Deep Agents0.7.32、LangGraph、FastAPI、Pydantic、Streamlit、FAISS等；未定依赖首解析后锁 | INSTALLED（`locks/app.txt`；probe_s06_envs PASS） |
| E/infer | vLLM0.10.2，Torch遵从该版依赖，不手工覆盖为训练版 | INSTALLED（vllm 0.10.2 / torch 2.8.0+cu128） |
| E/train | Torch2.8.0 CUDA12.8、Transformers4.56.2、PEFT0.17.1、TRL0.23.1、bitsandbytes0.47.0 | INSTALLED（`locks/train.txt`） |
| E/judge | MiniCheck及其官方检查器包装所需依赖，独立锁 | INSTALLED（minicheck 可导入） |

Python统一3.11；锁文件为 `R/locks/{app,infer,train,judge}.txt`。首次记录uv版本、解析时间、来源、包版本和制品哈希，此后按锁安装。表中UNKNOWN表示尚未核验，不能当安装失败。

依赖解析失败时保留报告，在干净环境按固定核心包重试一次；仍冲突阻断，修复作为明确环境补丁，重探针后再冻结，不静默升级。

## 5. 模型、来源与适配器登记

| 角色 | 目标标识 | revision/哈希与现状 |
| --- | --- | --- |
| 基座 | Qwen/Qwen3-4B-Instruct-2507 | `cdbee75f17c01a7cc42f958dc650907174af0554`；manifest `mf_model_base_0001` |
| Embedding | BAAI/bge-m3，仅dense，CPU | `5617a9f61b028005a4858fdac845db406aefb181`；`mf_model_embedding_0001` |
| Reranker | BAAI/bge-reranker-v2-m3，CPU | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`；`mf_model_reranker_0001` |
| 英文辅助评分 | MiniCheck官方包装＋flan-t5-large检查器制品 | HF `lytang/MiniCheck-Flan-T5-Large` @ `96eafd01…`；`mf_model_judge_0001` |
| API教师 | 百炼北京qwen3.8-max-0902，非思考 | 账号权限、响应model、当日价格和条款待核 |
| 教师回退 | 本地同一base候选生成 | 条件触发后记录，不静默混用教师版本 |
| SFT adapter | 正式训练后生成 | 当前NOT_REGISTERED，无真实checkpoint哈希 |
| DPO adapter | SFT后DPO生成 | 当前NOT_REGISTERED；reference必须冻结同一SFT |
| 发布策略 | E0/E1/E2按完整dev160选择 | 尚未选择，不预设DPO一定入选 |

每个本地模型记录：官方来源、许可、完整revision SHA、文件SHA、tokenizer与chat template、物理路径、大小、探针。不能只保存main。API模型记录固定名称、地域、请求/响应ID、用量与原始输出；不伪造供应商没有提供的源码SHA。

上游代码固定Deep Agents0.7.32提交 `e85c6b98087861512d2c5240305e16cfac68a746`，这是代码目标，不是模型revision。API教师和Tavily的密钥只在私有配置，不进入此表。

新会话先查登记和文件哈希，再下载；电脑默认只作浏览器、连接和备份端，不重复下载全量模型到本地。

## 6. 服务、端口和实际访问

| 服务 | 设计监听 | 当前进程／可达性 |
| --- | --- | --- |
| Streamlit UI | 0.0.0.0:6006，独立口令 | UNKNOWN |
| FastAPI | 0.0.0.0:6008，Bearer Token | UNKNOWN |
| vLLM | 127.0.0.1:8001，不直接公开 | UNKNOWN |
| Worker | 无公网监听，研究任务并发1、队列10 | UNKNOWN |

vLLM设计：一套BF16基座、LoRA rank上限16、最大长度8192、显存比例0.80、max_num_seqs2。policy显式请求发布adapter；Writer/Verifier显式请求base。不能因启用LoRA就让全部请求默认进入策略adapter。

vLLM0.10.2结构化输出应查该固定版本文档，接口名不能从最新文档照抄；结构化输出仍须业务Schema、candidate权限和预算检查。

### 6.1 本人访问与公开托管

AutoDL端口页列出6006/6008映射及账号条件；自定义服务协议含使用与转发约束。本人访问、录屏展示、公共托管分别验收，不能因为能打开个人入口就向第三方转发。

账号不具备映射条件时检查官方SSH隧道路径。该路径是原“只用浏览器”前提的条件性例外，只增加连接工具，不引入本地CUDA或模型部署；电脑系统未核实，不假定必须使用某个Windows客户端。

本人访问不可达标BLOCKED并记录；公开托管条件未确认时提供脱敏录像、仓库和复现包，写清未提供公开在线入口，不擅自换平台或承诺全天在线。

### 6.2 官方核验链接

以下于2026-10-25查阅，网页公开事实不等于账号能力或实机结果；真正执行时核对当前账号界面和适用条件。

| 官方来源 | 本项目使用范围 |
| --- | --- |
| [AutoDL开放端口](https://www.autodl.com/docs/port/) | 端口映射与账号条件 |
| [AutoDL自定义服务补充协议](https://www.autodl.com/docs/service_agreement/) | 访问和链接转发限制，决定展示方式 |
| [AutoDL SSH隧道](https://www.autodl.com/docs/ssh_proxy/) | 本人访问备选路径 |
| [vLLM0.10.2结构化输出](https://docs.vllm.ai/en/v0.10.2/features/structured_outputs.html) | 固定版接口与探针依据 |
| [vLLM0.10.2服务参数](https://docs.vllm.ai/en/v0.10.2/cli/serve.html) | 服务与LoRA配置需按该版实测 |

## 7. 长任务前的最低核验与资源切换

### 7.1 每个新实例或环境变更后

1. 核对host/实例ID、数据盘、可用空间、GPU、驱动、CUDA、系统与网络；与期望不符先停。
2. 核对repo的branch/HEAD/diff、配置、锁、模型revision、数据manifest；检查已有等价产物。
3. 检查tmux、进程、active run和GPU占用；不能盲目杀未知任务。
4. 跑所涉环境、模型路由、训练保存/重载、CPU检索及工具最小探针。doctor等统一CLI属于需实现入口，尚未实现时不能声称命令已可用。
5. 核对剩余阶段与总预算、实例价、教师与搜索余额、未知计费预留。

### 7.2 单卡分时

开始SFT/DPO前停止本项目Worker派发，结束或保存当前任务，停vLLM并确认显存释放；训练结束保存、验证并退出训练进程，显存释放后再恢复推理。judge如使用GPU也纳入同一排他控制。

模型max_num_seqs2不是许可同时执行两条研究任务。CPU embedding/reranker固定CPU、线程≤8；不要临时挪GPU破坏单卡与公平成本条件。

长下载、长预处理、训练和批量评测使用tmux等可恢复机制；关闭浏览器/SSH不等于任务结束或实例停止计费。

## 8. 每个运行必须登记的字段

| 类别 | 必填字段 |
| --- | --- |
| 身份 | run/experiment/collection/evaluation ID、S步骤、目的、mandatory或补充属性 |
| 环境 | 实例ID、host、环境、Python/锁、GPU/驱动、代码branch/commit/diff |
| 输入 | 配置/提示/模板/Schema、来源/数据/模型/adapter完整版本与哈希 |
| 执行 | 具体入口、tmux session或进程、seed/温度、起止时间和时区 |
| 观察 | 日志、输出、状态、错误、数量/覆盖、验收与断点 |
| 资源 | 实例计费时段、Token、逻辑/物理工具次数、credits、实际/预留/未知费用 |
| 恢复 | 可用检查点、已提交步骤、外部请求完成未知项、下一步和备份位置 |

状态生命周期可用PLANNED、RUNNING、SUCCEEDED、FAILED、CANCELLED、TIMEOUT、STOPPED；步骤验收另记PASS等，不把进程退出码0直接当项目门槛通过。

### 当前active run登记

本次任务未发起项目远程run；现有远程运行状态UNKNOWN。后续首次登记要填实际实例和时间，不能将本段改成“全局无任务”而不查进程。

## 9. 失败、恢复与费用停止

- 付费请求超时可能已计费，标billing_unknown并保守预留；崩溃恢复区分未派发、已完成、完成未知，不盲目重放。
- 取消后停止新派发，已发出的远端请求可能返回并收费；费用照实记。
- 控制器非法动作修复最多1次，暂时工具错误最多重试1次；401/403不盲重试。
- SFT OOM先查其他进程，再按执行方案缩总长3072→2048、prompt2880→1856并同步线上、数据、基线；仍失败停。NaN按原SFT规则最多一次降lr重跑，不把此例外自动扩展为DPO随意调参。
- 硬预算标准为工具8、live≤3、总输入48000/输出4096、收尾输出预留1536、任务240秒，所有模型节点和修复均计账；b4/b12仅内部评测。
- 总预算1500元，教师/评分300、搜索100、存储100；返工预留400不等于自动可花余额。实际资源和余额是未知时，先核对不填0。
- 预算不足执行原定停止顺序，保留可用系统和未完成清单；不按结果删主测试题、不低于训练最低门槛、不自动充值或升级。

## 10. 同步、备份、实例迁移与关机

### 10.1 同步和复用

先核Git状态再同步，保留未合并diff，不force push或覆盖唯一修改。代码、锁和小型manifest走Git；模型与大结果按路径、哈希和备份清单管理。

迁移实例时先建立新的登记记录，核实际挂载、模型与数据、四环境、代码版本、服务和active run。旧实例条目标DEPRECATED并保留证据索引，不把旧VERIFIED直接复制成新机状态。

### 10.2 关机前检查

1. 明确拟关的实例ID和当前任务；只操作本项目已授权范围，不停止其他未知工作。
2. 停止新派发，等待当前调用完成或记录完成未知，保存检查点与事务状态。
3. 核输出数量、错误、manifest和费用；更新HANDOFF、REMOTE与必要CHANGELOG。
4. 提交/保存源码，导出一致性数据库，备份adapter、索引/来源快照、真实数据与结果到独立端，校验SHA-256并确认能恢复。
5. 备份暂存放 `L/backups/<backup_id>/`，不能把同实例数据盘当永久独立备份。
6. 通过控制台确认实例停止计费状态；只退出tmux、SSH或模型进程不代表关机，存储费仍需核账。

### 10.3 当前关机结论

**2026-10-27 21:05：** S42 已优雅暂停并完成本机备份；无本项目 harness/vLLM；GPU 空闲。**可在 AutoDL 控制台关机停计费**（仅退出 SSH ≠ 关机）。数据盘上的 `eval_main_s42_0001` 会保留，明日开机后按 HANDOFF 续跑。本文件不自动关机。

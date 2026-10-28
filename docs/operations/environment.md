# Environment：四套 Python 环境与冻结模型（S06）

> 更新日期：2026-10-26｜WORK_ROOT（active）：`/root/autodl-tmp/evidence-agent`  
> 实机：`autodl-container-12ce4dade8-72ec6d56`（RTX 4080 SUPER 32GB，驱动 580.142）；数据盘 100.00 GiB。

## 1. 容量与缓存门禁

- 数据盘 `/root/autodl-tmp` 实测 **100.00 GiB**（a002 PASS），允许大下载与四环境安装。
- 所有 envs / models / HF·pip·uv·torch 缓存落在数据盘：`envs/cache/{huggingface,pip,uv,torch,xdg}`（见 `configs/paths.yaml`）。
- 系统盘 `/` 约 30 GiB，禁止存放项目环境与模型。

## 2. 四套环境（Python 3.11）

| 环境 | 路径 | 固定核心 | 锁文件 |
| --- | --- | --- | --- |
| app | `envs/app` | `deepagents==0.7.32` + FastAPI / Streamlit / LangGraph / FAISS / sentence-transformers；**CPU 版 torch** | `repo/locks/app.txt` |
| infer | `envs/infer` | `vllm==0.10.2`（Torch **只遵从** vLLM 解析结果，当前 `torch==2.8.0`） | `repo/locks/infer.txt` |
| train | `envs/train` | `torch==2.8.0`(cu128)、`transformers==4.56.2`、`peft==0.17.1`、`trl==0.23.1`、`bitsandbytes==0.47.0` | `repo/locks/train.txt` |
| judge | `envs/judge` | MiniCheck 官方源码 + `transformers` / `datasets`；**CPU 版 torch** | `repo/locks/judge.txt` |

### 2.1 实际解析结果（首解析，2026-10-26）

| 项 | 值 |
| --- | --- |
| uv | 0.13.5（`pip install uv` 到系统 miniconda；uv 自带的 GitHub 下载在本机极慢，改为本地解释器） |
| Python 解释器 | `/root/autodl-tmp/evidence-agent/envs/py311/bin/python`（conda 创建，3.11.17） |
| app | `torch==2.8.0+cpu`、`transformers==5.20.2`、`sentence-transformers==6.2.0`、`huggingface-hub==2.3.0`、`deepagents==0.7.32` |
| infer | `vllm==0.10.2`、`torch==2.8.0`（vLLM 解析）、`transformers==5.20.2` |
| train | `torch==2.8.0`、`transformers==4.56.2`、`peft==0.17.1`、`trl==0.23.1`、`bitsandbytes==0.47.0`、`huggingface-hub==0.36.2` |
| judge | `torch==2.8.0+cpu`、`transformers==5.20.2`、`minicheck`（本地源码安装，GitHub 直连 `git clone` 多次失败后改 tarball） |
| tmux/apt | `tmux 3.2a` 已装（后台长任务） |

**注意**：train 与 infer/app/judge 的 `transformers` 主版本不同（4.56.2 vs 5.20.2）。这是各环境独立锁的预期结果，训练只走 train 环境；不要把 train 的包混进 infer/app。

### 重建（按锁）

```bash
export WORK_ROOT=/root/autodl-tmp/evidence-agent
export UV_CACHE_DIR=$WORK_ROOT/envs/cache/uv
export PIP_CACHE_DIR=$WORK_ROOT/envs/cache/pip
export HF_HOME=$WORK_ROOT/envs/cache/huggingface
export HF_ENDPOINT=https://hf-mirror.com
export HF_HUB_DISABLE_XET=1
export TORCH_HOME=$WORK_ROOT/envs/cache/torch

bash $WORK_ROOT/repo/scripts/setup_envs.sh          # 需先有 envs/py311
bash $WORK_ROOT/repo/scripts/check_envs.py           # 四环境导入自检
```

解析冲突：保留错误 → 干净环境仅装核心包重试一次 → 仍失败则阻断。`CLEAN_ENVS=1` 可强制重建某个 venv。

### 已知坑（记录以避免重复踩）

1. uv 自动下载 CPython（`astral.sh` / GitHub release）在本机极慢/hang；用 conda 提供的 3.11 解释器绕开。
2. `astral.sh/uv/install.sh` 依赖 GitHub 下载二进制，同样失败；改用 `pip install uv`。
3. `git clone https://github.com/Liyan06/MiniCheck.git` 多次 `RPC failed; curl 16` / 超时；改用 `codeload.github.com` tar.gz。
4. HF Xet CAS（`cas-server.xethub.hf.co`）在镜像端点返回 401；必须设 `HF_HUB_DISABLE_XET=1`，走普通 LFS。
5. `huggingface.co` 直连不可达；统一 `HF_ENDPOINT=https://hf-mirror.com`。

## 3. 冻结模型

| 角色 | HF / 包装 | 存放 | 实际 revision |
| --- | --- | --- | --- |
| base | `Qwen/Qwen3-4B-Instruct-2507` | `models/base/<sha>/` | 见 manifest |
| embedding | `BAAI/bge-m3`（dense only，忽略 onnx/imgs） | `models/embedding/<sha>/` | 见 manifest |
| reranker | `BAAI/bge-reranker-v2-m3` | `models/reranker/<sha>/` | 见 manifest |
| judge | `lytang/MiniCheck-Flan-T5-Large` | `models/judge/<sha>/` | 见 manifest |

每个模型登记完整 revision SHA、文件哈希、tokenizer、许可 → `data/manifests/mf_model_*.json`；大文件索引 → `repo/artifacts/artifact_index.json`。

下载入口：`repo/scripts/download_models.py`（capacity gate PASS + `HF_ENDPOINT`/`HF_HUB_DISABLE_XET`）。

## 4. 分时与探针

- 单卡：训练探针前停 vLLM / Worker；训练结束释放显存后再启推理。
- 探针脚本：`repo/scripts/doctor.py`（CUDA/tokenizer/embed-rerank/app import/external）、`probe_vllm_route.py`、`probe_train_lora.py`、`probe_timeshare.py`；原始输出 `runs/probes/`。
- 统一服务：`repo/scripts/serve.py`（UI 6006 / API 6008 / vLLM 仅 `127.0.0.1:8001`）。

## 5. 权威配置

业务参数：`repo/configs/project.yaml`。路径：`repo/configs/paths.yaml`。密钥：`runs/system/private.env`。

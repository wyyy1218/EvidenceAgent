# 基座模型卡（E0 决策 / Writer / Verifier 共用）

> 状态：RELEASED_AS_E0（2026-10-28）  
> 产品发布系统 **E0** = 本基座路由，无决策 LoRA；Writer/Verifier 亦走本基座（T24）。

## 1. 标识

| 字段 | 值 |
| --- | --- |
| repo_id | `Qwen/Qwen3-4B-Instruct-2507` |
| revision | `cdbee75f17c01a7cc42f958dc650907174af0554` |
| 本地路径 | `models/base/cdbee75f17c01a7cc42f958dc650907174af0554/` |
| manifest | `data/manifests/mf_model_base_0001.json` |
| 规模（磁盘） | ≈ 8.06 GiB（见 `repo/artifacts/artifact_index.json`） |
| 推理 | vLLM 0.10.2，BF16，`max_model_len=8192`，绑定 `127.0.0.1:8001` |

## 2. 在本项目中的角色

| 角色 | 是否加载 LoRA | 说明 |
| --- | --- | --- |
| 决策（E0） | 否 | 五动作 JSON；发布系统 |
| Writer | 否 | 固定写作者；不跟决策 adapter |
| Verifier | 否 | 固定校验；不跟决策 adapter |
| 决策（E1/E2） | 是（研究） | 见 `sft_model_card.md` / `dpo_model_card.md`；**未发布** |

## 3. 配套模型（非决策）

| 角色 | 标识 | revision |
| --- | --- | --- |
| embedding | `BAAI/bge-m3` | `5617a9f61b028005a4858fdac845db406aefb181` |
| reranker | `BAAI/bge-reranker-v2-m3` | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` |
| judge | `lytang/MiniCheck-Flan-T5-Large` | `96eafd01cee2d16cf81aaa2fb226b14f422a37b3` |

## 4. 许可与局限

- 基座与配套模型许可以各自 Hub 卡片与 `data/manifests/mf_model_*.json` 为准；不得用项目 Apache-2.0 覆盖。
- E0 正式主实验见 `artifacts/reports/rpt_s47_0001/`（n=300）：Q≈0.247，G_gold≈0.382。
- 不声称工业级高并发；Worker 并发为 1；vLLM `max_num_seqs=2`。

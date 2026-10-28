# 数据卡 — 中文技术资料冻结包（S26）

> manifest: `mf_chinese_sources_s26_0001`  
> 冻结截止日：`2026-10-25`  
> 更新日期：2026-10-26

## 集合与项目隔离

| Split | 项目 |
| --- | --- |
| train | FastAPI、Pydantic、HTTPX、Streamlit、Qdrant、LangGraph |
| dev | Gradio、Typer |
| test | Starlette、Click |

训练／开发／测试**不共享项目**。版本比较题使用同一项目的两个已发布版本标签，仍不跨集合借项目。

## 捕获方式

- 首选：官方仓库在截止日解析提交后拉取文档。  
- 本轮：GitHub raw 超时，使用 **authored_local_use_excerpt**（带 repo/tag/path/license/provenance 的本地研究摘录）。  
- 不把摘录假定为可整树上架的再分发包；`data/raw/chinese_docs/LICENSE_NOTICES.md` 保留分项许可。

## Replay 库

| Split | library_id |
| --- | --- |
| train | `chinese_replay_train_s26_v1` |
| dev | `chinese_replay_dev_s26_v1` |
| test | `chinese_replay_test_s26_v1` |

Replay **不是**实时搜索排名复现。测试库在出测试题之前冻结。

## 重建

```bash
python repo/scripts/freeze_chinese_sources.py --root <WORK_ROOT>
```

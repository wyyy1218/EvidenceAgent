# 数据卡 — 中文技术核验任务（S27）

> dataset_id: `zh_tech_s27_v1`  
> 来源 manifest: `mf_chinese_sources_s26_0001`  
> 任务 manifest: `mf_chinese_tasks_s27_0001`

## 规模

| Split | 题数 | 四类各 | Replay |
| --- | ---: | ---: | ---: |
| train | 240 | 60 | 120（每类 30） |
| dev | 60 | 15 | 30（8/7/8/7） |
| test | 100 | 25 | 50（13/12/13/12） |

类别：`direct_fact` / `multi_source` / `version_conflict` / `insufficient_evidence`。

## Gold 边界

- 在线 `*.jsonl`：问题、需求、允许快照、web_mode；**无** gold/rubric。  
- 离线 `*.gold.jsonl`：claims、support spans、rubric、removal_manifest。  
- 证据不足题：先可回答再移除唯一支持句，removal 记入 gold。

## 审核

- Dev/Test：全量 span/removal 自动核验；通过后 test `sealed`。  
- Train：每类抽查 10 题。  
- 审核角色：`agent_span_verify`（单人代理；非多人 IAA）。记录见 `runs/audits/chinese_s27_a001/`。

## 重建

```bash
python repo/scripts/freeze_chinese_sources.py --root <WORK_ROOT>
python repo/scripts/build_chinese_tasks.py --root <WORK_ROOT>
```

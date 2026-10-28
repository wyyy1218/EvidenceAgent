# 数据卡 — HotpotQA 派生子集（S25）

> dataset_id: `hotpotqa_distractor_s25_v1`  
> 更新日期：2026-10-26

## 来源与许可

| 项 | 值 |
| --- | --- |
| 上游 | HuggingFace `hotpotqa/hotpot_qa`，config=`distractor` |
| 数据许可 | **CC BY-SA 4.0**（不得用项目 Apache-2.0 覆盖） |
| 抽取 seed | 42（`SHA-256("42:"+id)` 排序） |
| 规模目标 | train 600 / dev 100 / test 200 |
| 官方 split 映射 | test ← validation；dev+train ← train |
| Manifest | `data/manifests/mf_hotpotqa_s25_0001.json` |

结果必须报告为**自建派生子集**成绩，不得冒充官方 fullwiki。

## 隔离

- 在线包（`*.jsonl`）：问题、需求、允许语料指针；**不含** `answer` / `supporting_facts` / gold。  
- 离线金标准（`*.gold.jsonl`）：答案、支持句及转换后锚点；仅离线评测。  
- 每题语料：`corpora/<task_id>/context.md`（仅该题 context）。  
- 跨 split：支持标题冲突与近重复题跳过；context 段落跨 split 重用记入泄漏报告（distractor 设定下常见），并声明标题隔离≠语义完全独立。

## 重建

```bash
# 如直连 Hub 失败，可设 HF_ENDPOINT=https://hf-mirror.com
python repo/scripts/build_hotpotqa_subset.py --root <WORK_ROOT>
# 离线夹具（非官方规模）：
python repo/scripts/build_hotpotqa_subset.py --root <WORK_ROOT> --fixture-only
```

## 局限

预训练污染与实体语义重叠无法仅靠支持标题隔离消除；见 `leakage_report.json` 中的 `limitations`。

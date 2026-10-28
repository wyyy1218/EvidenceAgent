# 演示脚本（3–5 分钟关键路径 + 可复现扩展）

> release：E0｜公开托管：**未提供**｜本人访问：SSH 隧道 `6006`/`6008`  
> 不能用截图替代可调用应用；下列步骤假定 `serve start` 已成功。

## 0. 开场（15s）

一句话：EvidenceAgent 是**可引用、带硬预算**的证据型研究助手；正式发布是编排基线 **E0**（基座路由），SFT/DPO 为保留的负结果。

## 1. 关键演示顺序（约 4 分钟）

| # | 动作 | UI / API | 期望可见 |
| --- | --- | --- | --- |
| 1 | 登录 UI | `http://127.0.0.1:6006` | 口令页 → 工作台 |
| 2 | 建项目 / 上传 | 项目页上传 `examples/docs/demo_traceable.md` | 解析状态成功 |
| 3 | 建索引 | 索引按钮（可用 HashEmbedder 演示） | version_set 锁定 |
| 4 | 提问 | 「用一句话说明什么是可追溯证据。」 | 运行进入队列 |
| 5 | 动作可见 | 运行详情 / SSE | search/read 等五动作分离显示 |
| 6 | 证据台账 | 证据列表 | evidence_id、原文位置、引用 |
| 7 | 无答案/冲突（可选） | 提问超出语料或故意冲突摘录 | insufficient / conflict 状态可解释 |
| 8 | 取消 / 找回 | 取消按钮；刷新后同 run_id | `cancelled` 或可恢复状态 |
| 9 | 结果导出 | 下载 / `GET /v1/runs/{id}/export` | `answer.json` + citations + `report.md` |
| 10 | 实验页（可选） | 评测/报告入口说明 | 指向 `rpt_s47_0001`，不现场改 test |

## 2. 一键 API 烟测（隧道已开）

见 `examples/requests/demo_smoke.sh`。最短路径：

```bash
export EVIDENCE_AGENT_API_TOKEN=...   # 仅 private.env
curl -s http://127.0.0.1:6008/healthz
curl -s -H "Authorization: Bearer $EVIDENCE_AGENT_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"用一句话说明什么是可追溯证据。"}' \
  http://127.0.0.1:6008/v1/ask
```

## 3. 讲解提纲（约 10 分钟，演示后）

1. **为何 Agent：** 多跳检索 + 引用约束 + 预算，而非单次 RAG。  
2. **相对上游：** 证据台账、打包、五动作受控循环、固定 Writer/Verifier。  
3. **训练谁：** 决策 LoRA（E1/E2）；Writer/Verifier 始终 base。  
4. **DPO reference：** 冻结 SFT，不是 base。  
5. **为何不用在线 GRPO：** 本方案固定为离线偏好 DPO 一次实验。  
6. **防泄漏：** 在线包无 gold；test seal；盲底私有。  
7. **是否「少回答」：** 假答率与 G 一并报告；E1/E2 未过发布门是负结果，不是隐藏。

绑定文件：`docs/evaluation/release_selection.md`、`docs/models/*_model_card.md`、`artifacts/reports/rpt_s47_0001/report.md`。

## 4. 录像备选

若当面无法开实例：播放脱敏录像 + 打开本仓库 `examples/` 与 S48 探针记录；仍须说明「公开托管未提供」。

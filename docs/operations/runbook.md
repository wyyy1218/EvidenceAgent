# EvidenceAgent runbook (S21)

## Services

| Service | Port / host | Start |
| --- | --- | --- |
| API | 6008 | `python -m evidence_agent.cli serve start` / `scripts/serve.py` |
| UI | 6006 | same serve entry |
| Worker | process | started by serve；或 `python -m evidence_agent.worker` |
| vLLM | 127.0.0.1:8001 | serve 默认同启；API 固定 base 路由 |

Worker concurrency = 1. Queue max = 10. vLLM：`max_model_len=8192`，`gpu_memory_utilization=0.80`，`max_num_seqs=2`，`max_lora_rank=16`。

## Cancel

1. `POST /v1/runs/{run_id}/cancel` sets `cancel_requested`.
2. Worker checks cancel between steps; does not dispatch new steps.
3. In-flight remote calls may still complete; their usage is recorded.
4. Queued runs finalize immediately as `cancelled`.

## SSE reconnect (U08)

1. Client keeps the **same** `run_id` (do not create a new research).
2. Reconnect `GET /v1/runs/{run_id}/events` with header `Last-Event-ID: <id>`.
3. Windowed SSE ≠ full history; full trajectory is under `runs/trajectories/{run_id}/trajectory.json`.

## Crash recovery (T18)

| Paid call state | Recovery |
| --- | --- |
| `not_started` | May execute |
| `completed` | Do not replay |
| `completion_unknown` | Mark for review; **no blind replay** |

Resume from last committed `actions.step_no`. Lease + heartbeat prevent dual workers.

## Backup

See `backup_restore.md`. Prefer `python scripts/backup_db.py backup`.

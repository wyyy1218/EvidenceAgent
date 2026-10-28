# Backup & restore（S05）

> 更新日期：2026-10-26｜首个小备份：`bak_s05_0001`

## 1. 原则

- 服务器数据盘不是永久独立备份端；电脑或独立盘保留 SHA-256 可核验副本。
- 私有内容（`private.env`）与公开包分开；公开备份不得含密钥。
- 大文件按路径+哈希管理；代码/锁/小型文档走 Git 或小 bundle。

## 2. 开关机检查单

开机 / 开工：

1. 控制台确认正确实例 ID；SSH `evidence-agent-autodl`。
2. `df -h /root/autodl-tmp`；容量 &lt;100GiB 时禁止 S06 大下载。
3. `nvidia-smi`；核对 GPU 型号与空闲显存。
4. 核对 `WORK_ROOT=/root/autodl-tmp/evidence-agent` 与 `paths.yaml`。
5. 检查是否有遗留 tmux/训练/vLLM；勿盲杀未知任务。

关机 / 收工：

1. 停止本项目派发与服务；保存必要状态。
2. 更新 HANDOFF / REMOTE / 账单笔记。
3. 小备份或增量备份；核 SHA-256。
4. **控制台停止实例**（退出 SSH ≠ 停计费）；核存储费。

## 3. bak_s05_0001

| 项 | 值 |
| --- | --- |
| 远端 | `/root/autodl-tmp/evidence-agent/runs/backups/bak_s05_0001/` |
| 本机 | `runs/backups/bak_s05_0001/` |
| 内容 | Rule、configs、docs/plan|operations|decisions、project_spec、billing、probe、S04 steps |
| 校验 | `SHA256SUMS.txt`；本机拉取后比对 + 解压抽查 `repo/Rule/REMOTE.md` |

恢复抽样：解压到临时目录，确认 `REMOTE.md` 存在即视为小备份可恢复（本步已做）。

## 4. 扩容后

数据盘扩到 ≥100GiB 后：新建 `probe_s05_host_a00N`，更新 REMOTE 与 paths 注释，再开 S06。

## 5. S48 服务验收备份

| 项 | 值 |
| --- | --- |
| 远端 | `/root/autodl-tmp/evidence-agent/runs/backups/bak_s48_a001/` |
| 本机 | `runs/backups/bak_s48_a001/` |
| 校验 | `evidence_agent.sqlite` SHA-256 本机/远端一致（2026-10-28） |
| 恢复 | `python scripts/backup_db.py restore-check --backup-db …` PASS |

公开托管未提供；关机前确认新产物已在本机副本中。

## 6. 应用库一致备份（S21）

**禁止**只复制活跃 `evidence_agent.sqlite` 而忽略 `-wal`/`-shm`。

推荐：

```bash
# WORK_ROOT 已设置
python repo/scripts/backup_db.py backup --label bak_s21_manual
python repo/scripts/backup_db.py restore-check --backup-db runs/backups/bak_s21_manual/evidence_agent.sqlite
```

实现：`PRAGMA wal_checkpoint(TRUNCATE)` 后 `VACUUM INTO` 目标文件；清单含 SHA-256。恢复前停写，删除目标旁 WAL/SHM，再拷贝快照。轨迹全文另存 `runs/trajectories/<run_id>/trajectory.json`。

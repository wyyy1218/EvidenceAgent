# 干净复现与服务验收（S48）

> 更新日期：2026-10-28

## 1. 目标

在干净目标环境或**清晰隔离的重建核验**下，用锁文件与统一 CLI 恢复依赖、基座、发布路由（E0）、数据库迁移与索引，并完成服务抽验与备份恢复。

## 2. 缓存策略

当前 AutoDL 数据盘总量约 71GiB、可用约 25GiB，**不执行整盘 wipe 重建**（会毁掉已验证的四环境与基座）。S48 验收记录：

- 复用 `envs/{app,infer,train,judge}` 与 `envs/cache/`
- 核验 `repo/locks/*.txt` 存在且 app 关键 import 可用
- 核验 `models/base/<revision>` 存在
- `cache_reused=true` 写入 `runs/steps/S48/*/acceptance.json`

若未来盘 ≥100GiB 且需严格从零：`CLEAN_ENVS=1 bash scripts/setup_envs.sh` 后再 `download_models.py`。

## 3. 统一入口

见仓库根 `README.md`。验收脚本：`python scripts/run_s48.py --attempt a001`。

## 4. 访问与公开托管

| 类型 | 状态 |
| --- | --- |
| 本人 SSH 隧道 6006/6008 | 可验收 |
| AutoDL 个人映射 | 仅本人，**≠** 公开部署 |
| 公开在线托管 | **未提供**（条件性未完成，不影响本地/本人服务事实） |

## 5. 备份

```bash
python -m evidence_agent.cli backup --label bak_s48_a001
python scripts/backup_db.py restore-check \
  --backup-db runs/backups/bak_s48_a001/evidence_agent.sqlite
```

服务器数据盘不是永久独立备份端；关机前将 `runs/backups/bak_s48_*` 拉回工作站。

# Access：本人访问与公开托管（S04）

> 更新日期：2026-10-28｜证据：用户提供新 SSH；本机别名重绑 + 密钥 `BatchMode` 登录 OK。资源深度核验因远端克隆进行中暂缓。账号企业认证未在控制台点击确认。

## 1. SSH 运维入口（已通）

| 项 | 值 |
| --- | --- |
| Host | `connect.westc.seetacloud.com` |
| Port | `28394`（2026-10-28 起；旧口 `35832`/`36512` 作废） |
| User | `root` |
| 本机别名 | `evidence-agent-autodl` |
| 认证 | ed25519 密钥（路径见 `private.env` 的 `SSH_IDENTITY_FILE`） |
| Keepalive | `ServerAliveInterval 30`；`TCPKeepAlive yes` |
| Host key | ED25519 `SHA256:EPstg8jNN+u3Bs1JyQOqlBeq3w+a4VynoJAe48YnIV0` |
| 连接探测命令 | `ssh -o BatchMode=yes evidence-agent-autodl "echo OK"` |

密码仅作密钥安装引导，正式运维用密钥；密码轮换后更新 `private.env`。

## 2. 产品端口设计

| 服务 | 监听 | 对外 |
| --- | --- | --- |
| Streamlit UI | `0.0.0.0:6006` | 映射或隧道 |
| FastAPI | `0.0.0.0:6008` | 映射或隧道 |
| vLLM | `127.0.0.1:8001` | **禁止**公网直开 |

## 3. 本人访问方案（条件）

官方文档（2026-10-26 查阅 [开放端口](https://www.autodl.com/docs/port/)）：

- 实例无独立公网 IP；平台为 **6006 / 6008** 提供映射地址。
- **开放端口需企业认证**；个人用户文档指向 **SSH 隧道** 将端口转到本机。

本项目登记：

1. **优先：** 若账号已企业认证 → 控制台「自定义服务」复制 6006/6008 映射 URL（仅本人使用）。
2. **备选（个人默认路径）：** SSH 本地转发，例如：
   - `ssh -N -L 6006:127.0.0.1:6006 -L 6008:127.0.0.1:6008 evidence-agent-autodl`
   - 浏览器打开 `http://127.0.0.1:6006` / API `http://127.0.0.1:6008`。
3. **账号能力：** 企业认证是否已开通 = **MUST_VERIFY_ONCE**（需用户在控制台确认一次并回填本文件）。

## 4. 公开托管

- 默认交付：脱敏录像 + 仓库 + 复现包。
- **未**确认获准公开转发/托管前，标注「未提供公开在线入口」。
- 不得把本人映射 URL 当作可分享公网演示链接（见 [自定义服务补充协议](https://www.autodl.com/docs/service_agreement/)）。

## 5. 鉴权（S08 已落地，2026-10-26）

| 项 | 实现 |
| --- | --- |
| API Bearer | `EVIDENCE_AGENT_API_TOKEN`（兼容 `API_BEARER_TOKEN`）于 `runs/system/private.env`；`/readyz`、`/v1/ask` 强制 Bearer；`/healthz` 无鉴权且不泄密钥 |
| UI 口令 | `EVIDENCE_AGENT_UI_PASSWORD`（兼容 `UI_PASSWORD`）；Streamlit 登录页校验，会话内存标记 |
| 模型路径 | 浏览器只调 API；API 调 `127.0.0.1:8001` 固定 **base**；禁止公网开 8001 |
| 启停 | `python -m evidence_agent.cli serve start\|stop\|status`（或 `scripts/serve.py` / `scripts/ea.py`）；状态 `runs/system/service_state.json`；日志 `runs/system/logs/` |
| S48 公开托管 | **未提供**；不得把 AutoDL 个人入口当作公开部署完成 |

变量名模板见 `repo/.env.example`。真实值只在 `private.env`。

S08 探针：`runs/probes/probe_s08_e2e_a001/`（未鉴权 401、短问真实回答、UI 200）。

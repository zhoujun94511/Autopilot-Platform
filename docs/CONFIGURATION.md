# AutoPilot Platform — 配置真源说明

> **优先级**：运维配置中心（`mc_runtime_config.json`）> 环境变量 / `.env` > 代码默认  
> IDE 侧见 [AutoPilot/docs/CONFIGURATION.md](../../AutoPilot/docs/CONFIGURATION.md)

---

## 1. 三层模型

```
运维 UI / GET /ops/config  →  mc_runtime_config.json  (L1，最高)
        ↓ 未覆盖时
.env / 进程环境变量          (L2)
        ↓ 未设置时
代码 default                 (L3)
```

**L1 可编辑键**：Webhook、设计域 AI（`AP_AI_*`）、RAG、告警、制品策略等 — 见 `platform/ops/runtime_config.py` 的 `EDITABLE_KEYS`。

**L2 仅 env（不可 runtime 热改）**：`MC_HOST`、`MC_PORT`、`MC_API_TOKEN`、`MC_JWT_SECRET`、`MC_DATABASE_URL`、SSO 证书等。

---

## 2. 端口与 URL 对照

| 端口 | 用途 | 配置 |
|------|------|------|
| **8000**（默认） | Platform API + 生产静态页 | `MC_PORT` / `MC_HOST`；完整 URL：`MC_PLATFORM_URL` 或 `MC_SERVER` |
| **5173** | Vite 开发 Web | 固定；代理目标读 `MC_PORT` |
| **8765** | IDE `serve-webhook` 接收 | IDE `.env` `AUTOPILOT_INTENT_WEBHOOK_PORT`；Platform 填 `MC_DESIGN_WEBHOOK_URL` |

**单一真源函数**：`autopilot_platform.platform.core.urls.platform_base_url()`

Runner、托管 Runner、MCP 客户端、SSO 默认回调均由此派生。

---

## 3. 常用变量

| 变量 | 层 | 说明 |
|------|-----|------|
| `MC_WEBHOOK_URL` | L1 | 任务终态回调 |
| `MC_DESIGN_WEBHOOK_URL` | L1 | APPROVED → IDE webhook |
| `MC_WEBHOOK_SECRET` | L1（加密落盘） | 签名密钥 |
| `MC_WEBHOOK_ALLOW_LOOPBACK` | L1 | 允许推送到 127.0.0.1（联调） |
| （投递实现） | — | Webhook POST 将 DNS 解析结果钉到已校验公网 IP 再连接（防 rebinding TOCTOU） |
| `AP_AI_*` | L1 | 设计域 AI |
| `MC_HOST` / `MC_PORT` | L2 | uvicorn 绑定 |
| `MC_PLATFORM_URL` | L2 | 显式 Platform 根 URL（覆盖 host+port 推导） |
| `MC_SERVER` | L2 | Runner CLI 默认（同 `platform_base_url()`） |

---

## 4. 改端口步骤

1. `.env`：`MC_PORT=9000`（或 `MC_PLATFORM_URL=http://127.0.0.1:9000`）
2. 重启 Platform；`start_dev.py` 与 Vite 会自动读 `MC_PORT`
3. 企业分发 IDE：在用户机器写入 `platform.url` 或 `AUTOPILOT_PLATFORM_URL`，与对外根地址一致（见下文 §7）
4. 运维中心：检查 `MC_DESIGN_WEBHOOK_URL` 是否仍指向 IDE webhook

---

## 5. 公开 Bootstrap（前端 / IDE）

无需登录：`GET /api/v1/public/bootstrap`

返回 `platform_base_url`、`api_prefix`、`endpoints` 映射、Runner CLI 模板（Token 占位，不含密钥）等。Web 在 `main.ts` 启动时拉取；`api.ts` 经 `apiPath()` 统一前缀。

IDE 校验：`python tools/config_doctor.py`（对比本地 `mc_server_url` 与 Bootstrap）。

---

## 6. HTTPS / TLS

开发联调（`start_dev.py`）使用 **HTTP**，无需证书。

生产对外 URL 为 `https://` 时，须启用以下之一：

| 模式 | 变量 | 说明 |
|------|------|------|
| **反代终结 TLS**（推荐） | `MC_BEHIND_HTTPS_PROXY=1`、`MC_PLATFORM_URL=https://…` | nginx/Caddy 对外 HTTPS，Platform 本机 HTTP |
| **uvicorn 直连 TLS** | `MC_SSL_CERTFILE` + `MC_SSL_KEYFILE` | 证书文件存在即自动启用 HTTPS 监听 |

完整步骤、nginx 示例与校验清单见 **[setup/https.md](setup/https.md)**。  
生产模板见 [`deploy/production.env.example`](../deploy/production.env.example)。

`MC_ENV=production` 且 `MC_PLATFORM_URL` 为 `https://` 时，未配置上述任一种模式将**拒绝启动**。

---

## 7. 向用户分发 IDE（Platform 地址）

企业场景下 Platform **根 URL 只配一次**，服务端与客户端须指向同一对外地址。常见误解：`platform.url.example`（IDE 仓模板）**不会被程序读取**；只改模板或只写 IP 都不会生效。

### 7.1 两端各写什么

| 侧 | 谁配 | 写什么 | 典型位置 |
|----|------|--------|----------|
| **Platform 服务端** | 运维 / 发布 | 对外根 URL + 生产密钥 | 仓库根 `.env` 的 `MC_PLATFORM_URL`；或复制 [`deploy/platform.env.example`](../deploy/platform.env.example) → `C:\ProgramData\AutoPilot\platform.env`（`AUTOPILOT_PLATFORM_URL=…`，Platform 启动也会加载） |
| **IDE 客户端** | 打包 / 装机 | 同上根 URL（单行） | 与 `AutoPilot.exe` 同目录的 `platform.url`；或 `%ProgramData%\AutoPilot\platform.url`；或环境变量 `AUTOPILOT_PLATFORM_URL` |

两端 URL 须一致：IDE 连 `https://autopilot.company.com`，Platform 也必须按该主机名（反代 / 证书）对外服务，不能一边 HTTPS 公网、一边只在内网 `:8000` 裸 HTTP（除非全员走内网 HTTP）。

### 7.2 IDE 侧写入方式（任选其一）

| 方式 | 位置 | 说明 |
|------|------|------|
| 文件（推荐） | 与 `AutoPilot.exe` 同目录的 `platform.url` | Windows 安装包最常用 |
| 文件 | `%ProgramData%\AutoPilot\platform.url` | 全机一份，升级 exe 不丢 |
| 文件 | macOS：`/Library/Application Support/AutoPilot/platform.url`；Linux：`/etc/autopilot/platform.url` | 系统级 |
| 环境变量 | `AUTOPILOT_PLATFORM_URL` | 组策略 / 启动脚本 |
| 自定义路径 | `AUTOPILOT_PLATFORM_URL_FILE` | 指向任意 `platform.url` 文件 |

`platform.url` 格式：`#` 开头为注释；**有效内容须为一行完整 URL**（含 `http://` 或 `https://` 和端口）。示例：

```text
# 生产（HTTPS 反代）
https://autopilot.company.com

# 内网 HTTP（必须带协议与端口）
http://192.168.1.10:8000
```

**无效示例**：`192.168.1.10`、`autopilot.company.com`（缺协议）、`platform.url.example`（模板文件名）。

### 7.3 生效后 IDE 行为

- **锁定** Platform 地址，登录页默认不能改（联调例外：`AUTOPILOT_ALLOW_PLATFORM_URL_OVERRIDE=1`）。
- 用户仍须输入 **用户名 / 密码**，并选择 **项目空间**。地址锁定 ≠ 免登录 ≠ 自动可用。
- **厂商 AI Key** 只在 Platform 运维配置（`AP_AI_*` / 配置中心），**不要**写进 IDE 安装包或用户 `.env`。
- 非 loopback 部署须先完成 [生产安全基线](setup/managementconsole.md#10-生产部署安全基线)（轮换 `MC_API_TOKEN`、`MC_JWT_SECRET`、管理员口令等）。

### 7.4 运维检查清单

1. Platform 已对外可访问：`curl -s https://autopilot.company.com/api/v1/public/bootstrap` 返回 JSON（含 `platform_base_url`）。
2. 服务端 `MC_PLATFORM_URL`（或 `platform.env`）与 IDE `platform.url` **字符串一致**（协议、主机、端口）。
3. 防火墙 / 反代 / TLS 证书允许客户端访问该 URL。
4. 客户端已写入 `platform.url` 或 `AUTOPILOT_PLATFORM_URL`（不是只改 `platform.url.example`）。
5. IDE 侧校验：`python tools/config_doctor.py`（兄弟仓 AutoPilot；对比 deploy URL 与 Bootstrap）。
6. 用户用 Platform 账号登录 IDE，能拉项目列表；链路 3 编写走 Platform 持钥网关。

### 7.5 常见故障

| 现象 | 常见原因 |
|------|----------|
| IDE 仍连 `127.0.0.1:8000` | 未部署 `platform.url` / 环境变量；或文件名为 `platform.url.example` |
| 登录超时 / 无法连接 | URL 缺 `http(s)://` 或端口；或用户网络访问不到 Platform |
| 地址对了但登录失败 | 账号密码错；或 Platform 仍用开发默认 JWT / 未按 §10 轮换密钥 |
| 能登录但 AI 编写不可用 | Platform 运维未配 `AP_AI_*`；与 IDE 地址无关 |

细则与打包步骤：IDE 仓 [`docs/CONFIGURATION.md` §1](../../AutoPilot/docs/CONFIGURATION.md)、[`docs/packaging.md`](../../AutoPilot/docs/packaging.md)；操作指南 [setup/managementconsole.md §5.1](setup/managementconsole.md#51-登录与连接)、[§10 向用户分发 IDE](setup/managementconsole.md#向用户分发-ide)。

---

## 9. 日志与审计（三类分离）

| 类型 | 位置 | 用途 |
|------|------|------|
| **应用日志** | `logs/platform_YYYYMMDD.log`（`MC_PLATFORM_LOGS_DIR`） | Platform 进程：调度、RAG、告警、未捕获异常；stderr 同步输出 |
| **任务日志** | `data/job_logs/{job_id}.log`（`MC_JOB_LOGS_DIR`） | Runner 批跑 stdout/stderr；UI/SSE 查看 |
| **操作审计** | DB 表 `audit_logs` | 登录、设计域写操作、运维配置变更；Web「审计」只读 |

**应用日志变量（L2 env，不进运维 JSON）**

| 变量 | 默认 | 说明 |
|------|------|------|
| `MC_PLATFORM_LOGS_DIR` | 仓库根 `logs/` | 轮转文件目录 |
| `MC_LOG_LEVEL` | `INFO` | stderr 级别；文件 handler 始终 DEBUG |
| `MC_LOG_FORMAT` | `text` | `json` 可对接 Loki/ELK |

**请求关联**：HTTP 响应头 `X-Request-ID`（可传入或自动生成）；500 异常与应用 JSON 日志（`MC_LOG_FORMAT=json`）含同一 ID。

**审计补充**：登录失败写入 `auth.login_failed`（含 client IP）；成功仍为 `auth.login`。

**保留策略（scheduler tick 自动清理，`0`=关闭）**

| 变量 | 默认 | 说明 |
|------|------|------|
| `MC_JOB_LOG_RETENTION_DAYS` | `90` | 终态 Job 的 `data/job_logs/*.log` |
| `MC_AUDIT_LOG_RETENTION_DAYS` | `180` | DB `audit_logs` 行 |
| `MC_JOB_REPORT_RETENTION_DAYS` | `90` | 报告目录（已有） |

开发联调：`start_dev.py` 将各服务 stdout 写入 `logs/dev-*.log`，与 Platform 应用日志并存。

---

## 10. 相关文件

- `autopilot_platform/platform/core/logging_setup.py` — 应用日志装配
- `autopilot_platform/platform/core/request_context.py` — `X-Request-ID`
- `autopilot_platform/platform/ops/runtime_config.py` — L1 键表与 `cfg_*`
- `autopilot_platform/platform/core/urls.py` — 基址推导
- `autopilot_platform/platform/core/tls.py` — HTTPS / 反代 TLS
- `.env.example` — L2 样例与注释
- Web：运维 → 配置中心
- IDE：`docs/CONFIGURATION.md`、`platform.url.example`

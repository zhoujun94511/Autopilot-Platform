# Platform HTTPS / TLS 部署指南

> 开发联调：`start_dev.py`（HTTP :8000）或 `start_dev_https.py`（HTTPS 直连 :8443）。  
> 生产环境对外 URL 为 `https://` 时，须启用 TLS（当前阶段：**Platform 直连**；反代见 §3 后续阶段）。

---

## 1. 部署阶段说明

| 阶段 | 模式 | 状态 |
|------|------|------|
| **当前** | **B — uvicorn 直连 TLS** | Platform 进程直接持证书监听 HTTPS |
| **后续** | A — 反代终结 TLS | nginx / Caddy / 云 LB 前置（§2） |

**当前只需关心模式 B**：配置 `MC_SSL_CERTFILE` + `MC_SSL_KEYFILE`，**不要**设 `MC_BEHIND_HTTPS_PROXY`。

---

## 2. 模式 B：uvicorn 直连 TLS（当前推荐）

```bash
MC_ENV=production
MC_PLATFORM_URL=https://autopilot.company.com:8443
MC_SSL_CERTFILE=/path/to/server.crt
MC_SSL_KEYFILE=/path/to/server.key
MC_COOKIE_SECURE=1
MC_CORS_ORIGINS=https://autopilot.company.com:8443
# 可选：中间 CA 链
# MC_SSL_CA_CERTS=/path/to/ca-chain.pem
```

**证书存在即启用**：`MC_SSL_CERTFILE` 与 `MC_SSL_KEYFILE` 均为可读 PEM 文件时，`python -m autopilot_platform.platform` 自动向 uvicorn 传入 `ssl_certfile` / `ssl_keyfile`。可用 `MC_SSL_ENABLED=0` 临时关闭。

启动（对外监听示例）：

```bash
python -m autopilot_platform.platform --host 0.0.0.0 --port 8443
```

Bootstrap 自检：

```bash
curl -sk https://autopilot.company.com:8443/api/v1/public/bootstrap
# 期望 flags.tls_direct=true, public_scheme_https=true
```

### 2.1 内网自签：keytool 一键生成 PEM

```bash
python tools/gen_tls_cert.py \
  --cn autopilot.local \
  --san DNS:autopilot.local \
  --san IP:127.0.0.1 \
  --write-env
```

流程：`keytool -genkeypair`（JKS / RSA 2048）→ PKCS12 → **自动导出** `server.crt` + `server.key`（PEM）。

| 产物 | 说明 |
|------|------|
| `server.crt` / `server.key` | 填入 `MC_SSL_CERTFILE` / `MC_SSL_KEYFILE` |
| `randomkey_*.jks` | Java keystore 备份 |
| `*_info.txt` | keystore 密码与别名（**勿提交 Git**） |
| `platform-tls.env` | `--write-env` 时生成的 Platform `.env` 片段 |
| `dev-local-ide.env` | `--write-env` 时生成的 **双仓联调** IDE 片段（非企业分发） |

依赖：JDK `keytool` 在 PATH；PEM 转换用项目已有 `cryptography`。

### 2.2 本机 HTTPS 联调（start_dev_https.py）

与 `start_dev.py` 类似，一键起 Platform（HTTPS）+ Vite（HTTP）：

```bash
python start_dev_https.py start --auto-cert
# 或预先 gen_tls_cert + .env 配 MC_SSL_* 后直接：
python start_dev_https.py
```

默认 Platform **8443**；浏览器打开 `https://127.0.0.1:8443`（自签须手动信任）。

### 2.3 双仓本地联调（开发）

> **仅开发者本机**：与 IDE 企业分发无关。证书在 Platform 仓 `data/tls/` 生成；IDE 用户不应引用该路径。

服务端与客户端 URL **须完全一致**（协议、主机、端口）：

| 侧 | 配置位置 | 示例 |
|----|----------|------|
| Platform | 本仓 `.env` | `MC_SSL_CERTFILE` / `MC_SSL_KEYFILE` / `MC_PLATFORM_URL` |
| IDE（开发机） | AutoPilot 仓 `.env` 或 `dev-local-ide.env` | `AUTOPILOT_PLATFORM_URL` + `AUTOPILOT_SSL_CA_FILE=<本机 server.crt>` |

`gen_tls_cert --write-env` 会分别写入 `platform-tls.env` 与 `dev-local-ide.env`（后者复制到 **开发机** AutoPilot `.env`）。

公网 CA：IDE 默认校验即可。应用层仍须 **用户名/密码登录**（TLS 不代替 JWT）。

---

## 3. 模式 A：反向代理（后续阶段）

> **当前阶段可跳过本节。** 待引入 nginx / Caddy / 云 LB 时再启用；届时 Platform 改回本机 HTTP + `MC_BEHIND_HTTPS_PROXY=1`，证书挂在反代上。

### 3.1 Platform 环境变量

```bash
MC_ENV=production
MC_PLATFORM_URL=https://autopilot.company.com
MC_BEHIND_HTTPS_PROXY=1
MC_FORWARDED_ALLOW_IPS=127.0.0.1
MC_COOKIE_SECURE=1
MC_CORS_ORIGINS=https://autopilot.company.com
```

- `MC_BEHIND_HTTPS_PROXY=1`：启用 uvicorn `proxy_headers`，识别 `X-Forwarded-Proto: https`。
- `MC_FORWARDED_ALLOW_IPS`：仅信任来自反代的连接；默认 `127.0.0.1`。

### 3.2 nginx 示例

```nginx
server {
    listen 443 ssl http2;
    server_name autopilot.company.com;

    ssl_certificate     /etc/ssl/certs/autopilot.crt;
    ssl_certificate_key /etc/ssl/private/autopilot.key;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 3.3 自检

```bash
curl -s https://autopilot.company.com/api/v1/public/bootstrap | jq .flags
# 期望：public_scheme_https=true, behind_https_proxy=true
```

---

## 4. IDE 客户端（企业分发）

Platform 文档**不**定义 IDE 安装包内容。企业用户机配置见 [AutoPilot/docs/CONFIGURATION.md](../../../AutoPilot/docs/CONFIGURATION.md#https--tlside-客户端)：

- URL：`platform.url` 或 `AUTOPILOT_PLATFORM_URL`
- 私有 CA：IT 组策略下发 `AUTOPILOT_SSL_CA_FILE`（用户机上的 CA 路径，与 Platform 服务器 `MC_SSL_*` 无关）

双仓开发者自签联调见 §2.3。

---

## 5. 生产校验

`MC_ENV=production` 且 `MC_PLATFORM_URL` 为 `https://` 时，启动会校验：

- **当前（直连）**：`MC_SSL_CERTFILE` + `MC_SSL_KEYFILE` 可读；
- **后续（反代）**：或 `MC_BEHIND_HTTPS_PROXY=1`；
- 证书路径存在但不可读、或只配 cert/只配 key 时报错。

开发环境（非 `MC_ENV=production`）不强制 HTTPS，便于 `start_dev.py` HTTP 联调。

---

## 6. 相关变量速查

| 变量 | 阶段 | 说明 |
|------|------|------|
| `MC_PLATFORM_URL` | 当前 | 对外根 URL（须含 `https://` 与端口） |
| `MC_SSL_CERTFILE` | **当前** | 服务器证书（PEM） |
| `MC_SSL_KEYFILE` | **当前** | 服务器私钥（PEM） |
| `MC_SSL_CA_CERTS` | 当前 | 可选 CA 链 |
| `MC_SSL_ENABLED` | 当前 | 显式开/关直连 TLS |
| `MC_COOKIE_SECURE` | 当前 | Refresh Cookie Secure（HTTPS 建议 `1`） |
| `MC_CORS_ORIGINS` | 当前 | 生产跨域源（HTTPS 源） |
| `MC_BEHIND_HTTPS_PROXY` | **后续** | 反代模式 |
| `MC_FORWARDED_ALLOW_IPS` | **后续** | 受信反代 IP |

实现：`autopilot_platform/platform/core/tls.py`  
启动入口：`python -m autopilot_platform.platform`（**不要用** `start_dev.py` 跑 HTTPS 生产）

# Web 管理台（AutoPilot Platform）

与桌面 PyQt IDE **互补**，不是 Web IDE。

**联调操作步骤**：[setup/managementconsole.md](setup/managementconsole.md)。  
**仓边界说明**：[managementconsole-split.md](managementconsole-split.md)。

### 按主题速查

| 我想…                | 去这里                                                              |
|--------------------|------------------------------------------------------------------|
| 第一次装好并跑起来          | [setup/managementconsole.md](setup/managementconsole.md)         |
| 向用户分发 IDE、写 Platform 地址 | [CONFIGURATION.md §7](CONFIGURATION.md#7-向用户分发-ideplatform-地址) + setup [§5.1 / §10](setup/managementconsole.md#51-登录与连接) |
| 配环境变量 / 生产密钥       | 仓库根 [`.env.example`](../.env.example) + 本页「环境变量」相关小节             |
| 启动 Platform + Web  | 仓库根 `python start_dev.py`                                        |
| 启动执行节点 Runner      | `python -m autopilot_platform.runner`（详见 setup 第 4 节）             |
| 查完整 REST API 定义    | Platform 启动后访问 `http://127.0.0.1:8000/docs`（Swagger UI，以此为准）     |
| 弄清 IDE / Web 角色边界  | 本页「鉴权边界」「设备池隔离」                                                  |
| 排查登录 / 权限问题        | 本页「鉴权边界」「RBAC」                                                   |

> **API 以运行时 `/docs` 为准**：Platform 基于 FastAPI，启动后在 `http://127.0.0.1:8000/docs`（Swagger）与 `/redoc` 提供交互式接口文档；本页中出现的路径仅为讲解，字段/参数请以 `/docs` 实时输出为准。

## 品牌

主品牌统一为 **AutoPilot**（色值 `#1565C0`）。图标单一来源：`autopilot/ui/branding.draw_icon()` → `tools/export_icon.py` → `resources/branding/`（并同步到 Web `frontend/public/brand/`）。禁止 Web 另画一套标识。产品线后缀区分形态，不另起品牌名：

| 形态  | 对外名称                      | 说明              |
|-----|---------------------------|-----------------|
| 桌面  | AutoPilot / AutoPilot IDE | 关键字自动化测试 IDE    |
| Web | AutoPilot 管理台             | 设计域、权限、TR 设备池、批跑、报告、远控 |

| 角色                                          | 职责                                               |
|---------------------------------------------|--------------------------------------------------|
| **桌面 IDE** (`autopilot/`)                   | 用例编辑调试；**本地设备池**小批量执行；向管理台**投递**制品/任务（共用用户 JWT）  |
| **Platform** (`autopilot_platform/platform`) | 用户登录(JWT)、设计域、TR 设备池、工程制品、应用资源、批跑、报告、远控 |
| **Runner** (`autopilot_platform/runner`)     | 靠近设备的执行节点；HTTP 对接 Platform；调用仓内 `autopilot_platform.ap` |

## 鉴权边界（登录的意义）

**本地 IDE 必须登录后才能使用。** 架构为 **C/S**：IDE / Web 前端都是客户端，只调 Platform HTTP API；禁止 IDE `import autopilot_platform` 服务端鉴权实现。

```
IDE (Client)  --HTTP-->  Platform API  <--HTTP--  Web SPA (Client)
                              |
                         JWT 签发 / 用户库
```

| 角色                                        | 职责                                                |
|-------------------------------------------|---------------------------------------------------|
| **IDE** `autopilot/mgmt/auth_api.py`      | `POST /api/v1/auth/login`、`GET /auth/me`；本机缓存 JWT |
| **Web** `autopilot_platform/frontend`      | 同样调上述 API                                         |
| **Platform** `autopilot_platform/platform` | 唯一鉴权实现（password hash、JWT 签发）                      |

| 场景                    | 是否需要登录          | 说明                   |
|-----------------------|-----------------|----------------------|
| 启动 IDE / 进入主界面        | **是**           | 未登录只能看到登录框；取消 = 退出应用 |
| 编辑用例、本机设备、本机运行        | **是**（已处于登录会话中） | 无独立「免登录本地模式」         |
| 上传制品 / 远程批跑 / 打开管理台网页 | **是**           | 使用当前 IDE 会话 JWT      |
| 退出登录                  | —               | 清会话后须重新登录，否则退出应用     |
| Web 管理台               | **是**           | 未登录只能停在登录页           |

- **禁止**：未登录进入 IDE 主界面；IDE 直接 import Platform `security`/`users`；用 API Token 冒充个人账号做 IDE 日常使用。
- 单测 / 离屏：`AUTOPILOT_SKIP_LOGIN=1` 或 `QT_QPA_PLATFORM=offscreen` 可跳过 GUI 门禁（仅测试）。

## 设备池隔离

- **本地池**：IDE 本机枚举，默认不注册 TR，与云端/TR 池互不影响。
- **TR 池**：仅 Runner 注册并心跳上报的设备会出现在 `GET /api/v1/devices`。
- 未注册 TR 时两池独立；不做自动合流。

## 目录

```
<仓库根>/
  start_dev.py  # 一键联调入口（在仓库根运行：python start_dev.py）
  autopilot_platform/
    core/       # 契约 DTO / 常量（无 Qt）
    platform/   # FastAPI + SQLAlchemy（默认 SQLite）；托管 `frontend/dist`
      api/      # 领域 HTTP 路由（auth / ops / artifacts / jobs…）
      services/ # 领域服务（runners / devices / jobs / reports）
      routes.py # 组装 shim：导出 auth_router / router
    frontend/   # Vite + Vue 3 管理台 SPA（源码；构建产物 `dist/`）
    runner/     # 独立 Runner（python -m autopilot_platform.runner）
```

## 安装

```bash
pip install -e ".[platform]"
```

前端：

```bash
python start_dev.py   # 一键联调
# 或 cd autopilot_platform/frontend && npm install && npm run build
```

## 使用操作（按步骤）

**完整上手说明（Platform → Runner → IDE / Web）请看：**

👉 **[docs/setup/managementconsole.md](setup/managementconsole.md)**

要点摘要：

1. **先**启动 Platform + Web：`python start_dev.py`
2. **再**启动独立 Runner（自动注册，无单独 register 命令）：
   ```powershell
   $env:MC_RUNNER_TOKEN = "<your-runner-token>"
   python -m autopilot_platform.runner --server http://127.0.0.1:8000 --token-env MC_RUNNER_TOKEN
   ```
   或 IDE 菜单 **管理台 → 启动本机 Runner**（须先登录且 Platform 已起）。
3. IDE / Web 用同一账号登录（默认 `admin` / `admin`，仅 loopback）；远程批跑依赖设备池，因此必须有 Runner。

## 鉴权（双通道）

| 调用方              | 方式                                                        |
|------------------|-----------------------------------------------------------|
| **管理台用户（Vue）**   | `POST /api/v1/auth/login` → Access JWT（内存）+ Refresh **HttpOnly Cookie** `mc_refresh`（AUD-2026-02-C；`credentials: include`）；业务请求仍 `Authorization: Bearer` |
| **IDE / API 客户端** | 登录响应 JSON 仍含 `refresh_token`；可继续 body 调 `/auth/refresh`（与 Cookie 并存） |
| **Runner Agent** | `X-API-Token`（默认 `dev-mc-token`，环境变量 `MC_API_TOKEN`）      |

### 统一错误信封

业务错误由 Platform 统一返回 JSON：`{code, message, error_type, trace_id, details}`。  
用户可见文案集中在 `platform/api_messages.py`；全局 handler（`error_handlers.py`）会把历史英文 `detail` 映射为中文。前端 / IDE 客户端只展示 `message`，不要自行拼装状态码文案。

首次启动若无用户，会创建默认管理员：`admin` / `admin`（`MC_ADMIN_USER` / `MC_ADMIN_PASSWORD` 可改）。  
**生产部署必须**覆盖默认口令与密钥，见下文「生产部署（安全基线）」及 [setup/managementconsole.md §10](setup/managementconsole.md#10-生产部署安全基线)。可另配 **OIDC / SAML**（见十一、十四期）。

### 生产部署（安全基线）

| 环境变量                 | 用途                          | 说明                                                                                       |
|----------------------|-----------------------------|------------------------------------------------------------------------------------------|
| `MC_API_TOKEN`       | Runner / 执行通道 `X-API-Token` | **禁止**沿用默认 `dev-mc-token`；生产与 ADMIN 拆分后仅为执行通道（role=runner）                          |
| `MC_ADMIN_API_TOKEN` | 运维专用 Token（**生产 / 非 loopback 必配**） | 设置后：仅本令牌具备 admin；`MC_API_TOKEN` 仅作 Runner。未设置时默认 **不为** admin；仅 `MC_ALLOW_LEGACY_TOKEN_ADMIN=1` 时兼容升权 |
| `MC_ALLOW_LEGACY_TOKEN_ADMIN` | `1` 开启旧「单 Token=admin」 | **默认关**；仅本地迁移/旧脚本临时使用 |
| `MC_ENV`             | `production` / `prod`          | 生产模式：未配 ADMIN token / 仍用默认口令时启动失败；非 loopback 绑定同样强制强凭据 |
| `MC_REQUIRE_ADMIN_API_TOKEN` | `1` 时同生产强制拆分提示     | 非 production 环境也可打开                                                                 |
| `MC_JWT_SECRET`      | 用户 JWT 签名密钥                 | **禁止**沿用内置开发默认值；建议 ≥32 字节随机串                                                             |
| `MC_ADMIN_PASSWORD`  | 引导管理员密码                     | **禁止**沿用 `admin`；可用 `MC_ADMIN_USER` 改用户名                                                 |

**Prometheus `/metrics`：**

- 本机（`127.0.0.1` / `::1`）可匿名抓取，便于同机 scrape；判定依据为连接对端地址，**忽略** `X-Forwarded-For`（防伪造旁路）。
- **远程** scrape 须带 `Authorization: Bearer <jwt>` 或 `X-API-Token`（运维 Token / API Token），或把 Prometheus 放到与 Platform 同机。
- `MC_METRICS_ENABLED=0` 可关闭指标端点。

**SSO 前端回跳：**

- OIDC / SAML 成功后的前端 redirect **默认把 `access_token` 放在 URL fragment（`#…`）**，避免进入反向代理 access log / Referer。
- 配置 `MC_OIDC_FRONTEND_REDIRECT` / `MC_SAML_FRONTEND_REDIRECT` 时，基址不要依赖 query 传 token；前端会同时兼容 hash 与历史 query。
- IDE「打开管理台」同样优先走 hash SSO。

管理员可：`POST /api/v1/auth/users` 创建用户（role: `admin` \| `operator`）。

## 启动（速查）

顺序固定：**Platform 先起 → Runner 再起**。逐步说明与全参数见 [setup/managementconsole.md](setup/managementconsole.md)。

```bash
# 终端 1：Platform :8000 + Vite :5173
python start_dev.py

# 终端 2：独立 Runner（启动即自动 register）
$env:MC_RUNNER_TOKEN = "<your-runner-token>"
python -m autopilot_platform.runner --server http://127.0.0.1:8000 --token-env MC_RUNNER_TOKEN
# 可选：--runner-id my-runner-01 --poll-interval 3.0
```

Web 登录 `http://127.0.0.1:5173`（默认 `admin` / `admin`）后操作。

## 主要 API

| 方法               | 路径                                 | 鉴权          | 说明                                                  |
|------------------|------------------------------------|-------------|-----------------------------------------------------|
| POST             | `/api/v1/auth/login`               | 无           | 登录拿 JWT                                             |
| GET              | `/api/v1/auth/me`                  | JWT         | 当前用户                                                |
| POST/GET         | `/api/v1/auth/users`               | JWT+admin   | 用户管理                                                |
| POST/GET         | `/api/v1/artifacts`                | JWT 或 Token | 上传/列表工程 zip                                         |
| GET              | `/api/v1/artifacts/{id}/download`  | JWT 或 Token | Runner 下载                                           |
| POST/GET         | `/api/v1/app-builds`               | JWT 或 Token | 上传/列表 apk·ipa 应用资源（sha256 同项目去重）                    |
| GET/PATCH/DELETE | `/api/v1/app-builds/{id}`          | JWT 或 Token | 详情 / 重命名 / 删除                                       |
| GET              | `/api/v1/app-builds/{id}/download` | JWT 或 Token | Runner 下载安装包                                        |
| POST             | `/api/v1/app-builds/purge`         | JWT+admin   | 按天清理应用资源                                            |
| *                | `/api/v1/runners/*`                | JWT 或 Token | 注册/心跳/列表                                            |
| GET              | `/api/v1/devices`                  | JWT 或 Token | 在线 TR 设备池                                           |
| POST/GET         | `/api/v1/jobs*`                    | JWT 或 Token | 任务；含 cancel / retry                                 |
| GET              | `/api/v1/reports`                  | JWT 或 Token | 报告索引；可筛 `app_build_id` / `artifact_id` / `platform` |
| GET              | `/api/v1/reports/compare`          | JWT 或 Token | 两任务报告对比（含版本维度）                                      |
| DELETE           | `/api/v1/artifacts/{id}`           | JWT 或 Token | 删除制品                                                |
| POST             | `/api/v1/artifacts/purge`          | JWT+admin   | 按天清理制品                                              |

## 制品、应用资源与任务

三域拆分（不要混用存储）：

1. **工程制品**（`/artifacts`）— 用例/配置 zip → `data/artifacts/{id}/`（`MC_ARTIFACTS_DIR`）
2. **应用资源**（`/app-builds`）— 独立 apk/ipa 版本库 → `data/app_builds/{id}/`（`MC_APP_BUILDS_DIR`）
   - 上传校验：后缀、单包大小（`MC_APP_BUILD_MAX_MB`）、ZIP 魔数
   - 同项目 `sha256` 去重（复用既有记录，`reused=true`）
   - 项目配额：`MC_APP_BUILD_MAX_COUNT` / `MC_APP_BUILD_MAX_TOTAL_MB`
   - 超期清理：`MC_APP_BUILD_RETENTION_DAYS` + `POST /app-builds/purge`
   - ACL：`resource_type=app_build`（与制品同级分享）
3. **批跑 Job** — 同时引用 `artifact_id`（或 `project_dir`）与可选 `app_build_id` + 设备

- 建任务可只填 `artifact_id`；同机 Runner 可用解压路径，远程 Runner 会下载 zip 再执行。
- **正式远程装包**：任务带 `app_build_id` 时，Runner 下载应用资源并注入 `__app_build_path__`，安装关键字优先使用该路径，**不再依赖工程 zip 内的 apk/ipa**。
- **旧用例兼容**：未指定 `app_build_id` 时，仍可用工程内相对路径（`appFile`）或本机绝对路径重定位（见引擎路径解析）。
- 安装发生在 **Runner 所连接的设备** 上（`adb install` / iOS 装包），不是由 Platform HTTP 代装。
- 仍支持仅 `project_dir`（Runner 本机可见路径）。
- Web：「工程制品」「应用资源」分栏管理；**批跑**页按「选制品 → 选应用 → 选设备 → 提交」编排。
- IDE：「管理台 → 上传应用资源」；「提交远程批跑」对话框拉取应用资源与 TR 设备列表对齐选择。
## 数据

- SQLite：`data/autopilot_platform.db`；PostgreSQL：`MC_DATABASE_URL=postgresql+psycopg://...`（需 `.[pg]`）
- 增量列：`migrate_schema`（SQLite / PostgreSQL 通用，见上文「数据与迁移」）

## 前后端分离

- 后端纯 REST；CORS 默认本机 `8000`/`5173`。
- 前端 Vite + Vue 3；开发走 `start_dev.py`。
- 前端目录：`frontend/src/App.vue`（壳）+ Pinia stores + `composables/platformRuntime.ts`（运行时接线）+ `components/*Panel.vue`（各业务面板）。

## 已知缺口与运维说明

主干批跑闭环可用。下列项按现状区分：

| 类别             | 说明                                                                                                                                                                                                                                       |
|----------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **运维可写配置**     | Admin：`GET/PUT /api/v1/ops/config` → `data/mc_runtime_config.json`；覆盖 webhook/告警/stale/`MC_REQUIRE_JOB_DEVICES` 等，**立即生效**；`MC_WEBHOOK_SECRET` / `MC_ALERT_SECRET` / `AP_AI_API_KEY` **落盘加密**（`enc:v1:` Fernet；主密钥 `MC_CONFIG_SECRET` 或**非默认** `MC_JWT_SECRET`；禁止用开发默认 JWT 加密；旧默认密文可读并可在配置强密钥后重加密） |
| **仅环境变量**      | `MC_API_TOKEN`、`MC_JWT_SECRET`、DB、S3、OIDC/SAML 证书等安全/基础设施项仍只读 env                                                                                                                                                                        |
| **PostgreSQL** | `MC_DATABASE_URL=postgresql+psycopg://…`；`pip install -e ".[pg]"`；增量列迁移已通用（SQLite/PG）                                                                                                                                                    |
| **S3**         | `MC_STORAGE=s3` + bucket + `pip install -e ".[s3]"`                                                                                                                                                                                      |
| **IDE**        | 仅投递入口：连接（**用户账号 JWT**）、上传、提交批跑、打开 Web；**任务观察/计划/ACL/运维仅 Web**（刻意不做 IDE 远程日志）                                                                                                                                                             |
| **开发代理**       | Vite 已代理 `/api`、`/health`、`/metrics`                                                                                                                                                                                                     |
| **设备看板**       | `GET /api/v1/devices/board`；明细含占用任务名/状态；Admin `POST /devices/{udid}/release` 强制释放                                                                                                                                                        |
| **任务日志**       | Runner 回传 `JobResultIn.log` 或 `POST /jobs/{id}/logs`；`GET /jobs/{id}/logs` 查看；目录 `data/job_logs/`（`MC_JOB_LOGS_DIR`）                                                                                                                     |
| **任务日志 SSE**   | 先以用户 JWT（Header）调用 `POST /jobs/{id}/logs/stream-token`，再将返回的短时票（默认 **2 分钟**，`MC_STREAM_TOKEN_MINUTES`）用于 `GET /jobs/{id}/logs/stream?access_token=&since=`（EventSource）；票 `typ=job_log_stream` 仅限该任务，**普通 API 禁止 `?access_token=` 传用户 JWT**；服务端 access log 脱敏 query 令牌；SSE `Referrer-Policy: no-referrer`；增量 `data:{offset,text}`，终态后 `event: end`。**AUD-2026-08 RISK ACCEPTED**：EventSource 无法带 Authorization，query 短时票为有意设计；反向代理 access log 亦应脱敏 `access_token` |
| **报告对比**       | `GET /api/v1/reports/compare?left=&right=`；含应用/制品版本是否相同；Web 可按版本筛报告后对比                                                                                                                                                                   |
| **前端结构**       | `App.vue` 壳 + 侧栏分 Tab；Pinia + `platformRuntime.ts` 接线；`components/*Panel.vue` 分面板                                                                                                                                                         |

### 仍待完善（真实缺口）

当前文档所列能力缺口已收口。后续若有新缺口再记于此。

### 预留工作项（不做当前交付）

| 项 | 说明 |
|----|------|
| **Runner 安装面削瘦 / 可选独立包** | 源码与 Platform 同仓、`.[runner]` extra 已能在 B/C 只跑 Agent。后续可把平台 pip 依赖挪出 Runner 安装面，或再发独立 `autopilot-runner` wheel；**现在不改代码、不拆第三仓**。见 [managementconsole-split.md](managementconsole-split.md#预留runner-安装面削瘦与独立包不做当前交付) 与 [setup/managementconsole.md §4.3](setup/managementconsole.md#43-多台设备机接入机房--工位)。 |

**非目标（刻意不做）**：IDE 内远程任务日志 / SSE、IDE 内计划与 ACL 运维——远程观察与治理只在 Web；IDE 与 Web **共用同一套用户账号（JWT）**。

## 数据与迁移

- 默认 SQLite：`data/autopilot_platform.db`
- PostgreSQL：安装 `[pg]` extra 后设 `MC_DATABASE_URL`（推荐 `postgresql+psycopg://user:pass@host:5432/autopilot_mc`）
- 启动时 `create_all` + `migrate_schema`：对已有表**补缺列**（幂等）；不自动删列/改类型
- 可选真实 PG 烟测：`MC_TEST_DATABASE_URL=… pytest tests/test_autopilot_platform_pg.py`

## 十八期：SAML IdP 证书签名校验

仍不依赖 xmlsec；使用 `signxml` + `cryptography` 校验 XML-DSig。

| 变量                         | 说明                                     |
|----------------------------|----------------------------------------|
| `MC_SAML_IDP_CERT`         | IdP 公钥证书 PEM（可用 `\\n`）；或指向 `.pem` 文件路径 |
| `MC_SAML_IDP_CERT_FILE`    | 证书文件路径（优先于非 PEM 的 CERT 值）              |
| `MC_SAML_CLOCK_SKEW_SEC`   | Conditions 时钟偏差，默认 120                 |
| `MC_SAML_ALLOW_UNSIGNED=1` | **仅联调**跳过签名；生产务必关                      |

- 生产路径：未允许 unsigned 时**必须**配置证书并校验签名；顺带校验 Audience / NotBefore / NotOnOrAfter
- SP metadata 在已配证书且非 unsigned 时 `WantAssertionsSigned=true`
- `GET /auth/saml/status` 增加 `signature_verify` / `idp_cert_configured`

## 十七期：钉钉 / 飞书 / Slack 告警渠道

在十六期 `MC_ALERT_WEBHOOK_URL` 之上按渠道格式化载荷：

| 变量                 | 说明                                             |
|--------------------|------------------------------------------------|
| `MC_ALERT_CHANNEL` | `json`（默认）\| `dingtalk` \| `feishu` \| `slack` |
| `MC_ALERT_SECRET`  | 钉钉/飞书机器人「加签」密钥；空则不加签                           |

- 钉钉：markdown；加签参数挂到 URL
- 飞书：`msg_type=text`；加签字段写入 body
- Slack：`{"text":...}`
- `POST /api/v1/ops/alert-test`（admin）：同步发一条测试；Web「运维概览」可点

## 十六期：Prometheus 指标 + 运维告警

### 指标

- `GET /metrics`：Prometheus 文本（无额外依赖）；`MC_METRICS_ENABLED=0` 关闭
- **访问控制**：本机可匿名；远程须 JWT 或 `X-API-Token`（见上文「生产部署」）
- 进程计数：`mc_job_terminal_total{status}`、`mc_stale_reclaimed_total`、`mc_alert_sent_total`
- 实时 gauge：`mc_jobs{status}`、`mc_runners{state}`、`mc_devices{state}`
- `GET /api/v1/ops/summary`（admin）：JSON 运维摘要；Web 有「运维概览」面板

### 告警

- `MC_ALERT_WEBHOOK_URL`：与任务 webhook 分离；失败任务 / 僵死回收时 POST JSON
- `MC_ALERT_ON_FAILED` / `MC_ALERT_ON_STALE`（默认开）；签名复用 `MC_WEBHOOK_SECRET`
- `MC_ALERT_ON_RUNNER_OFFLINE`（默认开）：scheduler 检测 Runner **在线→离线**边沿后推送；`MC_ALERT_RUNNER_OFFLINE_COOLDOWN_SEC`（默认 3600）防抖
- `MC_ALERT_ON_DEVICE_EMPTY`（默认开）：仍有在线 Runner 但在线设备数 **>0→0** 时推送（与 Runner 全离线错开，避免双响）
- Dashboard / 报告页：`GET /api/v1/ops/job-quality` +「批跑失败趋势」卡（日失败率 / 全步 fail_reason / Job.error 前缀）
- ACL：`acl.grant` / `acl.revoke` 均写审计；审计筛选 `action` 以 `.` 结尾时按前缀匹配

## 十五期：Runner 独立令牌 + 僵死任务回收

### Runner Token

- `POST /api/v1/runners/{runner_id}/token`（admin / 全局 Token）：生成独立 `X-API-Token`（明文仅返回一次，库内存 sha256）
- 独立 Token 只能操作本 `runner_id` 的 register/heartbeat/claim/running/complete
- 全局 `MC_API_TOKEN`：默认仅为 Runner 执行通道；运维请配 `MC_ADMIN_API_TOKEN`。旧「单 Token=admin」仅当 `MC_ALLOW_LEGACY_TOKEN_ADMIN=1`（**生产勿开**；见「生产部署」）
- 非 loopback 绑定（`MC_HOST=0.0.0.0` / `start_dev --lan`）：与生产同等，拒绝默认凭据与未拆分 ADMIN Token
- 列表字段 `has_token` 表示是否已发独立令牌

### 本机托管 Runner（Web 启停）

浏览器不能在用户 PC 上直接起进程。Platform **同机**时可由服务端托管子进程：

| 项 | 说明 |
|----|------|
| 权限 | `require_ops_admin`（当前=平台 admin）；普通 member / Runner Token → 403 |
| 开关 | 须显式 `MC_ALLOW_MANAGED_RUNNER=1`（默认关）；且仅 loopback 绑定有效；`0.0.0.0` / `--lan` 禁止 |
| API | `GET/POST /api/v1/runners/managed` · `…/start` · `…/stop` · `…/logs` |
| Token | 启动时自动签发独立 scope token（`managed-local`）；审计 `runner.managed_start` / `runner.managed_stop` |
| 远程 | Web 仅注销登记；启动靠该机 CLI/服务 |

### 僵死回收

- `claimed`/`running` 且 `updated_at` 超过 `MC_JOB_STALE_SEC`（默认 3600，`0`=关）→ 标 `failed` 并释放设备
- 后台 tick 自动扫描；也可 `POST /api/v1/jobs/reclaim?older_than_sec=`（admin）
- Web：Runner 表「签发 Token」；admin「回收僵死任务」

## 十四期：SAML 企业登录

轻量 SP（**不依赖 xmlsec**）：

| 变量                           | 说明                              |
|------------------------------|---------------------------------|
| `MC_SAML_ENABLED=1`          | 打开 SAML                         |
| `MC_SAML_IDP_SSO_URL`        | IdP SSO 入口                      |
| `MC_SAML_IDP_ENTITY_ID`      | 可选；校验 Assertion Issuer          |
| `MC_SAML_SP_ENTITY_ID`       | SP entityID（默认 metadata URL）    |
| `MC_SAML_ACS_URL`            | ACS，默认 `…/api/v1/auth/saml/acs` |
| `MC_SAML_FRONTEND_REDIRECT`  | 成功回跳前端（同 OIDC）                  |
| `MC_SAML_AUTO_PROVISION`     | 默认开                             |
| `MC_SAML_ALLOW_UNSIGNED=1`   | **仅联调**：允许未签名 Response          |
| `MC_SAML_IDP_CERT` / `_FILE` | IdP 签名证书（见十八期）                  |

API：`/auth/saml/status` · `/metadata` · `/login` · `POST /acs`  
用户绑定字段：`users.saml_nameid`。生产请关闭 `ALLOW_UNSIGNED`，并配置 IdP 证书做签名校验。

## 十三期：操作审计

- `GET /api/v1/audit`（admin）：最近操作；可按 `action` / `actor` 过滤
- 埋点：登录 / OIDC、建用户、制品上传删除清理、项目/ACL、计划、任务创建取消重试
- 表 `audit_logs`；写入失败不影响主业务

## 十二期：报告回传与在线查看

- Runner 完成任务后自动 `POST /api/v1/jobs/{id}/report` 上传 HTML
- `GET /api/v1/jobs/{id}/report`：鉴权后返回 HTML（管理台「查看」）
- 报告列表含 `job_id` / `stored`，以及结档冻结的 `artifact_*` / `app_build_*`（任务完成时写入，后续重命名不影响历史）。
- 列表筛选项：`project_id` / `artifact_id` / `app_build_id` / `platform`。
- 目录默认 `data/reports/`（`MC_REPORTS_DIR`）。
- 仍保留 Runner 本机 `report_path` 索引字段

## 十一期：OIDC 企业登录

环境变量（均需时启用）：

| 变量                                            | 说明                                                      |
|-----------------------------------------------|---------------------------------------------------------|
| `MC_OIDC_ENABLED=1`                           | 打开 OIDC                                                 |
| `MC_OIDC_ISSUER`                              | IdP issuer（无尾斜杠），自动拉 `.well-known/openid-configuration` |
| `MC_OIDC_CLIENT_ID` / `MC_OIDC_CLIENT_SECRET` | 应用凭据                                                    |
| `MC_OIDC_REDIRECT_URI`                        | 默认 `http://127.0.0.1:8000/api/v1/auth/oidc/callback`    |
| `MC_OIDC_FRONTEND_REDIRECT`                   | 成功后回前端（默认 `http://127.0.0.1:5173/`）并带 `access_token`    |
| `MC_OIDC_SCOPES`                              | 默认 `openid profile email`                               |
| `MC_OIDC_AUTO_PROVISION`                      | 默认开：首登自动建 `operator`                                    |
| `MC_OIDC_DEFAULT_ROLE`                        | `operator`（默认）或 `admin`                                 |

API：

- `GET /api/v1/auth/oidc/status` — 是否启用（登录页显示 SSO 按钮）
- `GET /api/v1/auth/oidc/start` — 302 到 IdP
- `GET /api/v1/auth/oidc/callback` — 换票、校验 `id_token`（JWKS）、绑定 `users.oidc_sub`、发平台 JWT 并回跳前端

本地账号密码登录仍可用。

## 十期：细粒度资源 ACL

- **有 `project_id`**：按项目成员制。角色为 `owner` / `member` / `viewer`；**viewer 只读**（写操作走 `assert_can_write_project`）。跨项目只读/读写另可用「共享」ACL（`permission=read|write`），且必须同组织。
- **无 `project_id`**：拒绝创建。不是「创建者可见」通道。
- 显式分享：
  - `POST /api/v1/acl`：`{resource_type, resource_id, username, permission: read|write}`
  - `GET /api/v1/acl?resource_type=&resource_id=`：返回 `{items,total,page,page_size}`（兼容 `limit/offset`）
  - `DELETE /api/v1/acl/{id}`
- 平台 admin / 运维 Token 可访问全部资源；**执行通道 Runner Token 不得创建 Job**，且不可借项目校验旁路访问任意 `project_id`
- 独立 Runner Token 可绑 `org_id` / `project_ids`（签发时 body 或 `PATCH /runners/{id}/scope`）；越权项目任务在 claim 时跳过
- 设备强制释放（`POST /devices/{udid}/release`）会**立即**清空 busy 并取消占用任务；响应可含 `warning`，提示 Runner 仍可能短暂收尾——与用户 cancel（claimed/running 保留 busy 至 complete）不同

## 九期：平台定时调度

对齐桌面 `Schedule` 语义（`delay_sec` / `interval_sec` / `repeat` / `stop_on_fail`）：

| 方法               | 路径                               | 说明             |
|------------------|----------------------------------|----------------|
| POST/GET         | `/api/v1/schedules`              | 创建/列表          |
| GET/PATCH/DELETE | `/api/v1/schedules/{id}`         | 详情/启停与参数/删除    |
| POST             | `/api/v1/schedules/{id}/run-now` | 立即触发一拍         |
| POST             | `/api/v1/schedules-tick`         | admin 手动扫描（联调） |

- 后台线程按 `MC_SCHEDULE_TICK_SEC`（默认 15）扫描 `next_run_at`；`MC_SCHEDULE_ENABLED=0` 可关
- **AUD-2026-13（RISK ACCEPTED）**：无独立 MQ；见 `docs/architecture/ADR_scheduler_no_mq.md`
- **单库单 leader**：多实例共享同一 DB 时由 `ops_locks.schedule_loop` 租约选举；跟随节点建议关调度。默认 SQLite 为单写模型，多写 HA 请用 PostgreSQL
- 计划触发另有条件 UPDATE 租约，避免同一拍重复建 Job；僵死回收亦为条件领取
- 上一拍未终态时不会重叠触发；`stop_on_fail` 在任务失败/取消后停计
- 创建的任务名形如 `计划名#N`

## 八期：Webhook / 重试 / 制品清理

### Webhook

- 环境变量 `MC_WEBHOOK_URL`：任务终态异步 POST JSON  
  `event`: `job.succeeded` | `job.failed` | `job.cancelled`；body 含 `job`（及可选 `report`）
- 可选 `MC_WEBHOOK_SECRET` → 请求头 `X-MC-Signature: sha256=...`
- 创建任务时可传 `webhook_url` 覆盖全局 URL

### 任务重试

- `POST /api/v1/jobs/{id}/retry`：仅终态（succeeded/failed/cancelled）可重试  
  克隆为新 `pending`，`parent_job_id` 指向原任务

### 制品清理

- `DELETE /api/v1/artifacts/{id}`：删除元数据与存储文件
- `POST /api/v1/artifacts/purge?older_than_days=N`（admin）：清理过期制品  
  缺省天数：`MC_ARTIFACT_RETENTION_DAYS`（默认 30）

## 项目空间（软多租户）

- `POST/GET /api/v1/projects`：创建/列出空间（必须带 `org_id`；operator 仅见自己加入的本组织项目）
- `POST/GET /api/v1/projects/{id}/members`：owner/admin 添加成员（须先是该组织成员）
- 制品/任务/计划必须带 `project_id`；operator 必须是成员才可读写

## 制品存储

- 默认本地：`MC_STORAGE=local`（`data/artifacts`）
- 可选 S3：`MC_STORAGE=s3` + `MC_S3_BUCKET` +（可选）`MC_S3_PREFIX`  
  `pip install -e ".[platform,s3]"`

## IDE 连接管理台

桌面操作清单与远程批跑流程：**[setup/managementconsole.md §5–§6](setup/managementconsole.md)**。

桌面菜单 **管理台(&M)**：

| 动作              | 说明                                                  |
|-----------------|-----------------------------------------------------|
| （启动门禁）          | 进入主界面前必须登录                                          |
| 连接设置…           | 服务器 / 账号 / 默认项目空间 / API Token（Runner 用）             |
| 退出登录            | 清会话后须再登录，取消则退出应用                                    |
| **启动本机 Runner** | 子进程拉起 IDE Runner：本机 USB 设备心跳进 **设备池**（与 IDE 本地池隔离） |
| **停止本机 Runner** | 停止 IDE 拉起的本机 Agent                                  |
| 上传工程制品          | 打包上传；内部自动确保项目空间                                     |
| 上传应用资源          | 选择 apk/ipa 上传到独立应用资源库                               |
| 提交远程批跑…         | 选应用资源 + 选 TR 设备后创建 Job；进度与报告回 Web                   |
| 打开管理台           | 浏览器打开（带 JWT SSO）                                    |

状态栏显示当前用户，以及 Runner 未启动 / `Runner <id>`。关 IDE 时自动停止本机 Runner。

菜单不再提供「登录」：启动门禁已强制登录；换号/改密走连接设置。

**设备进 TR 池**：须本机 Runner 在跑（IDE「启动本机 Runner」或 `python -m autopilot_platform.runner …`）。仅 IDE「已连接设备」不会出现在 Web「设备」页。

已去掉：`确保项目空间`（上传/批跑时自动做）、`在管理台中运维`（与打开管理台重复）。

配置存 `~/.autopilot/settings.json`。


### 任务取消与设备占用

- `POST /api/v1/jobs/{id}/cancel`：pending/claimed/running → `cancelled`，释放设备占用。
- claim 时按 `device_udids` 占用 TR 设备；同设备其它 pending 不会被领走。
- 心跳重建设备列表时会保留 `busy_job_id`。

### 设备状态、后端能力与调度规则

心跳 `DeviceInfo` 除 udid/platform 外还上报：

| 字段                              | 含义                                                           |
|---------------------------------|--------------------------------------------------------------|
| `os_version` / `name` / `model` | 设备元数据                                                        |
| `state`                         | `ready` / `unauthorized` / `error` / `offline`（busy 以占用字段为准） |
| `backends`                      | 如 `android-appium`、`ios-appium`、`ios-wda`                    |
| `health_note`                   | 不可调度原因说明                                                     |

调度（`claim`）：

1. 指定 `device_udids`：全部须在本 Runner、`state` 可调度（ready）、未占用，且与 Job `backend_mode` 匹配。
2. `backend_mode=auto`：有 backends 时至少具备该平台的一个后端；未上报 backends 的旧 Runner 兼容放行。
3. 明确模式：`uia2`→`android-appium`；`wda`→`ios-wda`；`appium`→按 Job platform 选 `*-appium`。
4. 非 ready 设备仍出现在设备目录，但 Web/IDE 勾选与 claim 均跳过。

联调探测：`python -m autopilot_platform.runner --dry-probe`。

### RBAC（当前，三层）

与 [architecture/MULTI_TENANCY.md](architecture/MULTI_TENANCY.md) 对齐：

| 层 | 角色 | 能力 |
|---|---|---|
| **平台** | `admin` | 用户删除、跨租户、全部 API；运维 Token（`MC_ADMIN_API_TOKEN`）同等 |
| **平台** | `operator` | 业务 API；不能创建/指定 `admin`；无 `X-Org-Id` 时不能管组织用户 |
| **组织** | `owner` / `admin` / `member` | 请求头 `X-Org-Id`；org admin 可管本组织用户（删用户仍仅平台 admin） |
| **项目** | `owner` / `member` / `viewer` | 成员制 + 写操作用 `assert_can_write_project`（viewer 只读） |
| **资源 ACL** | `read` / `write` | 跨项目显式分享（`/api/v1/acl`） |
| **Runner** | 执行 Token | 注册/心跳/领任务/回传；**不得**创建 Job；可绑 `org_id`/`project_ids` 作用域 |

> **ops_admin**：运维配置（`/ops/*`）暂用平台 admin（`is_ops_admin` / `require_ops_admin` 扩展点已留）；后续可拆「可写 ops 但不等于删用户/跨租户」的独立角色，不改登录路径。

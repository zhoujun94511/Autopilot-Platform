# AutoPilot 管理台与 IDE 联调操作指南

本文是**上手操作**文档：按步骤把 Platform、Web 工作台、独立 Runner、桌面 IDE 跑通。  
架构/API/数据模型见 [管理台架构与 API](../managementconsole.md)。

## 0. 5 分钟最短路径（本机联调）

只想尽快看到 Web 跑起来、能远程批跑？照抄下面三步（纯 Platform，无需 IDE 客户端仓）。`start_dev.py` **仅用于本机开发**，不得作为生产入口。默认账户与 Token **仅允许绑定 127.0.0.1**。

```powershell
# ① 安装（仓库根）
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev,runner]"

# ② 启动 Platform + Web（保持此终端不关）
.\.venv\Scripts\python.exe start_dev.py
#    浏览器自动打开 http://127.0.0.1:5173，用 admin / admin 登录
```

另开终端启动本机独立 Runner（否则「设备」页为空、无法远程批跑）。Token 走环境变量，避免进入命令历史：

```powershell
$env:MC_RUNNER_TOKEN = "<your-runner-token>"
python -m autopilot_platform.runner --server http://127.0.0.1:8000 --token-env MC_RUNNER_TOKEN
```

```bash
# Linux / macOS
export MC_RUNNER_TOKEN="<your-runner-token>"
python -m autopilot_platform.runner --server http://127.0.0.1:8000 --token-env MC_RUNNER_TOKEN
```

验证：`http://127.0.0.1:8000/health` 返回健康；Web「集群资源 → 设备」能看到本机 USB 设备（需 adb / iOS 已授权）。

> 以上仅本机联调默认口令。生产部署务必先看 [§10 生产部署（安全基线）](#10-生产部署安全基线)，并参考仓库根 [`.env.example`](../../.env.example) 覆盖全部默认密钥。下面各节是完整版说明。

---

## 1. 角色与先后顺序（必读）

| 组件             | 目录或入口                                                                            | 职责                                  |
|----------------|----------------------------------------------------------------------------------|-------------------------------------|
| **Platform**   | `autopilot_platform/platform`                                                     | HTTP API、用户 JWT、制品、应用资源、批跑、设备池      |
| **Web 工作台**    | `autopilot_platform/frontend`                                                     | 浏览器运维：权限、设备池、批跑、报告（**不是** Web IDE） |
| **独立 Runner** | `python -m autopilot_platform.runner`（本仓） | 靠近设备的命令行执行节点；启动时自动注册并心跳上报设备            |
| **IDE Runner** | `python -m autopilot.runner` 或 IDE「启动本机 Runner」 | 由 AutoPilot IDE 启动的本机执行节点 |
| **桌面 IDE**     | 独立仓 AutoPilot（`autopilot/`）                                                      | 用例编辑、本地调试；可投递制品与任务到 Platform        |

**正确启动顺序：**

```
① Platform（+ Web）先起
② 再起独立 Runner 或 IDE Runner
③ IDE / Web 登录后操作
```

没有 Platform，Runner 无法注册；没有 Runner，Web「设备」页不会出现设备池设备。

---

## 2. 环境准备

在本仓库（AutoPilot Console / 服务端）根目录：

```bash
pip install -e ".[platform]"
```

客户端（IDE + TestRunner）在 AutoPilot 仓：

```bash
pip install -e ".[http,report,mobile]"
```

两边仅 HTTP 对接，互不依赖对方实现包。

默认管理员（首次启动空库时自动创建）：

- 用户名：`admin`
- 密码：`admin`  
  （可用环境变量 `MC_ADMIN_USER` / `MC_ADMIN_PASSWORD` 覆盖）

默认 Runner Token：`dev-mc-token`（环境变量 `MC_API_TOKEN`）。

> **仅适合本机联调。** 对外或生产环境必须按 [§10 生产部署（安全基线）](#10-生产部署安全基线) 覆盖全部默认口令与密钥。

| 地址                       | 用途                                        |
|--------------------------|-------------------------------------------|
| `http://127.0.0.1:8000`  | Platform API（`/health`、`/docs`、`/api/v1`） |
| `http://127.0.0.1:5173`  | 开发态 Web 管理台（Vite，代理到 :8000）               |
| `http://127.0.0.1:8000/` | 生产构建后同源托管前端（`npm run build` 后）            |

### 2.1 TestRunner 节点的设备侧运行时（跑真机批跑必读）

「装好 Platform、能登录 Web」**不等于**能跑真机批跑。真机用例在 **Runner 节点**（靠近设备的机器）上执行，该机除 Runner 依赖外，还需对应平台的**外部运行时**（Appium / JDK / Node、WDA / go-ios 等，**均非 pip 包**）。

在**每台 Runner 机器**上：

```bash
pip install -e ".[runner]"     # ① Runner 依赖（本仓根目录，建议独立 venv）
# ② 再按被测平台装下表的外部运行时
```

| 平台      | 该机还需要                                                                                    | 详细步骤                       |
|---------|------------------------------------------------------------------------------------------|----------------------------|
| Android | JDK 17+、Node 18+、Appium + uiautomator2 驱动；adb（内置自举）                                      | [Android 环境配置](android.md) |
| iOS     | 设备侧已装签名 WDA；go-ios（内置）+ pymobiledevice3；Win/Linux 走 WDA-direct（免 Appium），macOS 可选 Appium | [iOS 环境配置](ios.md)         |
| WebUI   | 浏览器 + Selenium（driver 自动解析）                                                              | [Web 环境配置](web.md)         |

> **Platform / Web 机器不需要**上述工具链，只装 `pip install -e ".[platform]"`。  
> 环境与依赖预检：`python tools/preflight.py --role platform`（含 Node 开发 Web、`.env` 密钥项）或 `--role runner`（JDK/Node/Appium/adb 等）。  
> 快速自检该机设备/后端是否就位（不注册、不领任务）：`python -m autopilot_platform.runner --dry-probe`。  
> 连续批跑想复用本进程 Appium（少冷启动）：Runner 环境设 `AUTOPILOT_RUNNER_KEEP_APPIUM=1`（默认关；跳过 suite 结束 teardown，非进程池）。

---

## 3. 启动 Platform + Web（一步）

在**仓库根目录**执行：

```bash
python start_dev.py
# 等价于：
python start_dev.py start
```

效果：

1. 拉起 Platform（默认 `127.0.0.1:8000`）
2. 拉起 Vite（默认 `127.0.0.1:5173`）；缺 `node_modules` 时自动 `npm install`
3. 默认打开浏览器

常用选项：

```bash
python start_dev.py start --no-browser   # 不自动开浏览器
python start_dev.py start --lan          # 绑定 0.0.0.0，打印局域网 URL
python start_dev.py stop                 # 清理联调占用端口
```

自检：浏览器打开 `http://127.0.0.1:8000/health` 应返回健康状态；Web 登录页 `http://127.0.0.1:5173`，用 `admin` / `admin` 登录。

> 仅后端、不启 Vite 时：`python -m autopilot_platform.platform --port 8000`（见 `autopilot_platform/frontend/README.md`）。

---

## 4. 启动执行节点（注册进设备池）

Runner **没有单独的「register」CLI**。进程启动时会自动调用 `POST /api/v1/runners/register`，再进入心跳 / 领任务循环。

### 4.0 Web 本机托管（Platform 同机）

浏览器**不能**在用户 PC 上直接起进程。若 Platform 与 Runner **同机**（常见本机联调），平台 admin 可在 Web「执行节点」页使用 **启动本机托管 Runner / 停止**：

- 后端 `subprocess` 拉起 `python -m autopilot_platform.runner`，并自动签发独立 Runner Token（不把 admin token 交给子进程）
- API（均需 **ops_admin / 平台 admin**；普通 member → 403）：
  - `GET /api/v1/runners/managed` — 状态 / PID / 日志尾 / CLI 降级命令
  - `POST /api/v1/runners/managed/start` · `POST …/stop`
  - `GET /api/v1/runners/managed/logs`
- 开关 `MC_ALLOW_MANAGED_RUNNER`：默认关，须显式 `=1`；且 Platform 须绑定 loopback。`MC_HOST=0.0.0.0` / `--lan` 即使开启旗标也禁止 Web 启停
- **远程节点**：Web 仅支持注销 / 令牌；启动仍靠该机 CLI 或系统服务

### 4.1 推荐：独立终端用 CLI（联调 / 专用机）

**先确保第 3 节 Platform 已启动**，再开**另一个终端**（仓库根，同一 venv）。

> 入口二选一，**协议相同**：本仓（Console）用 `autopilot_platform.runner`；若同机另装了 **AutoPilot 客户端仓**，也可用 `autopilot.runner`。纯 Console 部署请用前者。下文以 `autopilot_platform.runner` 为准，参数完全一致，替换模块名即可。

Windows PowerShell：

```powershell
$env:MC_RUNNER_TOKEN = "<your-runner-token>"
python -m autopilot_platform.runner `
  --server http://127.0.0.1:8000 `
  --token-env MC_RUNNER_TOKEN `
  --runner-id my-runner-01 `
  --poll-interval 3.0
```

Linux / macOS：

```bash
export MC_RUNNER_TOKEN="<your-runner-token>"
python -m autopilot_platform.runner \
  --server http://127.0.0.1:8000 \
  --token-env MC_RUNNER_TOKEN \
  --runner-id my-runner-01 \
  --poll-interval 3.0
```

最简（本机 loopback；未设置自定义变量时，默认 `--token-env MC_API_TOKEN` 可回落到开发通道）：

```powershell
python -m autopilot_platform.runner --server http://127.0.0.1:8000 --token-env MC_API_TOKEN
```

| 参数 | 环境变量 | 默认 | 说明 |
|------|----------|------|------|
| `--server` | `MC_SERVER` | `http://127.0.0.1:8000` | Platform 根 URL |
| `--token` | （不推荐） | 无 | 显式 Token，会进入命令历史 |
| `--token-env` | 变量名本身 | `MC_API_TOKEN` | 从该环境变量读取 `X-API-Token` |
| `--runner-id` | `MC_RUNNER_ID` | `{主机名}-{网卡node}` | 节点 ID；多机请显式指定避免冲突 |
| `--poll-interval` | （无） | `3.0` | 空闲时轮询领任务的间隔（秒） |
| `--dry-probe` | （无） | off | 只探测设备/后端并打印，不注册、不领任务 |

成功时终端会出现类似：

```text
[runner] register capabilities=[...] host_backends=[...] version=0.1.0
[runner] id=my-runner-01 server=http://127.0.0.1:8000
```

联调探测（不连 Platform）：

```bash
python -m autopilot_platform.runner --dry-probe
```

随后：

- Web「集群资源 → 设备」可见本机 USB 设备（需 adb / iOS 已授权）
- Web 概览可见 Runner 在线

停止：在该终端 `Ctrl+C`。

### 4.2 备选：IDE 菜单「启动本机 Runner」

Platform 已在跑、且 IDE 已登录时：

1. 菜单 **管理台** → **连接设置…**  
   - 服务器 URL：`http://127.0.0.1:8000`  
   - 用户名 / 密码：与 Web 相同（如 `admin` / `admin`）  
   - API Token：须与 Platform `MC_API_TOKEN` 一致（开发常为 `dev-mc-token`）；留空则**不会**回落默认值，本机 Runner 无法启动  

2. **管理台 → 启动本机 Runner**（IDE 为 AutoPilot 客户端，子进程执行 `python -m autopilot.runner …`，协议与 §4.1 一致）  
3. **停止本机 Runner**：同菜单；关闭 IDE 也会自动停掉本机 Runner

> **不要**同时用 CLI 与 IDE 拉两个相同 `--runner-id` 的 Runner，会互相抢心跳/任务。

### 4.3 多台设备机接入（机房 / 工位）

单台电脑的 USB 供电和 adb/usbmux 有限（常见 Android 4～8 台）。**不要**把所有测试机插到跑 Platform 的那台服务器上。正确模型：

```text
一台 Platform（调度中心）
  ├── Runner lab-shanghai-01   工位/工控机 USB
  ├── Runner lab-shanghai-02   另一台设备机
  └── Runner lab-ios-mac01     Mac mini（iOS 更稳）
```

**操作（每台插手机的电脑做一次）：**

1. Web「设备与执行 → 执行节点 → 创建远程节点」：选组织，节点 ID 用 `lab-地点-机器`。
2. 复制一次性启动命令。**到插手机的那台电脑**上执行，不要在 Platform 服务器上执行。
3. 该节点上线后，Web 点「管理设备」，勾选本机扫到的 UDID 注册。设备进组织池，不绑某个项目。
4. 多项目共用机房：用「设备池」把这些节点授权给项目，不要按项目重插线。

同一 UDID 不要同时挂在两台 Runner 上，服务端会冲突折叠，只调度一台。

**开机自启（关窗口会掉线）：**

Linux `systemd` 示例（把路径、Token、节点 ID 换成预配结果；Token 只放环境文件，勿进 git）：

```ini
# /etc/systemd/system/autopilot-runner.service
[Unit]
Description=AutoPilot Runner
After=network-online.target

[Service]
Type=simple
User=autopilot
WorkingDirectory=/opt/autopilot
Environment=MC_API_TOKEN=<预配Token>
ExecStart=/opt/autopilot/.venv/bin/python -m autopilot_platform.runner --server https://platform.example --runner-id lab-shanghai-01 --poll-interval 3
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now autopilot-runner
```

Windows：用「任务计划程序」在用户登录时启动同一条 `python -m autopilot_platform.runner ...` 命令，或用 NSSM 把该命令装成服务。启动后不要关那个控制台窗口（除非已做成服务）。

网页**不能**替你启动远程电脑上的 Runner，只能预配、注销和轮换令牌。

**同仓 ≠ 同机部署。** B/C 设备机要的是单独的 **Runner 进程**，不是再起一套 Platform。源码与平台同仓、安装 extra 分开即可：设备机只装 `pip install -e ".[runner]"`，只跑 `python -m autopilot_platform.runner --server <A 的局域网地址>`，**不要**在 B/C 上执行 `start_dev.py` 或 `python -m autopilot_platform.platform`。

> **预留（后续拓展，本阶段不改代码）**：安装面削瘦与可选独立 Runner 包，见 [managementconsole-split.md §预留](../managementconsole-split.md#预留runner-安装面削瘦与独立包不做当前交付)。当前 `.[runner]` 仍会顺带装上部分平台 pip 依赖，但设备机**不要启动** FastAPI / Web。不要为了多机挂载先拆第三仓。

---

## 5. 桌面 IDE 侧操作

### 5.1 登录与连接

- 启动 IDE 后须先登录（C/S：会话 JWT 来自 Platform）。地址配好 **不等于** 免登录。
- **本机开发**：未部署 `platform.url` 时默认 `http://127.0.0.1:8000`，登录页可改地址（「连接设置…」）。
- **向用户分发的安装包**：不要让用户手填 IP。把 `platform.url.example` 复制为 `platform.url`，写入完整根 URL（含 `http(s)://` 和端口），放到：
  - 与 `AutoPilot.exe` 同目录，或
  - `%ProgramData%\AutoPilot\platform.url`（全机一份），或
  - 设置机器环境变量 `AUTOPILOT_PLATFORM_URL`
- 部署文件生效后 IDE **锁定**服务器地址，用户只输入用户名/密码并选项目。联调若要改地址，须设 `AUTOPILOT_ALLOW_PLATFORM_URL_OVERRIDE=1`。
- 该 URL 必须与用户网络能访问的 Platform 对外地址一致（`MC_PLATFORM_URL` / 反代 HTTPS 主机名）。非 loopback 须先完成 [§10](#10-生产部署安全基线)。
- 厂商 AI Key 配在 Platform 运维中心，不要写进 IDE 安装包。
- **管理台 → 连接设置…**：未锁定时可改服务器、账号、默认项目空间、Runner Token。配置落在 `~/.autopilot/settings.json`（锁定后其中的 `mc_server_url` 默认不再生效）。
- **退出登录**：清会话；取消再登录会退出应用。

完整字段与优先级见兄弟仓 AutoPilot [`docs/CONFIGURATION.md` §1](../../../AutoPilot/docs/CONFIGURATION.md) 与 [`docs/packaging.md`](../../../AutoPilot/docs/packaging.md)。

### 5.2 典型工作流

| 步骤 | 操作                                          |
|----|---------------------------------------------|
| 1  | Platform + Runner 已按第 3、4 节就绪               |
| 2  | IDE 登录；可选「打开管理台」用浏览器看 Web                   |
| 3  | 本地编辑用例、本机设备调试（本地池，**不会**自动进 TR 池）           |
| 4  | **上传工程制品**：打包用例、配置 zip 到 Platform           |
| 5  | **上传应用资源**：apk 或 ipa 进独立应用资源库（可选，远程装包推荐）    |
| 6  | **提交远程批跑…**：选制品（或路径）、应用资源、**TR 设备** 后提交 Job |
| 7  | 进度、日志、报告：在 Web「批跑」「报告」查看；或 IDE 侧状态栏相关入口     |

本地设备池 vs TR 池：

- IDE「已连接设备」= 本地池，只服务本机执行。
- Web「设备」= TR 池，只收录 **已注册 Runner 心跳上报** 的设备。
- 远程批跑必须勾选 TR 设备；因此必须先跑 Runner。

### 5.3 IDE 管理台菜单一览

| 菜单                        | 作用                                 |
|---------------------------|------------------------------------|
| 连接设置…                     | 服务器、账号、项目空间、API Token              |
| 退出登录                      | 清会话                                |
| 启动本机 Runner / 停止本机 Runner | 本机 Agent 进出 TR 池                   |
| 上传工程制品                    | zip 上传到 `/api/v1/artifacts`        |
| 上传应用资源                    | apk 或 ipa 上传到 `/api/v1/app-builds` |
| 提交远程批跑…                   | 创建 Job（制品 + 应用 + TR 设备）            |
| 打开管理台                     | 浏览器打开 Web（带 JWT SSO）               |

---

## 6. Web 管理台侧操作

登录：`http://127.0.0.1:5173`（开发）或 Platform 同源根路径（生产构建）。

建议路径：

1. **概览**：Runner / 设备 / 任务健康一览  
2. **工程制品**：上传或确认 IDE 已上传的 zip  
3. **应用资源**：上传或管理 apk、ipa 版本  
4. **批跑**：选制品 → 选应用资源 → 勾选 TR 设备 → 提交；查看队列与日志  
5. **报告**：按应用版本、工程制品筛选；双报告对比；admin 可用 `POST /api/v1/reports/purge` 按 `MC_JOB_REPORT_RETENTION_DAYS` 清理终态 Job 报告目录  
6. **设备**：确认 Runner 在线且设备空闲或占用状态正常（后台 reclaim 会写审计，并清理终态 Job 留下的孤儿占用）  
7. **计划 / 运维 / 用户 / 审计**（admin）：按需配置  

批跑编排原则：工程制品（用例）与应用资源（安装包）分开管理；Job 同时引用两者（应用资源可选，但远程正式装包应指定 `app_build_id`）。

---

## 7. 端到端最小验收清单

- [ ] `python start_dev.py` 成功；`:8000/health` OK  
- [ ] Web 能用 `admin` / `admin` 登录  
- [ ] 另开终端或 IDE 启动 Runner，日志出现 `[runner] id=…`  
- [ ] Web「设备」能看到本机 USB 设备（线已连、adb 或 ios 已信任）  
- [ ] IDE 或 Web 上传一件工程制品、一个应用资源  
- [ ] 创建批跑并选中一台 TR 设备；任务变为 running → succeeded 或 failed  
- [ ] 「报告」能打开 HTML 或对比结果  

---

## 8. 常见问题

| 现象                     | 排查                                                                                             |
|------------------------|------------------------------------------------------------------------------------------------|
| Runner 立刻报错连不上         | Platform 未起，或 `--server` URL、端口不对                                                              |
| `401` 或 Token 无效       | `--token` / `--token-env` 读到的值与 Platform 执行通道不一致；loopback 开发请核对 `.env` / `.env.example` |
| Web 无设备                | Runner 没跑；或 USB 未授权；本地 IDE 列表不等于 TR 池；Windows 上 iOS 须能 `python -m pymobiledevice3 usbmux list` |
| IDE 无法登录               | 开发态：连接设置里服务器不是正在跑的 Platform，或账号密码错。分发态：`platform.url` / `AUTOPILOT_PLATFORM_URL` 不是用户能访问的完整 URL（须含协议和端口）；或 Platform 未按该地址监听 / 未配生产密钥 |
| 任务一直 pending           | 无在线 Runner，或设备被占用、平台不匹配                                                                        |
| IDE 与 CLI 两个 Runner 打架 | 使用同一 `runner-id`；停掉其中一个或改 id                                                                   |
| 关终端后节点离线              | 前台跑的 Runner 随窗口退出；机房请按 §4.3 做成 systemd / 任务计划开机自启                                             |
| 想把几十台手机插一台 Platform 服务器 | USB 扛不住；按 §4.3 每台设备机一个远程节点                                                                       |
| 远程节点网页点了启动没反应         | 网页不能启停远程进程；把预配命令拿到插手机的电脑上执行                                                                   |
| Runner 和平台代码在同一仓，B/C 是否必须拆服务 | 不必。同仓只表示源码在一起；B/C 只装 `.[runner]`、只起 Agent 进程即可。安装面削瘦 / 独立包是**预留工作项**，见 [split 文档](../managementconsole-split.md#预留runner-安装面削瘦与独立包不做当前交付) |
| `/metrics` 远程 401      | 非本机 scrape 须带 JWT 或 `X-API-Token`；或把 Prometheus 放到同机                                           |
| SSO 登录后前端无会话           | 确认 redirect 落到前端原点且 token 在 `#fragment`；清缓存后重试                                                 |

---

## 9. 相关文档

- **Runner 设备侧环境**：[Android](android.md) · [iOS](ios.md) · [Web](web.md)（跑真机批跑的节点机器必看）；多设备机见 [§4.3](#43-多台设备机接入机房--工位)
- **仓边界 / 安装 extra**：[managementconsole-split.md](../managementconsole-split.md)（含 Runner 安装面削瘦预留项）
- [iOS Monkey 稳定性测试](ios_monkey.md)
- [管理台架构 / API / 数据](../managementconsole.md)
- [前端开发说明](../../autopilot_platform/frontend/README.md)

---

## 10. 生产部署（安全基线）

**HTTPS**：对外 URL 须为 `https://` 时，见 **[HTTPS / TLS 部署指南](https.md)**（反代或 uvicorn 证书；`start_dev.py` 开发仍 HTTP）。

对外暴露 Platform / Web 前，至少设置：

```bash
# Runner 执行通道（勿用默认 dev-mc-token）
export MC_API_TOKEN="<强随机串>"

# 运维专用 Token（强烈建议）：设置后 MC_API_TOKEN 不再具备 admin
export MC_ADMIN_API_TOKEN="<另一强随机串>"

# 用户 JWT 签名（勿用内置开发默认值）
export MC_JWT_SECRET="<至少32字节随机>"

# 引导管理员（勿用 admin/admin）
export MC_ADMIN_USER="ops-admin"
export MC_ADMIN_PASSWORD="<强密码>"
```

| 项                    | 要求                                                 |
|----------------------|----------------------------------------------------|
| `MC_API_TOKEN`       | Runner / 执行 `X-API-Token`；与 Runner 端 `--token-env` 对应变量一致；**不得**与 ADMIN 相同 |
| `MC_ADMIN_API_TOKEN` | 运维通道（**生产 / 非 loopback 必配**）；未设置时全局 `MC_API_TOKEN` 默认不为 admin；仅 `MC_ALLOW_LEGACY_TOKEN_ADMIN=1` 兼容升权 |
| `MC_ALLOW_LEGACY_TOKEN_ADMIN` | 默认关；迁移逃生口 |
| `MC_ENV` / `MC_REQUIRE_ADMIN_API_TOKEN` | 生产或显式开关：强制拆分 ADMIN token；非 loopback 绑定同样校验凭据强度 |
| `MC_JWT_SECRET`      | 签发/校验用户 JWT；泄露可伪造登录                                |
| `MC_ACCESS_TOKEN_MINUTES` | Access JWT 有效期（分钟），默认 60；可设 `MC_JWT_EXPIRE_HOURS` 覆盖为长会话 |
| `MC_REFRESH_TOKEN_DAYS` | Refresh 有效天数，默认 14；登出/改密可吊销 |
| `MC_ADMIN_PASSWORD`  | 空库 bootstrap 管理员密码；改密后旧默认账号若已创建须在库内重置              |

> 完整变量清单（含存储 / 调度 / SSO / Runner / 设计域 webhook / AI 等）见仓库根 [`.env.example`](../../.env.example)：复制为 `.env` 按需修改。启动脚本与 `create_app` **会自动加载**仓库根 `.env`（已有环境变量不被覆盖；也可用 shell `export` / 运维区 `/ops/config`）。

**调度 / 多实例（AUD-2026-13 · RISK ACCEPTED）：**

- **无独立 MQ**：计划触发与回收走进程内 `schedule` 线程 + DB，不引入 Celery/Redis Queue 等（见 `docs/architecture/ADR_scheduler_no_mq.md`）。
- 默认假设 **单活调度**：同一 `MC_DATABASE_URL` 上 schedule tick（计划触发、僵死回收、报告清理、fleet 告警）靠 `ops_locks` 租约选出一个 leader。
- 多副本时：仅一个节点 `MC_SCHEDULE_ENABLED=1`，其余设 `0`（推荐明确），或依赖租约自动互斥。
- **SQLite** 适合单进程联调；多实例写入请改 **PostgreSQL**（`.[pg]`）。

**Prometheus：**

- 同机 scrape → `GET http://127.0.0.1:8000/metrics` 可匿名（仅认 **TCP/ASGI peer** 为 loopback；**不**信任 `X-Forwarded-For` / `X-Real-IP`）。
- 远程 scrape → 请求头带 `Authorization: Bearer <admin-jwt>` 或 `X-API-Token: <MC_ADMIN_API_TOKEN|MC_API_TOKEN>`，或将 scrape 放到本机。
- 关闭：`MC_METRICS_ENABLED=0`。

**SSO 前端 redirect：**

- OIDC / SAML 成功回跳默认使用 **URL fragment**（`#access_token=…`），避免 token 进 access log / Referer。
- 配置 `MC_OIDC_FRONTEND_REDIRECT` / `MC_SAML_FRONTEND_REDIRECT` 指向 Web 原点即可（例如 `https://mc.example.com/`）；勿再依赖 query 传 token。
- 前端仍兼容历史 query 回调；IDE「打开管理台」同样优先 hash。

### 向用户分发 IDE

> 配置真源：[CONFIGURATION.md §7](../CONFIGURATION.md#7-向用户分发-ideplatform-地址)

**原则**：Platform 根 URL **只配一次**，服务端与 IDE 客户端须一致。`platform.url.example` 只是 IDE 仓里的模板，**程序不读**；必须复制为 `platform.url` 或通过环境变量下发。

| 步骤 | 服务端（本仓） | 客户端（IDE 安装包 / 用户 PC） |
|------|----------------|------------------------------|
| 1 | 按上文轮换 `MC_API_TOKEN`、`MC_JWT_SECRET`、管理员口令 | — |
| 2 | 设置对外根 URL：`MC_PLATFORM_URL=https://…`，或 `deploy/platform.env.example` → `%ProgramData%\AutoPilot\platform.env` | 同 URL 写入 `platform.url` 或 `AUTOPILOT_PLATFORM_URL` |
| 3 | 反代 / 防火墙 / TLS 使该 URL 对用户可达 | 文件放 exe 同目录，或 `%ProgramData%\AutoPilot\platform.url`（升级 exe 不覆盖） |
| 4 | 运维中心配置 `AP_AI_*`（链路 3 / 设计域 AI） | **不要**把 AI Key 打进 IDE |
| 5 | 自检：`GET /api/v1/public/bootstrap` 的 `platform_base_url` | 自检：`python tools/config_doctor.py`（IDE 仓） |

**URL 格式**：一行完整地址，例如 `https://autopilot.company.com` 或 `http://192.168.1.10:8000`。只写 IP、不写协议/端口无效。

**用户侧体验**：启动 IDE → 地址已锁定 → 输入 Platform **用户名 / 密码** → 选项目空间。锁定地址 ≠ 免登录。

打包细节见 IDE 仓 [`docs/packaging.md`](../../../AutoPilot/docs/packaging.md#分发时写入-platform-地址)；字段优先级见 [`docs/CONFIGURATION.md` §1](../../../AutoPilot/docs/CONFIGURATION.md#1-ide--platform-api-地址)。

**登录失败限速：**

- 登录限速：失败计数写入共享表 `login_rate_buckets`（多 worker / 多实例共库生效）；同一客户端短时多次密码错误会 `429`（默认约 8 次 / 60s，见 `platform/core/login_rate.py`）。
- **多实例部署时各进程独立计数**，不跨节点共享；对外暴露时请在反向代理 / WAF 再加一层 IP 限速，或前面挂统一入口。

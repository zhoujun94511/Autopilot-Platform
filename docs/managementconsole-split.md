# Platform 仓边界说明

> **服务端**：Platform + Web。  
> **执行 Agent**：本仓 `autopilot_platform/runner` 与 IDE `autopilot/runner` **各维护一份**（协议对齐，HTTP only）。  
> Platform **禁止** import `autopilot`；执行核为仓内同构切片 `autopilot_platform.ap`（非外部 autopilot 包）。

## 依赖矩阵

| 组件 | 安装 | 说明 |
|------|------|------|
| Platform | `pip install -e ".[platform]"` | 本仓 FastAPI 栈 |
| Platform Runner | `pip install -e ".[runner]"` | Agent；执行核 `autopilot_platform.ap` |
| IDE / 本机 Runner | AutoPilot：`python -m autopilot.runner` | 客户端默认入口 |

```text
IDE / Platform-Runner  ──HTTP──►  Platform
```

## 保留原则

必要联调流程（注册、心跳、claim、执行）在 **两边产品面都要能跑通**，不为「仓绝对干净」删除 Agent。  
干净边界指：**Platform 与客户端实现零 import**，不是「服务端仓不许有 Runner 目录」。

**部署边界**（与源码同仓独立）：中心机只起 Platform + Web；插手机的设备机只起 `autopilot_platform.runner`，通过 `--server` 指向同一 Platform。同仓不要求设备机再起一套管理台。

## 预留：Runner 安装面削瘦与独立包（不做当前交付）

多设备机接入**不依赖**先拆仓。下列为后续拓展预留，**本阶段不改 `pyproject.toml`、不改 Runner 入口、不新建第三仓**。

| 档 | 内容 | 何时才做 |
|----|------|----------|
| 现状（已够用） | 设备机 `pip install -e ".[runner]"` + `python -m autopilot_platform.runner --server …`；不启 Platform / Web | 现在就这样接 B/C |
| 预留 A：安装面削瘦 | 主依赖只留 Agent 真正需要的包；FastAPI / SQLAlchemy / 前端栈全部进入 `.[platform]`；去掉 Runner 对 `platform.core.urls` 等平台包的引用 | 设备机环境明显过胖、或要发精简 wheel 时 |
| 预留 B：独立 `autopilot-runner` 包 / 仓 | 设备机一条命令装 Agent，不再 clone 整个 Platform 仓 | 预留 A 已落地且发布周期稳定之后 |
| 相关但不同 | 执行核 `ap/` 切成单一 `autopilot-runtime` wheel | 见 [DUAL_REPO_CONTRACT.md](architecture/DUAL_REPO_CONTRACT.md) §1.4（AUD-P1-005）；**不是**本项 |

**明确不做（本预留项范围内）**：为「心理上更干净」先拆第三 Git 仓；在设备机再部署一套 Platform；复制第二套关键字引擎；用网页远程拉起 B/C 上的进程。

## 多 Runner 同设备

服务端与 IDE 客户端常分离部署，可能短时双挂同一 UDID：

- 心跳调和：多台在线同 UDID → 非 primary 标 `conflict`（不可调度）；primary = 已 busy 者，否则 `runner_id` 字典序最小
- **看板容错**：`GET /devices` 按 UDID 折叠为一行（只露 primary），不向用户甩双行 / conflict 告警
- claim / occupy：全局检查其它在线挂载或 busy，杜绝物理同机双跑
- 对端离线（心跳超时）后，下一跳心跳清除 conflict
- 注册兜底：`register` 幂等；`heartbeat` 可在未注册时自愈建档；Agent 遇 404 会补注册再心跳

## 统一错误信封

Platform 错误响应（对齐 Scenario_Engine）：

```json
{
  "code": "E4001",
  "message": "用户名或密码错误，请重试。",
  "error_type": "auth_failed",
  "trace_id": "…",
  "details": null
}
```

- 文案与错误码由后端 `core/errors.py` + `platform/api_messages.py` 管理  
- 前端 `api.ts` 解析信封，UI 展示 `message`（仅网络不可达时前端兜底）  
- 成功响应仍为原业务 JSON，暂不强制 `ok` 信封（避免破坏 Runner/既有客户端）

## 验证

- [x] Platform / `app_builds` / `app_meta` 无 `import autopilot`（用 `autopilot_platform.appparse`）
- [x] Console `execute` 用 `autopilot_platform.ap`，无外部 `import autopilot`
- [x] 装包解析唯一入口 `appparse`；Platform aapt 不依赖 `ap.mobile`
- [x] 裁掉 IDE 冗余（devices 枚举 / lint / lease / mirror UI / scheduler）
- [x] `autopilot_platform.runner` 可 `--dry-probe`
- [x] `autopilot.runner` 可 `--dry-probe`
- [x] 多 Runner 同 UDID 冲突 / 心跳自愈单测
- [ ] 执行路径：Console `[runner]` 或 AP Runner 领任务跑通

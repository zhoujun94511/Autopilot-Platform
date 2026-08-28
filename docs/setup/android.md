# Android 环境配置（TestRunner 节点）

> **面向对象：TestRunner 节点所在机器。**  
> 批跑的 Android 用例由 Runner 在**靠近设备的机器**上经 **Appium**（uiautomator2 driver）执行，因此该机器需具备下列外部运行时。  
> **Platform / Web 机器无需本页环境**——只装 `pip install -e ".[platform]"` 即可。  
> 启动与联调流程见 [操作指南](managementconsole.md)。

## 0. 前置

先在 Runner 机器上安装 Runner 依赖（本仓根目录，建议 venv）：

```bash
pip install -e ".[runner]"
```

`runner` 组已包含 `Appium-Python-Client`、`opencv-python-headless`、`numpy` 等 Python 客户端；APK 解析用主依赖里的 `pyaxmlparser`（无需 Android SDK build-tools）。

> **Python 客户端 ≠ 外部运行时。** `.[runner]` 只装 Python 侧；真正跑 Android 还需 **JDK + Node + Appium + uiautomator2 驱动**（见 §3），它们不是 pip 包。

## 1. adb（内置自举，通常零配置）

本仓自带 adb，无需单独安装。解析顺序见 [`autopilot_platform/ap/mobile/adb.py`](../../autopilot_platform/ap/mobile/adb.py)：

1. 环境变量 `ADB_PATH` / `ADBUTILS_ADB_PATH`；
2. 系统 `PATH` 上已有的 `adb`（尊重你的工具链）；
3. 都没有 → 从 `resources/re_adb/platform-tools-latest-<os>.zip` 解压到 `resources/runpath/` 并前插 PATH。

解析到的目录会注入 PATH，供 Appium 子进程继承。验证设备连通：

```bash
adb devices            # 已在 PATH；或用解压后的 resources/runpath/.../adb
```

## 2. Appium Server + uiautomator2 driver

Appium 需要 **Node.js（≥18）** 与 **JDK 17+**。

```bash
# 1) 安装 Appium
npm install -g appium

# 2) 安装 Android 驱动
appium driver install uiautomator2

# 3) 启动 server（默认 http://127.0.0.1:4723）
#    macOS：Appium 服务进程需 ANDROID_HOME（UiAutomator2 驱动读 SDK）
export ANDROID_HOME="$HOME/Library/Android/sdk"   # macOS Android Studio 默认
export ANDROID_SDK_ROOT="$ANDROID_HOME"
appium

# 4) 环境体检（可选）
npm install -g @appium/doctor && appium driver doctor uiautomator2
```

- **JDK 17+**：设 `JAVA_HOME`；Appium 的 uiautomator2 驱动构建/安装设备侧组件时需要。
- **ANDROID_HOME / ANDROID_SDK_ROOT**：macOS 上 Appium **服务进程**需要（驱动读 SDK）；Windows 上通常由驱动自带工具链，视报错补齐。

### 2.1 「设备侧 apk」≠「宿主侧驱动」（别混淆）

uiautomator2 在两层各有一份东西，**不能互相替代**：

| 层       | 是什么                                                 | 在哪                              |
|---------|-----------------------------------------------------|---------------------------------|
| **宿主侧** | `appium driver uiautomator2`（Node 驱动，跑在电脑上）         | `npm` / `appium driver install` |
| **设备侧** | `io.appium.uiautomator2.server(.test)` 等 apk（跑在手机上） | 建会话时由上面那个驱动自动推到设备               |

仓库里的 `resources/re_uiautomator/app-uiautomator*.apk` 是**设备侧** server 的副本，**当前代码并不直接引用**——Android 走 Appium 时，宿主侧 uiautomator2 驱动会携带并安装它自己那份。所以即使 `resources/re_uiautomator` 在位，仍必须安装**宿主侧** `appium driver install uiautomator2`。

Runner 执行时通过执行上下文传入 Appium server 与 caps（见 [`ap/keywords/mobile/session.py`](../../autopilot_platform/ap/keywords/mobile/session.py)、[`ap/keywords/mobile/driver.py`](../../autopilot_platform/ap/keywords/mobile/driver.py)）：

- `__appium_server__`：server 地址（默认 `http://127.0.0.1:4723`）；
- `__appium_caps__` / `__device_udid__`：附加 capabilities 与设备序列号；
- **`appium_start`**：Android 用例会启动/检测本机 Appium（4723）；iOS 在 Win/Linux WDA-direct 模式下自动跳过（见 [iOS 配置](ios.md)）。

### 2.2 装卸与自动化分层

（Windows / macOS / Linux 行为一致。）被测应用的 **安装、卸载** 刻意 **不经过 Appium** `install_app` / `remove_app`，而在 **设备层** 用 adb 完成（[`ap/mobile/adb.py`](../../autopilot_platform/ap/mobile/adb.py)；关键字编排见 [`ap/keywords/mobile/session.py`](../../autopilot_platform/ap/keywords/mobile/session.py)）：

| 关键字                           | 设备层实现                              | 之后                                         |
|-------------------------------|------------------------------------|--------------------------------------------|
| `mobile_app_install_and_open` | `adb install`（支持 `-r` 保留数据 / 先卸再装） | `AppiumManager.create()` 建 UiAutomator2 会话 |
| `mobile_app_adb_uninstall`    | `adb uninstall`（`-k` 可选保留缓存）       | 无需会话                                       |

元素点击、截屏等 **会话内** 操作仍走 Appium；与装/卸分层。iOS 对应说明见 [iOS 配置 §4](ios.md#4-装卸与自动化分层)。

## 3. 真机注意事项

- **开启开发者选项 + USB 调试**；首次连接在手机上「允许 USB 调试」。
- **允许通过 USB 安装应用**：Appium 会安装 `io.appium.uiautomator2.server` 等辅助 apk。部分 ROM（MIUI/HyperOS）需在开发者选项里打开「USB 安装」「USB 调试(安全设置)」。
- **UIA2 初始化失败**（`instrumentation cannot be initialized`）：通常是旧版辅助 apk 残留，先卸载再重连：

```bash
adb uninstall io.appium.uiautomator2.server
adb uninstall io.appium.uiautomator2.server.test
adb uninstall io.appium.settings
```

## 4. 实时镜像（scrcpy，可选，非 Runner 必需）

Web / IDE 的「实时镜像」面板走 scrcpy（H.264），与批跑执行无关。**Console 的 `runner` 组默认不含镜像依赖**；仅当你要在此机预览/交互控制时再单独安装：

```bash
pip install "av>=12.0" "adbutils>=2.0"
```

- 设备侧 server 已内置：`resources/re_scrcpy/scrcpy-server.jar`，无需手装 scrcpy。
- 依赖/资源缺任一会**自动回退**到 MJPEG / 截图轮询。

## 5. 验证

在 Runner 机器上探测设备与后端是否就绪（不连 Platform、不领任务）：

```bash
python -m autopilot_platform.runner --dry-probe
```

输出应能列出本机 USB 设备及可用后端（Android 需 adb 已授权、Appium 就绪）。随后正式启动 Runner 即可在 Web「集群资源 → 设备」看到该机设备（见 [操作指南 §4](managementconsole.md#4-启动执行节点注册进设备池)）。

## 6. 常见问题

- **`adb devices` 空**：换数据线/口、确认已授权调试、`adb kill-server && adb start-server`。
- **Appium 连不上**：确认 `appium` 在跑、端口 4723、`__appium_server__` 一致。
- **`Neither ANDROID_HOME nor ANDROID_SDK_ROOT`**：在**启动 appium 的终端**里 export SDK 路径后重启 appium。
- **mobile 关键字报未实现**：未装 Runner 组，执行 `pip install -e ".[runner]"`。
- **Web「设备」页看不到该机设备**：Runner 未启动、USB 未授权，或 IDE 本地列表 ≠ TR 池（须启动 Runner，见操作指南 §4）。

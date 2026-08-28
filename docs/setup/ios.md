# iOS 环境配置（TestRunner 节点）

> **面向对象：TestRunner 节点所在机器。**  
> 批跑的 iOS 用例由 Runner 在**靠近设备的机器**上执行，基于设备上的 **WebDriverAgent（WDA）** HTTP 服务。  
> **Platform / Web 机器无需本页环境。** 启动流程见 [操作指南](managementconsole.md)。

按宿主系统选择会话后端（[`ap/keywords/mobile/platform.py`](../../autopilot_platform/ap/keywords/mobile/platform.py)）：

| 宿主                  | 默认后端                       | 是否需要 Appium server                  |
|---------------------|----------------------------|-------------------------------------|
| **Windows / Linux** | **WDA-direct**             | **否**（`appium_start` 自动跳过）          |
| **macOS**           | Appium xcuitest（golden 参考） | 是（WDA 由 go-ios 准备，Appium 仅 HTTP 代理） |

Win/Linux 上 iOS 17+ 无法使用 Appium 的 RemoteXPC 隧道，因此主路径是 **go-ios + pymobiledevice3 准备 WDA → 直连 WDA HTTP**（[`ap/keywords/mobile/wda_client.py`](../../autopilot_platform/ap/keywords/mobile/wda_client.py)）。macOS 的 Appium golden 路径同样是 go-ios `runwda` + `webDriverAgentUrl` 直连。

## 0. 前置

在 Runner 机器安装 Runner 依赖（`runner` 组已含 `pymobiledevice3`）：

```bash
pip install -e ".[runner]"
```

## 1. 先决条件：编译 WDA（Mac/Xcode 侧，一次性）

把签好名的 WebDriverAgentRunner 安装到目标设备。这一步与宿主无关，**必须在 Mac 上用 Xcode 完成一次**。完整步骤见桌面 IDE 仓（AutoPilot）的 WDA 文档：

- [WebDriverAgent 编译与构建（中文）](../wdadoc/IOS自动化测试之WebDriverAgent编译与构建.md)
- [Building WebDriverAgent for iOS Automation (EN)](../wdadoc/Building-WebDriverAgent-for-iOS-Automation.en.md)

要点：用 Apple 开发者账号在 Xcode 里为 WebDriverAgentRunner 配置签名 → 真机 build/test 安装一次 → 设备「设置 → 通用 → VPN与设备管理」信任该开发者证书。装好后设备上常驻可被 `runwda` 唤起的 WDA。

## 2. go-ios（内置 `resources/re_go_ios`，零下载）

go-ios 负责 iOS 17+ 的**用户态 RSD 隧道**、**`runwda` 启动 WDA**、**DeveloperDiskImage 挂载**——都不需要管理员权限。资源随仓库放在 `resources/re_go_ios/`；首次使用会优先采用已展开的二进制，否则自动把对应宿主系统的 zip 解压到忽略版本控制的 `runpath/`，最后才回退到 PATH：

| 子项                       | 说明                                                             |
|--------------------------|----------------------------------------------------------------|
| `executable/win/ios.exe` | 可选的预展开 go-ios Windows 二进制（mac/linux 同理）                        |
| `utils/go-ios-*.zip`     | 随仓压缩包；缺预展开二进制时自动解压到 `runpath/<os>/`                       |
| `wintun/`                | Windows 上隧道所需的 wintun 驱动                                       |
| `devimages/`             | DeveloperDiskImage 缓存（首次可为空，由工具按设备在线下载）                      |

关键点：

- **用户态隧道**：go-ios 以 `ENABLE_GO_IOS_AGENT=user` 跑隧道 agent，**Windows 免管理员**。
- **端口要钉死**：隧道 agent 的 HTTP-API 端口需固定（`--tunnel-info-port`），否则崩溃后留孤儿进程占端口。

以上隧道 / 挂镜像 / runwda / 转发均由 [`ap/mobile/ios_bootstrap.py`](../../autopilot_platform/ap/mobile/ios_bootstrap.py)（`IosDevicePrep.prepare()`）代码化编排，**正常批跑无需手动执行**。

## 3. pymobiledevice3（设备发现 / 端口转发）

pymobiledevice3 走 usbmux，做不依赖隧道的活：列设备、把设备上 WDA 的 **8100** 端口转发到本机。排障时可手动执行：

```bash
python -m pymobiledevice3 usbmux list                             # 列出已连设备 + UDID
python -m pymobiledevice3 usbmux forward 8100 8100 --udid <UDID>  # 本机:8100 → 设备 WDA:8100
```

转发后，本机 `http://127.0.0.1:8100/status` 能摸到 WDA 即就绪。

## 4. 装卸与自动化分层

被测 **.ipa 的安装、卸载** 在 **设备层** 完成（[`ap/mobile/ios_bootstrap.py`](../../autopilot_platform/ap/mobile/ios_bootstrap.py) 的 `install_app` / `uninstall_app`；关键字编排见 [`ap/keywords/mobile/session.py`](../../autopilot_platform/ap/keywords/mobile/session.py)），**不经过** Appium，且 Windows / macOS / Linux 使用同一套实现：

| 步骤    | 实现                                                          | 说明                   |
|-------|-------------------------------------------------------------|----------------------|
| 安装    | pymobiledevice3 `InstallationProxy` → 失败回退 go-ios `install` | IPA 预检（描述文件、授权 UDID） |
| 卸载    | pymobiledevice3 `uninstall` → 失败回退 go-ios `uninstall`       | 无需已建 WDA/Appium 会话   |
| 检测已安装 | pymobiledevice3 `get_apps`                                  | 用于装前是否先卸             |

Android 侧对称说明见 [Android 配置 §2.2](android.md#22-装卸与自动化分层)。内置 go-ios 按宿主系统选用 `resources/re_go_ios/executable/{win,mac,linux}/`。

## 5. macOS Appium xcuitest（可选，golden 参考）

以下适用于 **macOS + `backendMode=appium`**。Win/Linux 跑 iOS 可跳过本节。

```bash
npm install -g appium
appium driver install xcuitest
appium    # http://127.0.0.1:4723
```

WDA 由 **go-ios `runwda`** 拉起、经 pymobiledevice3 转发到本机 8100；Appium **只当 HTTP 代理**，不 build/install/卸载 WDA：

| Cap                                      | 值                       | 说明                                               |
|------------------------------------------|-------------------------|--------------------------------------------------|
| `appium:webDriverAgentUrl`               | `http://127.0.0.1:8100` | 必填                                               |
| `appium:udid`                            | 设备 UDID                 | 必填                                               |
| `platformName` / `appium:automationName` | `iOS` / `XCUITest`      | 必填                                               |
| **`appium:usePreinstalledWDA`**          | **勿设**                  | 设了会触发 xcuitest 驱动 `cleanupApps`，**卸载自定义签名的 WDA** |

`build_ios_caps()`（[`ap/mobile/ios_bootstrap.py`](../../autopilot_platform/ap/mobile/ios_bootstrap.py)）已只输出 `webDriverAgentUrl`（无 `usePreinstalledWDA`）。

## 6. 启动顺序小结

### 6.1 Win/Linux — WDA-direct（推荐，无需 Appium）

1. （一次性）Mac/Xcode 编译签名安装 WDA → 设备信任证书。
2. 用例执行：`mobile_app_install_and_open`（设备层装 IPA）→ `AppiumManager.create()` 内部自动：go-ios 用户态隧道（iOS 17+）→ 挂 DeveloperDiskImage → `runwda` 拉起 WDA → pymobiledevice3 转发 8100 → 建 WDA HTTP session → `launch_app`。
3. 步骤里的 `appium_start` **自动跳过**（识别 `__current_platform__=ios` 且后端为 WDA-direct）。

### 6.2 macOS — Appium golden

1. （一次性）Xcode 编译签名安装 WDA → 设备信任证书。
2. go-ios 用户态隧道 → 挂镜像 → runwda → pymobiledevice3 转发 8100（与 Win 相同准备链）。
3. 启动 Appium（4723），caps **仅** `webDriverAgentUrl` + `udid`（**禁止** `usePreinstalledWDA`）。
4. 设 `IOS_APPIUM_MANAGED=0`；`appium_start` 会启动/检测本机 Appium。

后端由 [`ap/keywords/mobile/platform.py`](../../autopilot_platform/ap/keywords/mobile/platform.py) 决策：`backendMode=auto|appium|wda`，或环境变量 `IOS_BACKEND` / `IOS_BACKEND_MODE`。

## 7. 验证

在 Runner 机器探测 iOS 设备与后端（不领任务）：

```bash
python -m autopilot_platform.runner --dry-probe
# 手动摸设备（排障）：
python -m pymobiledevice3 usbmux list
```

## 8. 常见问题

- **iOS 17+ 开发者服务连不上**：隧道没起或挂了——确认 `ENABLE_GO_IOS_AGENT=user` 且隧道 agent 在跑、端口已钉死。
- **`/status` 摸不到 WDA**：WDA 没 `runwda` 起来，或 8100 没转发；先 `runwda` 再 `forward`。
- **镜像未挂载**：按设备系统版本在 `resources/re_go_ios/devimages` 选对镜像后 `image auto`。
- **证书过期/不信任**：重新在「VPN与设备管理」里信任，或重编 WDA（免费账号 7 天过期）。
- **`appium_start` 报未检测到 Appium**：Win/Linux 跑 iOS 时应自动跳过；若仍报错，确认用例平台（`platform: ios` 或步骤 `type: ios` / `.ipa`）已让执行器写入 `__current_platform__=ios`。
- **Appium 每次跑都卸载 WDA**：caps 里误设了 `usePreinstalledWDA`；macOS golden 路径只用 `webDriverAgentUrl`。
- **Windows 上 iOS 设备列不出**：确认可 `python -m pymobiledevice3 usbmux list`，设备已「信任此电脑」。

## 9. 相关文档

- [iOS Monkey 稳定性测试](ios_monkey.md) — `mobile_monkey` 参数、产出与排障
- [操作指南](managementconsole.md) — 批跑提交与设备池

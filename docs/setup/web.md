# Web（WebUI）环境配置（TestRunner 节点）

> **面向对象：TestRunner 节点所在机器。** WebUI 用例由 Runner 经 **Selenium 4** 执行；Platform / Web 管理台机器无需本页环境。

## 1. 依赖

`selenium`、`opencv-python-headless`、`numpy`（图像识别类关键字 `picture::`、截图比对用）都在 Runner 组里：

```bash
pip install -e ".[runner]"
```

## 2. 浏览器与驱动

Selenium 4 自带 **Selenium Manager**：首次启动会按本机浏览器版本**自动下载匹配的 driver**（chromedriver / geckodriver / msedgedriver），通常无需手动管理。

要求：

- Runner 机器已安装对应浏览器（Chrome / Edge / Firefox）。
- 能联网让 Selenium Manager 拉取 driver（离线见下）。

### 离线 / 手动指定 driver

无外网时，手动下载与浏览器同版本的 driver，并让其可被发现：

- 把 driver 放进系统 `PATH`；或
- 设环境变量指向 driver，或在用例/配置里指定 driver 路径。

> 版本匹配原则：driver 主版本号需与浏览器一致。

## 3. 批跑调度（web 能力上报）

Runner 心跳会**自动探测本机浏览器**（Chrome / Edge / Firefox），若存在则向 Platform 上报 `web` 能力：

- 在 Web 管理台「批跑编排」里，**平台选 `Web`**：此时无需选择移动设备，可选「指定 Runner」定向到某台节点，留空则由**任意具备 web 能力的节点**领取。
- web 任务只会被声明了 `web` 能力的 Runner 领取；移动 Runner 不会误跑，纯 web Runner 也不会误抢移动任务。
- 强制开关：设 `MC_RUNNER_WEB=1` 强制上报 web 能力（无头服务器/探测不到浏览器时），`MC_RUNNER_WEB=0` 则强制关闭。
- 浏览器类型由用例内「浏览器打开」关键字（Chrome / Edge / Firefox / headless）决定，Job 层无需再选。

## 4. 常见问题

- **找不到 driver / 版本不匹配**：升级浏览器或让 Selenium Manager 重新解析；离线则手动放置同版本 driver。
- **headless 与有头行为不一致**：部分站点对 headless 有差异，可在浏览器选项里关掉 headless 调试。
- **图像类关键字报未实现**：未装 Runner 组，执行 `pip install -e ".[runner]"`。

# 前端通知分层约定

真源注释见 `src/composables/useNotify.ts` 文件头。此处便于评审/检索。

| 通道 | API / 位置 | 用 |
|------|------------|----|
| 交互 Modal | `confirmDialog` / `promptDialog` / `showCopyDialog` | 确认、输入、敏感复制 |
| Toast | `notify(text, kind)` | **无表单上下文**的列表/工具动作结果 |
| 内联 msg | `jobMsg` / `artMsg` / `userMsg` / Design `notice` 等 | **绑定当前表单**的校验与结果 |
| 顶栏横幅 | `shell.error` | 全局数据层失败（轮询等） |
| Banner / strip | `Project*Banner`、Dashboard `alert-strip` | 持续情境状态（非通知） |

Toast `kind`：`"success"` 成功、`"info"` 提示、`"warn"` 警告、`"error"` 失败。`toast()` 是 `notify()` 的别名，同一宿主。

**默认只弹出 `warn` / `error`。** `"success"` / `"info"` 调用可保留（列表动作语义），但不弹窗。需要成功提示时：

- 某面板打开：`const { notify } = useNotify({ success: true })` 或 `createNotifier({ success: true })`
- 单次强制：`notify(text, "success", { toast: true })`
- 全局运行时：`setNotifyPolicy({ success: true })`（测试或以后的偏好）

表现：贴在顶栏下方（不挡主题/刷新/健康标签）；最新在上，最多 4 条；success/info 约 2.8s，warn/error 约 5s，悬停暂停。

**判定**：用户还要对着表单改？要 → 内联；不要 → `notify`。

**禁止**：再引入第二套 Toast；列表动作成功写到创建表单旁的 `xxxMsg`（会串台）；把 Toast 改到底部或做成通知中心。

**禁止原生浏览器弹框（全仓，不仅 `useNotify`）**：不要调用 `window.alert` / `window.confirm` / `window.prompt`（以及无前缀的 `alert()` / `confirm()` / `prompt()`）。它们在嵌入 WebView、远控叠层、非前台标签上可能被拦截或无主题样式。确认 / 单字段输入 / 敏感复制一律 `confirmDialog` / `promptDialog` / `showCopyDialog`（唯一宿主 `AppNotifyHost` → `ApModal`）。多字段采集仍用专用表单，不要串联 `promptDialog`。

自制 `modal-mask` / `modal-backdrop` 只允许业务表单、预览、日志查看器，**禁止**再做一套「确定 / 取消」确认层。叠层：Toast `10000` → `ApModal` `10001` → 文件预览 `10002` → stacked 确认 `10003` → `ApSelect` `10004`。

**禁止 `window.open` / `document.write`：** 任务报告在页内 `JobReportViewer`（`ApModal` + `sandbox="allow-scripts"` iframe）打开，避免弹窗拦截和无主题外壳。Chat 链接的 `target="_blank"`（用户点击开新标签）除外。

**禁止原生 `<select>`：** 下拉一律 `ApSelect`（系统弹层与暗色主题不一致）。远控叠层内须 `stack`。

**保留系统能力（不是页面弹框）：** `<input type="file">` 操作系统文件选择器；`navigator.clipboard` 浏览器剪贴板权限条；`<a download>` 本地下载。

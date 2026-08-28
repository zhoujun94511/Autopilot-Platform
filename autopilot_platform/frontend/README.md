# 前端开发（Vite + Vue 3）

**用户联调 / 使用步骤（含执行节点 Runner、IDE）请先看：**

- [docs/setup/managementconsole.md](../../docs/setup/managementconsole.md) — 操作指南  
- [docs/managementconsole.md](../../docs/managementconsole.md) — 架构与 API  

## 一键联调（推荐）

仓库根提供 `start_dev.py`：

```bash
# 在仓库根目录（start_dev.py 不在 autopilot_platform/ 下）
python start_dev.py
# 或
python start_dev.py start --lan
python start_dev.py stop
```

会同时拉起：

- Platform API：`http://127.0.0.1:8000`（`/health`、`/docs`、`/api/v1`）
- Vite 前端：`http://127.0.0.1:5173`（proxy 到后端）

缺 `node_modules` 时会自动 `npm install`。默认打开浏览器；`--no-browser` 可关闭。

默认登录：`admin` / `admin`（**仅联调**）。生产须配置 `MC_API_TOKEN` / `MC_ADMIN_API_TOKEN` / `MC_JWT_SECRET` / `MC_ADMIN_PASSWORD`，见 [docs/setup/managementconsole.md §10](../../docs/setup/managementconsole.md#10-生产部署安全基线)。

### 联调时还需要执行节点

`start_dev.py` **不会**自动启动 Runner。另开终端（仓库根）：

```powershell
# Windows PowerShell — 仅本机 127.0.0.1
$env:MC_RUNNER_TOKEN = "<your-runner-token>"
python -m autopilot_platform.runner --server http://127.0.0.1:8000 --token-env MC_RUNNER_TOKEN
# 同机 IDE 仓可用其本机 Runner（二选一，节点 ID 须不同）：
# python -m autopilot.runner --server http://127.0.0.1:8000 --token-env MC_RUNNER_TOKEN
```

否则 Web「设备」无设备池数据，远程批跑无法选设备。详见操作指南。

## 手动分端启动

```bash
cd autopilot_platform/frontend
npm install
npm run dev          # http://127.0.0.1:5173 ，API 代理到 :8000
```

另开终端（仓库根）：

```bash
python -m autopilot_platform.platform --port 8000
# 或带热重载：
python -m uvicorn autopilot_platform.platform.app:create_app --factory --reload --port 8000
```

再按需启动 Runner（同上）。

## 生产构建

产物写入 `frontend/dist`，由 FastAPI 同源托管：

```bash
npm run build
python -m autopilot_platform.platform --port 8000
# 打开 http://127.0.0.1:8000/
```

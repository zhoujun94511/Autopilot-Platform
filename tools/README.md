# tools/

本目录放 **Platform 运维与巡检 CLI**（不替代 `tests/` 单测）。

## init_platform.py — 命令一览

在**仓库根**执行。Linux/macOS 将 ``.venv\Scripts\python.exe`` 改为 ``.venv/bin/python``。

本地数据均在 **`data/`**（gitignore）：`autopilot_platform.db`、`rag_index/vectors.sqlite`、`mc_runtime_config.json` 等。

### 日常

| 场景 | 命令 |
|------|------|
| 新克隆 / 删过 `data/` | `.venv\Scripts\python.exe tools\init_platform.py init` |
| 开发清库重来 | `.venv\Scripts\python.exe tools\init_platform.py fresh --yes` |
| 查看状态（只读） | `.venv\Scripts\python.exe tools\init_platform.py status` |

然后 `start_dev.py` 或 `python -m autopilot_platform.platform`。默认登录 **`admin` / `admin`**。

### 全部子命令

```powershell
# status — 只读：data_dir、表数、users、bootstrap admin、配置键、向量条目
.venv\Scripts\python.exe tools\init_platform.py status

# init — 建表 + migrate + admin + 空 mc_runtime_config + 向量骨架（不删已有数据）
.venv\Scripts\python.exe tools\init_platform.py init
.venv\Scripts\python.exe tools\init_platform.py init --skip-config
.venv\Scripts\python.exe tools\init_platform.py init --skip-vector

# migrate — 升级代码后仅补缺失列
.venv\Scripts\python.exe tools\init_platform.py migrate

# config — Web 运维运行时 JSON（非主库；{} 表示无在线覆盖）
.venv\Scripts\python.exe tools\init_platform.py config
.venv\Scripts\python.exe tools\init_platform.py config --force          # 清覆盖，先 .bak 备份
.venv\Scripts\python.exe tools\init_platform.py config --seed-defaults  # 写入非密钥默认值

# vector-init — 仅 RAG vectors.sqlite 表结构
.venv\Scripts\python.exe tools\init_platform.py vector-init

# clear-data — 清业务数据，保留表结构（须 --yes；默认保留 users）
.venv\Scripts\python.exe tools\init_platform.py clear-data --yes
.venv\Scripts\python.exe tools\init_platform.py clear-data --yes --drop-users

# reset — 删表重建，不清运维 JSON（须 --yes；一般用 fresh 即可）
.venv\Scripts\python.exe tools\init_platform.py reset --yes

# fresh — reset + 清 JSON + 仅 admin（开发一键重置，须 --yes）
.venv\Scripts\python.exe tools\init_platform.py fresh --yes

# migrate-data — 旧 autopilot_platform/data → data/（须 --yes）
.venv\Scripts\python.exe tools\init_platform.py migrate-data --yes
```

环境变量：`MC_DATA_DIR`、`MC_DATABASE_URL`、`MC_RUNTIME_CONFIG`、`MC_ADMIN_USER`、`MC_ADMIN_PASSWORD`（读仓库根 `.env`）。

---

## 其它脚本

| 脚本 | 用途 | 来源灵感 |
|---|---|---|
| `preflight.py` | 环境 / 依赖 / Runner 工具链体检 | 本仓原有 |
| `check_ap_version.py` | `ap` 与 `RUNTIME_PIN` 对齐 | 本仓原有 |
| `check_api_contract.py` | FastAPI 路由 ↔ 前端 `/api/v1` 调用契约 | TestPilot `check_api_contract` |
| `smoke_http.py` | 已启动服务的 HTTP 冒烟 | TestPilot `check_system` |
| `init_platform.py` | 业务库 + bootstrap admin + 运维 JSON + 向量索引：初始化 / 巡检 / 清数据 / 重置 | TestPilot `init_db` + `init_config_center` |
| `dump_ops_config.py` | 运维配置只读查看 / 导出 | TestPilot `query_config_center` |
| `batch_import_knowledge.py` | 按项目批量导入知识文件 | TestPilot `batch_import_knowledge` |
| `knowledge_admin.py` | 对已入库知识：HTTP 列表 / 检索 / 重建向量索引 / RAG 健康（需 Platform 已启动） | TestPilot `check_knowledge_base` 等 |
| `knowledge_vector_check.py` | 本地 SQLite 向量索引巡检（BLOB/FTS5）/ 与主库对照 | TestPilot `check_vector_*` |
| `gen_tls_cert.py` | keytool 生成自签 TLS 证书并导出 PEM（内网/联调） | WebAppForAndroid `generate_signature` |
| `verify_tls_chain.py` | 直连 TLS 全链路自检（证书→启动→Bootstrap→登录→IDE/Runner 路径） | — |
| `rbac_web_e2e.py` | RBAC Web 三账号 Playwright E2E（需 ``pip install -e \".[e2e]\"``） | — |

真机 / 部署后探活不在本目录：远控 live 见 `tests/live/remote_live_smoke.py`；TURN 见 `tests/test_remote_turn_optional.py`。

## 常用命令

```bash
# 环境预检
.venv/Scripts/python.exe tools/preflight.py --role platform   # 服务端（含 Node、.env 密钥）
.venv/Scripts/python.exe tools/preflight.py --role runner     # 执行节点（Appium/JDK/adb 等）
.venv/Scripts/python.exe tools/preflight.py --install-drivers # 仅缺 Appium 驱动时

# init_platform 详见上文「init_platform.py — 命令一览」

# 前后端契约（无服务）
.venv/Scripts/python.exe tools/check_api_contract.py

# 部署后冒烟（需服务已起）
.venv/Scripts/python.exe tools/smoke_http.py --smoke
.venv/Scripts/python.exe tools/smoke_http.py --module auth,projects

# 运维配置
.venv/Scripts/python.exe tools/dump_ops_config.py
.venv/Scripts/python.exe tools/dump_ops_config.py --export -o ops_export.json

# 知识库（Platform 须已启动；AP_SMOKE_* 同 smoke_http）
.venv/Scripts/python.exe tools/batch_import_knowledge.py --project-id <pid> --dir ./kb --dry-run  # 本地文件批量导入（试跑）
.venv/Scripts/python.exe tools/knowledge_admin.py --project-id <pid> list      # 分页列已入库条目
.venv/Scripts/python.exe tools/knowledge_admin.py --project-id <pid> stats     # 条目数 + rag-health（admin）
.venv/Scripts/python.exe tools/knowledge_admin.py --project-id <pid> search --query "登录"  # 混合检索试跑
.venv/Scripts/python.exe tools/knowledge_admin.py --project-id <pid> rebuild   # 全量重建向量索引（默认先清空）
.venv/Scripts/python.exe tools/knowledge_admin.py --project-id <pid> rebuild --no-clear  # 不清空再重建
.venv/Scripts/python.exe tools/knowledge_vector_check.py                       # 离线巡检 vectors.sqlite
.venv/Scripts/python.exe tools/knowledge_vector_check.py --compare-db          # 向量库 vs 主库条目对照
```

环境变量（HTTP 类 CLI 共用）：`AP_SMOKE_BASE_URL`、`AP_SMOKE_USER`、`AP_SMOKE_PASSWORD`；向量库根目录可用 `MC_DATA_DIR`。

向量索引形态（对齐 TestPilot）：`data/rag_index/vectors.sqlite` 存 float32 BLOB + FTS5；可选装 `sqlite-vec`（`pip install -e ".[design]"`）加速余弦距离。

本地 / 远程双支持（嵌入层，非远程向量库）：
- `AP_RAG_EMBEDDER=hashing`：本地离线
- `AP_RAG_EMBEDDER=openai`：远程 Embedding API（`AP_AI_BASE_URL` + Key + `AP_AI_EMBEDDING_MODEL`）
- `AP_RAG_EMBEDDER=auto`：有远程配置则走外部，否则 hashing

混合检索：`AP_RAG_HYBRID` / `AP_RAG_FTS_FACTOR` / `AP_RAG_FTS_MAX_CANDIDATES`。

# 内网 TLS 自签（keytool → PEM）
python tools/gen_tls_cert.py --cn autopilot.local --san DNS:autopilot.local --san IP:127.0.0.1 --write-env
# 直连 TLS 链路完整性自检（自动起 HTTPS 子进程探针）
python tools/verify_tls_chain.py
# 输出在 data/tls/<timestamp>/（server.crt、server.key、*.jks、*_info.txt）
# --write-env 另写 platform-tls.env（Platform 服务端）与 dev-local-ide.env（双仓联调，非分发）
# 详见 docs/setup/https.md

**刻意未移植**：Flask/Chroma/FastEmbed 专用脚本、硬编码卸载包列表、一次性 DEFAULT_COMPANY 迁移——与本栈不符。

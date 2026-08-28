# OpenAPI 契约导出（AUD-2026-11）

权威文件：`openapi.v1.json`（由 Platform 运行时生成，勿手改）。

```text
# 导出并更新仓内契约
.venv/Scripts/python.exe tools/export_openapi.py --pretty

# 校验仓内契约与现场 API 一致（CI 强制；失败须重新导出并提交）
.venv/Scripts/python.exe tools/export_openapi.py --check
```

默认同时写入 `docs/openapi.v1.json` 与本目录。  
IDE 侧 HTTP 用例导入走 `mgmt/openapi_import.py` + `contracts/mgmt_client_ops.json`，不强制镜像整份 OpenAPI。

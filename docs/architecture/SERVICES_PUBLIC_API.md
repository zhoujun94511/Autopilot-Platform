# Services 导入契约

`platform.services` 是业务编排层，不是通用工具箱。新代码必须引用领域真源模块，
禁止继续扩大顶层 facade。

## 正式公共入口

HTTP API、后台调度器和 Runner 协议当前依赖以下能力：

- `services.design`：用例、需求、文档、知识、对话与设计编排
- `services.execution.runners`：注册、心跳、清单、选择策略、Token 与作用域
- `services.execution.devices`：设备看板、维护、调度占用与冲突调和
- `services.execution.jobs`：创建、领取、生命周期、日志与超时回收
- `services.execution.schedules`：计划任务 CRUD、触发与回调
- `services.execution.resources`：资源池
- `services.remote`：设备预占、远控会话、信令与媒体命令
- `services.reports`：存储、查询、清理、证据与报告对比
- `services.observability`：AgentOps、任务质量与设备群告警
- `services.shared`：稳定、无领域编排的状态、映射、分页等公共原语

身份、租户、鉴权和运维能力不属于 services，真源分别位于
`platform.identity`、`platform.tenancy`、`platform.authz` 和 `platform.ops`。

`services.__init__` 只标识包边界，不导入或重新导出任何业务符号。调用方必须
直接引用上述领域入口或更具体的实现模块。

## 内部符号

以下类型的符号不属于公共 API：

- `_occupy_devices`、`_clear_device_busy` 等下划线函数
- `_fire_job_webhook`、`_report_snapshot` 等副作用实现
- `services.is_online` 这类历史包级别别名
- 领域模块之间通过 `services.__init__` 间接访问的函数

内部调用必须引用具体实现模块。测试 monkeypatch 同样 patch 真源路径。

旧的 `services.devices`、`services.jobs`、`services.runners` 等扁平模块已移除，
不保留兼容 shim 或双入口。

## 验收

每个领域迁移必须通过：

1. 对应领域 pytest
2. 全量 pytest
3. Pyright 闸门：`python tools/check_types.py`（仅 `autopilot_platform/platform`）。
   `ap/`、`runner/` 用 `--runtime` 另查，不作为拆包验收。
4. OpenAPI drift 检查
5. 前端 typecheck/build（若 API 或前端契约受影响）

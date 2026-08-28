"""Web 管理台 API（FastAPI + SQLAlchemy）。

包布局约定见 ``docs/architecture/PLATFORM_PACKAGE_LAYOUT.md``：
业务真源在 ``core`` / ``ops`` / ``identity`` / ``design`` / ``tenancy`` / ``authz`` /
``artifacts`` / ``ai`` / ``services`` / ``api`` / ``rag``；
根目录仅启动装配与 ``auth``。**禁止**在本包根目录新增业务模块。
"""

from .app import create_app

__all__ = ["create_app"]

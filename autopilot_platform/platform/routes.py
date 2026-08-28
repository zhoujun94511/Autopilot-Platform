"""HTTP 路由 shim：组合 ``api/`` 领域子模块，保持 ``auth_router`` / ``router`` 导出。"""

from __future__ import annotations

from .api import auth_router, router

__all__ = ["auth_router", "router"]

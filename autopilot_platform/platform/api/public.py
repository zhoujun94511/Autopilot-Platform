"""无需登录的公开接口（Bootstrap / 健康扩展）。"""

from __future__ import annotations

from fastapi import APIRouter

from ..ops.public_bootstrap import build_public_bootstrap

public_router = APIRouter(tags=["public"])


@public_router.get("/public/bootstrap")
def api_public_bootstrap() -> dict:
    """前端 / IDE 启动配置：Platform 基址、API 前缀、Runner CLI 模板（无密钥）。"""
    return build_public_bootstrap()

"""FastAPI 应用工厂。"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .core.db import init_db, reset_engine
from .core.error_handlers import register_error_handlers
from .core.logging_setup import setup_platform_logging
from .core.query_privacy import RedactSensitiveQueryMiddleware
from .core.request_context import RequestContextMiddleware
from .core.settings import (
    admin_api_token,
    allow_legacy_token_admin,
    allow_managed_runner,
    api_token,
    emit_insecure_defaults_startup_banner,
    insecure_defaults_reasons,
    is_exposed_bind_host,
    is_production,
    production_security_errors,
    require_admin_token_split,
    using_insecure_defaults,
    validate_bind_security,
    validate_production_security,
    metrics_enabled,
)
from .core.urls import default_cors_origins
from .ops.scheduler_loop import start_schedule_loop, stop_schedule_loop
from .routes import auth_router, router

# Vue(Vite) 构建产物：autopilot_platform/frontend/dist（npm run build）
_FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
_DIST_DIR = _FRONTEND_DIR / "dist"
_PUBLIC_DIR = _FRONTEND_DIR / "public"
# hashed /assets 可长期缓存；index.html 必须每次向服务器确认，否则会钉死旧 chunk。
_SPA_HTML_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
}
_SPA_SKIP_PREFIXES = (
    "api",
    "health",
    "metrics",
    "assets",
    "brand",
    "docs",
    "openapi",
    "openapi.json",
    "redoc",
    "favicon.ico",
)


def _resolve_brand_dir() -> Path | None:
    """Vite 会把 public/brand 复制到 dist/brand；未 build 时回退 public/brand。"""
    for candidate in (_DIST_DIR / "brand", _PUBLIC_DIR / "brand"):
        if (candidate / "autopilot.png").is_file():
            return candidate
    return None


def _resolve_favicon() -> Path | None:
    for candidate in (_DIST_DIR / "favicon.ico", _PUBLIC_DIR / "favicon.ico"):
        if candidate.is_file():
            return candidate
    return None


def _frontend_dev_url() -> str:
    """``start_dev.py`` 设置后，:8000 根路径转到 Vite，避免再托管过期 dist。"""
    if is_production():
        return ""
    return (os.environ.get("MC_FRONTEND_DEV_URL") or "").strip().rstrip("/")


def _redirect_to_dev_frontend(dev: str, request: Request, extra_path: str = "") -> RedirectResponse:
    path = "/" + (extra_path or "").lstrip("/")
    if path == "/":
        target = dev + "/"
    else:
        target = f"{dev}{path}"
    qs = request.url.query
    if qs:
        target = f"{target}?{qs}"
    return RedirectResponse(target, status_code=307, headers=_SPA_HTML_HEADERS)


def _mount_frontend_static(app: FastAPI) -> None:
    """挂载 Vite public 静态资源（/brand、/favicon.ico），与 /assets 分离。

    根因：FastAPI 同源 :8000 只挂了 hashed /assets，从未暴露 public/brand；
    Vite dev :5173 会自动提供 public/，因此仅直连后端时 404。

    联调（``MC_FRONTEND_DEV_URL``）：不挂 dist，把 SPA 重定向到 Vite，
    与 IDE / 浏览器同一套热更新前端，避免 hashed CSS 404。
    """
    brand = _resolve_brand_dir()
    if brand is not None:
        app.mount("/brand", StaticFiles(directory=str(brand)), name="brand")

    favicon = _resolve_favicon()
    if favicon is not None:

        @app.get("/favicon.ico", include_in_schema=False)
        def spa_favicon() -> FileResponse:
            return FileResponse(favicon)

    dev = _frontend_dev_url()
    if dev:

        @app.get("/", include_in_schema=False)
        def spa_dev_index(request: Request) -> RedirectResponse:
            return _redirect_to_dev_frontend(dev, request)

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_dev_fallback(full_path: str, request: Request) -> RedirectResponse:
            """联调：非 API 路径转到 Vite（AUD-P2-009 深链仍可用）。"""
            head = (full_path or "").split("/", 1)[0]
            if head in _SPA_SKIP_PREFIXES:
                raise HTTPException(status_code=404, detail="Not Found")
            return _redirect_to_dev_frontend(dev, request, full_path)

        return

    if _DIST_DIR.is_dir() and (_DIST_DIR / "index.html").is_file():
        assets = _DIST_DIR / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/", include_in_schema=False)
        def spa_index() -> FileResponse:
            return FileResponse(
                _DIST_DIR / "index.html",
                headers=_SPA_HTML_HEADERS,
            )

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str) -> FileResponse:
            """History 模式深链刷新：非 API 路径回退到 index.html（AUD-P2-009）。"""
            head = (full_path or "").split("/", 1)[0]
            if head in _SPA_SKIP_PREFIXES:
                raise HTTPException(status_code=404, detail="Not Found")
            return FileResponse(
                _DIST_DIR / "index.html",
                headers=_SPA_HTML_HEADERS,
            )


def _cors_origins() -> list[str]:
    raw = os.environ.get("MC_CORS_ORIGINS", "").strip()
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    return default_cors_origins()


def _log_ai_budget_health(log) -> None:
    """AI 开启但无预算约束时给出可见告警：生产按 error，其他按 warning。"""
    from .ai.ai_config import ai_enabled  # 延迟：避免应用工厂拉起 LLM 栈
    from .ai.ai_usage import budget_config_warnings
    if not ai_enabled():
        return
    warns = budget_config_warnings()
    if not warns:
        return
    level = log.error if is_production() else log.warning
    for msg in warns:
        level("AI TOKEN BUDGET: %s", msg)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    log = logging.getLogger("autopilot_platform.platform")
    if using_insecure_defaults():
        # AUD-2026-06：stderr 横幅 + 日志（硬门禁仍由 validate_* 负责）
        emit_insecure_defaults_startup_banner()
        errs = production_security_errors()
        reasons = insecure_defaults_reasons()
        detail = "; ".join(reasons or errs) if (reasons or errs) else "default credentials"
        level = log.error if is_production() else log.warning
        level(
            "INSECURE DEFAULTS in use (%s). "
            "Set strong MC_API_TOKEN / MC_JWT_SECRET / MC_ADMIN_PASSWORD before "
            "exposing Platform beyond localhost. See deploy/production.env.example.",
            detail,
        )
    admin_tok = admin_api_token()
    if not admin_tok:
        if allow_legacy_token_admin():
            msg = (
                "MC_ADMIN_API_TOKEN unset + MC_ALLOW_LEGACY_TOKEN_ADMIN=1: "
                "global MC_API_TOKEN acts as admin (migration only; prefer split tokens)."
            )
        else:
            msg = (
                "MC_ADMIN_API_TOKEN unset: global MC_API_TOKEN is runner-only "
                "(set MC_ADMIN_API_TOKEN for ops, or MC_ALLOW_LEGACY_TOKEN_ADMIN=1 for legacy)."
            )
        if require_admin_token_split():
            log.error(
                "PRODUCTION / MC_REQUIRE_ADMIN_API_TOKEN: %s "
                "Runner must use MC_API_TOKEN or per-runner token; do not share admin token.",
                msg,
            )
        else:
            log.info(msg)
    elif admin_tok == api_token():
        log.warning(
            "MC_ADMIN_API_TOKEN equals MC_API_TOKEN — token split is ineffective; "
            "use distinct values so Runner cannot elevate to platform admin."
        )
    _log_ai_budget_health(log)
    try:
        from .core.db import session_factory
        from .services.execution.fleet_startup import reset_fleet_liveness_on_startup

        factory = session_factory()
        if factory is not None:
            with factory() as db:
                stats = reset_fleet_liveness_on_startup(db)
                if stats.get("runners_cleared"):
                    log.info(
                        "Fleet liveness reset on startup: %s runner(s) awaiting heartbeat",
                        stats["runners_cleared"],
                    )
    except (OSError, RuntimeError, ValueError, TypeError, ImportError) as exc:
        log.warning("Fleet liveness reset skipped: %s", exc)
    if allow_managed_runner() and is_production():
        log.warning(
            "MC_ALLOW_MANAGED_RUNNER enabled in production on loopback: Platform can "
            "spawn a local Runner subprocess. Prefer dedicated Runner hosts with "
            "CLI/service when the UI is remote."
        )
    elif (
        os.environ.get("MC_ALLOW_MANAGED_RUNNER", "").strip().lower()
        in ("1", "true", "yes", "on")
        and is_exposed_bind_host()
    ):
        log.warning(
            "MC_ALLOW_MANAGED_RUNNER=1 ignored: non-loopback bind "
            "(MC_HOST / --lan) forbids Web-managed Runner spawn."
        )
    start_schedule_loop()
    try:
        yield
    finally:
        stop_schedule_loop()
        try:
            from .services.execution.runners.managed import get_managed_runner_manager  # 延迟：仅关闭托管 Runner

            get_managed_runner_manager().shutdown()
        except (OSError, RuntimeError, ValueError, TypeError, AttributeError, ImportError):
            pass


def create_app(*, database_url: str | None = None) -> FastAPI:
    try:
        from .core.env_file import load_project_dotenv  # 延迟：可选 .env

        load_project_dotenv(Path(__file__).resolve().parents[2])
    except (ImportError, OSError, ValueError, TypeError):
        pass
    setup_platform_logging()
    """创建应用；测试可传入 sqlite:///:memory: 或临时文件 URL。"""
    validate_production_security()
    validate_bind_security()
    if database_url is not None:
        reset_engine()
        init_db(database_url)
    else:
        init_db()

    app = FastAPI(
        title="AutoPilot Platform",
        description=(
            "统一测试平台 API：测试设计（需求/逻辑用例/知识）"
            " + 执行治理（设备池/制品/批跑/报告）。非 Web IDE。"
        ),
        version="0.2.0",
        lifespan=_lifespan,
        docs_url=None if is_production() else "/docs",
        redoc_url=None if is_production() else "/redoc",
        openapi_url=None if is_production() else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # 后添加的中间件更靠外；在 access log 写出前脱敏 ?access_token=
    app.add_middleware(RedactSensitiveQueryMiddleware)
    app.add_middleware(RequestContextMiddleware)

    register_error_handlers(app)

    @app.get("/health")
    def health() -> dict:
        from .services.shared.platform_boot import PLATFORM_BOOT_ID

        return {
            "status": "ok",
            "service": "autopilot_platform.platform",
            "platform_boot_id": PLATFORM_BOOT_ID,
        }

    @app.get("/health/turn")
    def health_turn() -> dict:
        from .ops.turn_health import check_turn_health  # 延迟：TURN 健康检查可选

        return check_turn_health()

    @app.get("/metrics")
    def metrics(request: Request) -> PlainTextResponse:
        from .core.db import session_factory
        from .core.metrics import collect_text

        if not metrics_enabled():
            return PlainTextResponse("metrics disabled\n", status_code=404)
        # 默认同源本机可匿名抓取；非本机须带运维/JWT/API Token。
        # 仅认 TCP/ASGI peer，忽略 X-Forwarded-For（AUD-P2-008）。
        from .core.metrics_access import metrics_peer_is_local

        if not metrics_peer_is_local(request):
            auth_hdr = request.headers.get("authorization") or ""
            api_tok = request.headers.get("x-api-token") or ""
            from .auth import _token_match

            ok = False
            if api_tok and (
                _token_match(api_tok, admin_api_token())
                or _token_match(api_tok, api_token())
            ):
                ok = True
            elif auth_hdr.lower().startswith("bearer "):
                # noinspection PyPackageRequirements
                from jwt import PyJWTError  # 延迟：仅非本机抓 metrics 时校验 JWT

                try:
                    from .core.security import decode_access_token

                    payload = decode_access_token(auth_hdr[7:].strip())
                    ok = (
                        payload.get("typ") == "access"
                        and (payload.get("role") or "") == "admin"
                    )
                except PyJWTError:
                    ok = False
            if not ok:
                return PlainTextResponse("metrics auth required\n", status_code=401)
        factory = session_factory()
        db = factory() if factory is not None else None
        try:
            text = collect_text(db)
        finally:
            if db is not None:
                db.close()
        return PlainTextResponse(text, media_type="text/plain; version=0.0.4; charset=utf-8")

    app.include_router(auth_router)
    app.include_router(router)

    _mount_frontend_static(app)

    return app

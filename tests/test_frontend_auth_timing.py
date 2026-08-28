"""前端鉴权时序相关契约：防止 design Tab 误打 dashboard 全量 API、access 过期判定回归。"""

from __future__ import annotations

import base64
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCOPES_TS = os.path.join(
    ROOT, "autopilot_platform", "frontend", "src", "composables", "mcRefreshScopes.ts"
)
API_TS = os.path.join(ROOT, "autopilot_platform", "frontend", "src", "api.ts")


def test_design_tabs_do_not_fallback_to_dashboard_scopes():
    src = open(SCOPES_TS, encoding="utf-8").read()
    # 旧缺陷：TAB_SCOPES[tab] || TAB_SCOPES.dashboard 会让 design-* 打 runners/devices/jobs/ops
    assert "TAB_SCOPES[tab as McTabId] || TAB_SCOPES.dashboard" not in src
    assert '"design-dashboard": []' in src
    assert 'tab.startsWith("design-")' in src
    assert "scopesForTab" in src
    assert "overlayBusy" in src


def test_api_proactive_refresh_and_session_sync_hooks_present():
    src = open(API_TS, encoding="utf-8").read()
    assert "export async function ensureFreshSession" in src
    assert "export function accessTokenNeedsRefresh" in src
    assert "export function bindSessionChange" in src
    assert "export function beginAuthSession" in src
    assert "accessTokenNeedsRefresh(loadJwt())" in src
    assert "emitSessionChange" in src
    assert "refreshEpoch" in src
    # 失败清会话须绑定本次 refresh，避免冲掉新登录
    assert "loadRefresh() === rt" in src
    # finally 不得无条件清空单飞句柄（会误伤后续 refresh）
    assert "if (refreshInFlight === p)" in src
    # AUD-2026-02 Phase B：access 仅内存，禁止再写入 mc_jwt
    assert "accessTokenMem" in src
    assert 'localStorage.setItem(JWT_KEY' not in src
    assert "migrateLegacyAccessToken" in src
    # AUD-2026-20：前端不得再导出/硬编码默认 Runner Token
    assert "loadRunnerToken" in src
    assert "DEFAULT_RUNNER_TOKEN" not in src
    assert "dev-mc-token" not in src
    assert "|| DEFAULT_RUNNER_TOKEN" not in src
    assert "getItem(RUNNER_TOKEN_KEY)" in src
    assert "AUD-2026-20" in src
    # AUD-2026-02 Phase C：refresh 走 HttpOnly Cookie，禁止再写入 mc_refresh
    assert "noteRefreshCookieActive" in src
    assert "hasRefreshSession" in src
    assert "hasDurableSessionHint" in src
    assert 'SESSION_HINT_KEY = "mc_session"' in src
    assert "persistSessionHint" in src
    assert "credentials: \"include\"" in src or "credentials: 'include'" in src
    assert 'localStorage.setItem(REFRESH_KEY' not in src
    assert "migrateLegacyRefreshToken" in src
    # F5 后内存旗标丢失，须凭 hint/mc_user 探测 Cookie，且 cookie 换票 401 要清会话
    assert "hasDurableSessionHint()" in src
    assert 'rt ? loadRefresh() === rt : true' in src

def test_apply_auth_session_begins_new_epoch():
    store = open(
        os.path.join(
            ROOT,
            "autopilot_platform",
            "frontend",
            "src",
            "composables",
            "mcSessionActions.ts",
        ),
        encoding="utf-8",
    ).read()
    assert "beginAuthSession" in store
    apply = re.search(r"export async function applyAuthSession\([\s\S]*?\n}", store)
    assert apply, "applyAuthSession not found"
    body = apply.group(0)
    assert "beginAuthSession" in body
    assert body.index("beginAuthSession") < body.index("saveJwt")


def _b64url(obj: dict) -> str:
    raw = json.dumps(obj, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _fake_jwt(payload: dict) -> str:
    return f"hdr.{_b64url(payload)}.sig"


def test_access_token_needs_refresh_logic_mirrors_frontend():
    """与 api.ts accessTokenNeedsRefresh 同算法的纯 Python 对照（无 DOM）。"""

    def needs_refresh(token: str, skew_seconds: int = 60, now_ms: int = 0) -> bool:
        raw = (token or "").strip()
        if not raw:
            return True
        try:
            part = raw.split(".")[1]
            if not part:
                return True
            pad = part + "=" * ((4 - (len(part) % 4)) % 4)
            payload = json.loads(base64.urlsafe_b64decode(pad.encode()))
            if payload.get("typ") != "access":
                return True
            exp = payload.get("exp")
            if not isinstance(exp, (int, float)):
                return True
            return exp <= (now_ms / 1000) + skew_seconds
        except (json.JSONDecodeError, TypeError, ValueError, UnicodeDecodeError):
            return True

    now = 1_700_000_000_000
    fresh = _fake_jwt({"typ": "access", "exp": now // 1000 + 3600})
    assert needs_refresh(fresh, now_ms=now) is False

    soon = _fake_jwt({"typ": "access", "exp": now // 1000 + 30})
    assert needs_refresh(soon, skew_seconds=60, now_ms=now) is True

    expired = _fake_jwt({"typ": "access", "exp": now // 1000 - 10})
    assert needs_refresh(expired, now_ms=now) is True

    # AP-06：stream / 缺 typ 不得当业务 access
    stream = _fake_jwt({"typ": "job_log_stream", "exp": now // 1000 + 3600})
    assert needs_refresh(stream, now_ms=now) is True
    legacy = _fake_jwt({"exp": now // 1000 + 3600})
    assert needs_refresh(legacy, now_ms=now) is True


def test_use_mc_store_bootstrap_awaits_ensure_fresh_session():
    store = open(
        os.path.join(
            ROOT,
            "autopilot_platform",
            "frontend",
            "src",
            "composables",
            "mcSessionActions.ts",
        ),
        encoding="utf-8",
    ).read()
    assert "ensureFreshSession" in store
    # bootstrap 须先换票再 refreshForTab
    boot = re.search(r"export async function bootstrap\(\) \{.*?^}", store, re.M | re.S)
    assert boot, "bootstrap() not found"
    body = boot.group(0)
    assert "ensureFreshSession" in body
    assert "sessionHydrating" in body
    assert body.index("ensureFreshSession") < body.index("refreshForTab")

"""阶段 C：登录限速、metrics 本机策略等。"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine
from autopilot_platform.platform.core.login_rate import (
    MAX_FAILURES,
    reset_for_tests,
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "mc_c.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "rt.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "logs"))
    reset_engine()
    reset_for_tests()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=url)
    with TestClient(app) as c:
        yield c
    reset_engine()
    reload_runtime_config()
    reset_for_tests()


def test_login_rate_limit(client: TestClient):
    for _ in range(MAX_FAILURES):
        r = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong-pass"},
        )
        assert r.status_code == 401
    r = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong-pass"},
    )
    assert r.status_code == 429
    # 正确密码在锁定期间仍拒绝（同 key）
    r = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    assert r.status_code == 429


def test_oidc_redirect_uses_fragment():
    from autopilot_platform.core.schemas import TokenOut, UserOut
    import autopilot_platform.platform.identity.oidc as oidc_svc
    from datetime import datetime, timezone

    tok = TokenOut(
        access_token="jwt.tok.en",
        user=UserOut(
            id="u1",
            username="alice",
            role="operator",
            created_at=datetime.now(timezone.utc),
        ),
    )
    url = oidc_svc.frontend_success_redirect(tok)
    assert "#" in url
    assert "access_token=" in url.split("#", 1)[1]
    assert "?" not in url.split("#", 1)[0] or "access_token" not in url.split("#", 1)[0]


def test_metrics_local_ok(client: TestClient):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "mc_jobs" in r.text

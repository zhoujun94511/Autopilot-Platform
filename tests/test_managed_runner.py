"""本机托管 Runner：权限隔离与启停（mock subprocess）。"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from list_page_helpers import page_items

from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine
from autopilot_platform.platform.services.execution.runners.managed import (
    reset_managed_runner_manager_for_tests,
)
from autopilot_platform.platform.core.settings import allow_managed_runner


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "managed_runner.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_APP_BUILDS_DIR", str(tmp_path / "app_builds"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_API_TOKEN", "runner-global-token")
    monkeypatch.setenv("MC_ADMIN_API_TOKEN", "admin-ops-token")
    monkeypatch.setenv("MC_ALLOW_MANAGED_RUNNER", "1")
    monkeypatch.setenv("MC_HOST", "127.0.0.1")
    monkeypatch.delenv("MC_ENV", raising=False)
    monkeypatch.delenv("MC_REQUIRE_ADMIN_API_TOKEN", raising=False)
    reset_engine()
    reset_managed_runner_manager_for_tests()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=url)
    with TestClient(app) as c:
        yield c
    reset_managed_runner_manager_for_tests()
    reset_engine()
    reload_runtime_config()


def _admin_headers(client: TestClient) -> dict:
    login = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    return {"Authorization": f"Bearer {login['access_token']}"}


def _operator_headers(client: TestClient, ah: dict) -> dict:
    r = client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "op-mrun", "password": "Opuser12", "duty": "user"},
    )
    assert r.status_code == 200, r.text
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "op-mrun", "password": "Opuser12"},
    ).json()
    return {"Authorization": f"Bearer {login['access_token']}"}


class _FakeStdout:
    def __iter__(self):
        return iter(())

    @staticmethod
    def close():
        return None


class _FakeProc:
    def __init__(self):
        self.pid = 4242
        self._code = None
        self.stdout = _FakeStdout()

    def poll(self):
        return self._code

    def terminate(self):
        self._code = 0

    def kill(self):
        self._code = -9


def test_allow_managed_runner_defaults(monkeypatch):
    monkeypatch.setenv("MC_HOST", "127.0.0.1")
    monkeypatch.delenv("MC_ALLOW_MANAGED_RUNNER", raising=False)
    monkeypatch.delenv("MC_ENV", raising=False)
    # 未设置 → 默认拒绝（不再因非 production 自动开启）
    assert allow_managed_runner() is False
    monkeypatch.setenv("MC_ENV", "production")
    assert allow_managed_runner() is False
    monkeypatch.delenv("MC_ENV", raising=False)
    monkeypatch.setenv("MC_ALLOW_MANAGED_RUNNER", "1")
    assert allow_managed_runner() is True
    monkeypatch.setenv("MC_ALLOW_MANAGED_RUNNER", "0")
    assert allow_managed_runner() is False


def test_allow_managed_runner_exposed_bind_denied(monkeypatch):
    monkeypatch.setenv("MC_ALLOW_MANAGED_RUNNER", "1")
    monkeypatch.delenv("MC_ENV", raising=False)
    monkeypatch.setenv("MC_HOST", "0.0.0.0")
    assert allow_managed_runner() is False
    monkeypatch.setenv("MC_HOST", "192.168.1.10")
    assert allow_managed_runner() is False
    monkeypatch.setenv("MC_HOST", "127.0.0.1")
    assert allow_managed_runner() is True


def test_managed_runner_operator_forbidden(client: TestClient):
    ah = _admin_headers(client)
    oh = _operator_headers(client, ah)
    assert client.get("/api/v1/runners/managed", headers=oh).status_code == 403
    assert client.get("/api/v1/runners/managed/logs", headers=oh).status_code == 403
    assert client.post("/api/v1/runners/managed/start", headers=oh).status_code == 403
    assert client.post("/api/v1/runners/managed/stop", headers=oh).status_code == 403


def test_managed_runner_runner_token_forbidden(client: TestClient):
    h = {"X-API-Token": "runner-global-token"}
    assert client.get("/api/v1/runners/managed", headers=h).status_code == 403
    assert client.post("/api/v1/runners/managed/start", headers=h).status_code == 403


def test_managed_runner_disabled_flag(client: TestClient, monkeypatch):
    monkeypatch.setenv("MC_ALLOW_MANAGED_RUNNER", "0")
    ah = _admin_headers(client)
    st = client.get("/api/v1/runners/managed", headers=ah)
    assert st.status_code == 200
    assert st.json()["enabled"] is False
    r = client.post("/api/v1/runners/managed/start", headers=ah)
    assert r.status_code == 403
    payload = r.json()
    text = str(payload.get("message") or payload.get("detail") or "")
    assert "MC_ALLOW_MANAGED_RUNNER" in text


def test_managed_runner_exposed_bind_start_forbidden(client: TestClient, monkeypatch):
    monkeypatch.setenv("MC_ALLOW_MANAGED_RUNNER", "1")
    monkeypatch.setenv("MC_HOST", "0.0.0.0")
    ah = _admin_headers(client)
    st = client.get("/api/v1/runners/managed", headers=ah)
    assert st.status_code == 200
    assert st.json()["enabled"] is False
    r = client.post("/api/v1/runners/managed/start", headers=ah)
    assert r.status_code == 403
    payload = r.json()
    text = str(payload.get("message") or payload.get("detail") or "")
    assert "loopback" in text.lower() or "0.0.0.0" in text or "lan" in text.lower()

def test_managed_runner_admin_start_stop(client: TestClient, monkeypatch):
    ah = _admin_headers(client)
    mgr = reset_managed_runner_manager_for_tests()
    fake = _FakeProc()

    st0 = client.get("/api/v1/runners/managed", headers=ah)
    assert st0.status_code == 200
    body0 = st0.json()
    assert body0["enabled"] is True
    assert body0["running"] is False
    assert "python -m autopilot_platform.runner" in body0["cli_command"]
    assert "--token-env MC_RUNNER_TOKEN" in body0["cli_command"]
    assert "runner-global-token" not in body0["cli_command"]
    assert "admin-ops-token" not in body0["cli_command"]
    assert "dev-mc-token" not in body0["cli_command"]

    # 注入 mock popen
    captured: dict = {}

    def _fake_popen(*_a, **_k):
        captured["args"] = _a
        captured["kwargs"] = _k
        return fake

    monkeypatch.setattr(
        "autopilot_platform.platform.services.execution.runners.managed.subprocess.Popen",
        _fake_popen,
    )

    started = client.post("/api/v1/runners/managed/start", headers=ah)
    assert started.status_code == 200, started.text
    data = started.json()
    assert data["running"] is True
    assert data["pid"] == 4242
    assert data["runner_id"] == "managed-local"
    assert data["managed"] is True
    assert data.get("log_file")
    assert "managed-runner.log" in data["log_file"]
    assert "--token-env MC_RUNNER_TOKEN" in data["cli_command"]
    assert "runner-global-token" not in data["cli_command"]
    # 启停响应与日志不得回显真实 token
    blob = started.text + "\n".join(data.get("log_tail") or [])
    assert "runner-global-token" not in blob
    assert "admin-ops-token" not in blob
    # argv 不含 --token；凭据仅经 env（Popen(cmd, **kwargs)）
    popen_argv = list(captured["args"][0]) if captured.get("args") else []
    assert "--token" not in popen_argv
    env = (captured.get("kwargs") or {}).get("env") or {}
    assert env.get("MC_API_TOKEN")
    assert env.get("MC_API_TOKEN") != "runner-global-token"
    assert env.get("MC_API_TOKEN") != "admin-ops-token"

    # 重复启动 → 409
    again = client.post("/api/v1/runners/managed/start", headers=ah)
    assert again.status_code == 409

    logs = client.get("/api/v1/runners/managed/logs", headers=ah)
    assert logs.status_code == 200
    assert logs.json()["running"] is True
    assert logs.json().get("log_file")

    stopped = client.post("/api/v1/runners/managed/stop", headers=ah)
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["running"] is False

    # 未运行再停 → 409
    stop2 = client.post("/api/v1/runners/managed/stop", headers=ah)
    assert stop2.status_code == 409

    # 确认 runner 行已注册且有 token
    runners = page_items(client.get("/api/v1/runners", headers=ah).json())
    row = next(r for r in runners if r["runner_id"] == "managed-local")
    assert row["has_token"] is True

    # 清理：避免 fixture teardown 再碰假进程
    mgr._proc = None

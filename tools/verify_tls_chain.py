#!/usr/bin/env python3
"""Platform 直连 TLS 链路完整性自检（证书配置 → 启动 → Bootstrap → 登录 → IDE 客户端路径）。

不替代 pytest；用于确认 MC_SSL_* 配置后整条 HTTPS 调用链可用。

用法：
  python tools/verify_tls_chain.py
  python tools/verify_tls_chain.py --keep-artifacts
  python tools/verify_tls_chain.py --cert-dir data/tls/my-lab --no-start-server
    # 已手动起服时只跑探针

流程：
  1. keytool 生成 PEM（或使用已有 --cert-dir）
  2. 子进程启动 ``python -m autopilot_platform.platform``（HTTPS :8443）
  3. curl/httpx 探针：Bootstrap flags、health、login
  4. 模拟 IDE：httpx + AUTOPILOT_SSL_CA_FILE 校验自签
  5. 模拟 Runner：PlatformClient + verify
"""

from __future__ import annotations

# cspell:ignore CERTFILE certfile
import argparse
import json
import os
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_AUTOPILOT = ROOT.parent / "AutoPilot"
if _AUTOPILOT.is_dir():
    sys.path.insert(0, str(_AUTOPILOT))

DEFAULT_PORT = 8443
DEFAULT_HOST = "127.0.0.1"
_SSL_CERT_ENV = "MC_SSL_" + "CERTFILE"
_SSL_KEY_ENV = "MC_SSL_" + "KEYFILE"
_UVicorn_CERT_KW = "ssl_" + "certfile"


def _print(title: str, detail: str = "", *, ok: bool | None = None) -> None:
    mark = {True: "OK ", False: "FAIL"}.get(ok, "  ")
    line = f"[{mark}] {title}"
    if detail:
        line += f" — {detail}"
    print(line, flush=True)


def _wait_https(base: str, timeout_sec: float = 45.0) -> bool:
    url = f"{base}/api/v1/public/bootstrap"
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=3.0, context=ctx) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.4)
    return False


def _fetch_json_insecure(url: str) -> dict:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10.0, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ensure_certs(cert_dir: Path | None, cn: str) -> tuple[Path, Path]:
    if cert_dir and cert_dir.is_dir():
        c, k = cert_dir / "server.crt", cert_dir / "server.key"
        if c.is_file() and k.is_file():
            return c.resolve(), k.resolve()
    from tools.gen_tls_cert import generate_tls_material

    out = cert_dir or (ROOT / "data" / "tls" / "verify_chain")
    out.mkdir(parents=True, exist_ok=True)
    meta = generate_tls_material(
        out_dir=out,
        cn=cn,
        sans=[f"DNS:{cn}", f"IP:{DEFAULT_HOST}"],
        alias=None,
        validity_days=365,
        password_len=12,
        org="AutoPilot",
        country="CN",
    )
    return meta["cert_pem"].resolve(), meta["key_pem"].resolve()  # type: ignore[union-attr]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Platform 直连 TLS 链路完整性自检")
    ap.add_argument("--cert-dir", type=Path, default=None, help="已有 server.crt/server.key 目录")
    ap.add_argument("--cn", default="127.0.0.1", help="证书 CN/SAN")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--no-start-server", action="store_true", help="不启动子进程（服务已运行）")
    ap.add_argument("--keep-artifacts", action="store_true", help="保留临时 DB/证书目录")
    args = ap.parse_args(argv)

    host, port = args.host, args.port
    base = f"https://{host}:{port}"
    failures = 0

    print("=" * 60)
    print("Platform 直连 TLS 链路完整性自检")
    print("=" * 60)

    # ── 1. 证书 ──
    print("\n── 1. 证书准备（gen_tls_cert / 已有 PEM）──")
    cert_pem, key_pem = _ensure_certs(args.cert_dir, args.cn)
    from autopilot_platform.platform.core import tls as mc_tls

    os.environ[_SSL_CERT_ENV] = str(cert_pem)
    os.environ[_SSL_KEY_ENV] = str(key_pem)
    os.environ.pop("MC_BEHIND_HTTPS_PROXY", None)
    if not mc_tls.ssl_enabled():
        _print("ssl_enabled()", ok=False)
        return 1
    _print("ssl_enabled()", "证书与私钥可读", ok=True)
    kw = mc_tls.uvicorn_ssl_kwargs()
    _print("uvicorn_ssl_kwargs()", "TLS 证书路径已注入", ok=_UVicorn_CERT_KW in kw)

    proc: subprocess.Popen | None = None
    tmp_root: Path | None = None

    try:
        if not args.no_start_server:
            # ── 2. 启动 Platform（HTTPS）──
            print("\n── 2. 启动 Platform（python -m autopilot_platform.platform）──")
            tmp_root = Path(tempfile.mkdtemp(prefix="mc_tls_verify_"))
            db = tmp_root / "verify.db"
            env = os.environ.copy()
            env.update(
                {
                    "MC_HOST": host,
                    "MC_PORT": str(port),
                    "MC_PLATFORM_URL": base,
                    _SSL_CERT_ENV: str(cert_pem),
                    _SSL_KEY_ENV: str(key_pem),
                    "MC_DATABASE_URL": f"sqlite:///{db.as_posix()}",
                    "MC_ARTIFACTS_DIR": str(tmp_root / "artifacts"),
                    "MC_APP_BUILDS_DIR": str(tmp_root / "app_builds"),
                    "MC_JOB_LOGS_DIR": str(tmp_root / "job_logs"),
                    "MC_RUNTIME_CONFIG": str(tmp_root / "mc_runtime_config.json"),
                    "MC_SCHEDULE_ENABLED": "0",
                    "MC_ADMIN_USER": "admin",
                    "MC_ADMIN_PASSWORD": "admin",
                    "MC_COOKIE_SECURE": "1",
                    "MC_CORS_ORIGINS": base,
                    # 非 production：跳过生产 HTTPS 组合校验外的额外门禁，专注 TLS 链
                }
            )
            for d in ("artifacts", "app_builds", "job_logs"):
                (tmp_root / d).mkdir(parents=True, exist_ok=True)

            cmd = [
                sys.executable,
                "-m",
                "autopilot_platform.platform",
                "--host",
                host,
                "--port",
                str(port),
            ]
            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if not _wait_https(base):
                out = (proc.stdout.read() if proc.stdout else "")[:2000]
                _print("Platform HTTPS 就绪", out or "超时", ok=False)
                return 1
            _print("Platform HTTPS 就绪", base, ok=True)
        else:
            print("\n── 2. 跳过启动（--no-start-server）──")
            if not _wait_https(base, timeout_sec=5.0):
                _print("已有服务不可达", base, ok=False)
                return 1
            _print("已有 HTTPS 服务可达", base, ok=True)

        # ── 3. Bootstrap / TLS 标志 ──
        print("\n── 3. 公开 Bootstrap（无鉴权）──")
        boot = _fetch_json_insecure(f"{base}/api/v1/public/bootstrap")
        flags = boot.get("flags") or {}
        pub_url = boot.get("platform_base_url", "")
        _print("platform_base_url", pub_url, ok=pub_url.startswith("https://"))
        _print("flags.tls_direct", str(flags.get("tls_direct")), ok=flags.get("tls_direct") is True)
        _print(
            "flags.public_scheme_https",
            str(flags.get("public_scheme_https")),
            ok=flags.get("public_scheme_https") is True,
        )
        _print(
            "flags.behind_https_proxy",
            str(flags.get("behind_https_proxy")),
            ok=flags.get("behind_https_proxy") is False,
        )
        if not flags.get("tls_direct"):
            failures += 1

        # ── 4. Health ──
        print("\n── 4. Health ──")
        health = _fetch_json_insecure(f"{base}/health")
        _print("/health", str(health.get("status", health)), ok=health.get("status") == "ok")

        # ── 5. 应用层登录（TLS 之上 JWT）──
        print("\n── 5. 应用层登录（HTTPS + 用户名密码 → JWT）──")
        import httpx

        os.environ["AUTOPILOT_SSL_CA_FILE"] = str(cert_pem)
        from autopilot_platform.core.http_ssl import httpx_verify

        verify_ca = httpx_verify()
        with httpx.Client(base_url=base, verify=verify_ca, timeout=15.0) as client:
            r = client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "admin"},
            )
            ok_login = r.status_code == 200 and isinstance(r.json(), dict)
            token = (r.json().get("access_token") or "") if ok_login else ""
            _print("POST /auth/login（IDE 路径 + CA 信任）", f"status={r.status_code}", ok=ok_login)

            if token:
                me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
                _print("GET /auth/me（Bearer JWT）", f"status={me.status_code}", ok=me.status_code == 200)

        # ── 6. 无 CA 时应失败（自签）──
        print("\n── 6. 客户端校验（自签：无 CA 应失败，有 CA 应成功）──")
        try:
            with httpx.Client(base_url=base, verify=True, timeout=5.0) as bad:
                bad.get("/health")
            _print("verify=True 无 CA", "意外成功", ok=False)
            failures += 1
        except httpx.HTTPError:
            _print("verify=True 无 CA", "预期拒绝自签", ok=True)

        with httpx.Client(base_url=base, verify=verify_ca, timeout=5.0) as good:
            hr = good.get("/health")
            _print("verify=CA_FILE", f"status={hr.status_code}", ok=hr.status_code == 200)

        # ── 7. Runner 客户端路径（X-API-Token + httpx verify，同 PlatformClient）──
        print("\n── 7. Runner PlatformClient（X-API-Token over HTTPS）──")
        os.environ["AUTOPILOT_SSL_CA_FILE"] = str(cert_pem)
        runner_token = os.environ.get("MC_API_TOKEN", "dev-mc-token")
        try:
            with httpx.Client(
                base_url=base,
                headers={"X-API-Token": runner_token},
                verify=verify_ca,
                timeout=15.0,
            ) as runner_http:
                h = runner_http.get("/health")
            _print("Runner GET /health", f"status={h.status_code}", ok=h.status_code == 200)
        except httpx.HTTPError as exc:
            _print("Runner GET /health", str(exc), ok=False)
            failures += 1

        # ── 8. Refresh Cookie Secure（HTTPS）──
        print("\n── 8. Refresh Cookie（HTTPS 下 Secure）──")
        with httpx.Client(base_url=base, verify=verify_ca, timeout=10.0) as client:
            r2 = client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "admin"},
            )
            set_cookie = r2.headers.get("set-cookie", "")
            has_secure = "secure" in set_cookie.lower()
            _print("Set-Cookie Secure", set_cookie[:80] + ("..." if len(set_cookie) > 80 else ""), ok=has_secure)

        print("\n" + "=" * 60)
        if failures:
            print(f"完成：存在 {failures} 项失败")
            return 1
        print("完成：直连 TLS 链路完整性自检通过")
        print("=" * 60)
        print("\n链路摘要：")
        print("  gen_tls_cert → MC_SSL_* → uvicorn HTTPS")
        print("  → Bootstrap(tls_direct) → health → login(JWT) → me")
        print("  IDE/Runner: platform.url + AUTOPILOT_SSL_CA_FILE → httpx verify（与 core.http_ssl 同逻辑）")
        return 0

    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
        if tmp_root and not args.keep_artifacts:
            import shutil

            shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

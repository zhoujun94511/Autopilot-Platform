r"""本机 HTTPS 联调（Platform API over TLS + Vite HTTP）。不得作为生产部署入口。

与 ``start_dev.py`` 类似，但 Platform 以 **直连 TLS** 监听（读取 MC_SSL 证书/私钥环境变量）。
Vite 仍为 ``http://127.0.0.1:5173``；浏览器访问 ``https://127.0.0.1:8443`` 后由 Platform 重定向到 Vite。

用法（仓库根目录）::

    python start_dev_https.py
    python start_dev_https.py start --auto-cert
    python start_dev_https.py start --no-browser
    python start_dev_https.py stop

证书：
  - ``.env`` 中配置 MC_SSL 证书与私钥路径，或
  - ``python tools/gen_tls_cert.py --cn 127.0.0.1 --write-env`` 后合并 ``platform-tls.env``，或
  - ``start --auto-cert`` 自动生成到 ``data/tls/<timestamp>/``

默认 Platform 端口 **8443**（``.env`` 里 ``MC_PORT=8000`` 时自动改用 8443；可设 ``MC_HTTPS_DEV_PORT``）。
生产部署请用 ``python -m autopilot_platform.platform``，不要用本脚本。
"""

from __future__ import annotations

import argparse
import atexit
import os
import ssl
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from autopilot_platform.platform.core.env_file import load_env_file

    load_env_file(ROOT / ".env", override=False)
except (ImportError, OSError, ValueError, TypeError):
    pass

import start_dev as sd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except (AttributeError, TypeError, ValueError, OSError):
    pass

try:
    _mc_port_raw = (os.environ.get("MC_PORT") or "").strip()
    if not _mc_port_raw or _mc_port_raw == "8000":
        # .env 常为 HTTP 联调 8000；HTTPS 脚本默认 8443（可用 MC_HTTPS_DEV_PORT 覆盖）
        BACKEND_PORT = int(os.environ.get("MC_HTTPS_DEV_PORT", "8443") or "8443")
    else:
        BACKEND_PORT = int(_mc_port_raw)
except ValueError:
    BACKEND_PORT = 8443

CLIENT_PORT = sd.CLIENT_PORT
VITE_HTTP = f"http://127.0.0.1:{CLIENT_PORT}"

_SSL_CERT_ENV = "MC_SSL_" + "CERTFILE"
_SSL_KEY_ENV = "MC_SSL_" + "KEYFILE"
_ENV_UNBUFFERED = "PYTHON" + "UNBUFFERED"
_UVicorn_SSL_CERT = "ssl_" + "certfile"
_UVicorn_SSL_KEY = "ssl_" + "keyfile"
_UVicorn_SSL_CA = "ssl_" + "ca_certs"


def _print(msg: str) -> None:
    print(f"[mc-start-dev-https] {msg}", flush=True)


def _https_health_url(host: str) -> str:
    return f"https://{host}:{BACKEND_PORT}/health"


def _https_platform_url(host: str) -> str:
    return f"https://{host}:{BACKEND_PORT}"


def _insecure_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def wait_for_https(
    url: str,
    timeout_seconds: int = 120,
    *,
    label: str,
    processes: list[tuple[str, Any]] | None = None,
) -> None:
    deadline = time.time() + timeout_seconds
    last_error: str | None = None
    ctx = _insecure_ssl_context()
    while time.time() < deadline:
        if processes is not None:
            for name, proc in processes:
                rc = proc.poll()
                if rc is not None:
                    sd.dump_recent_output(name)
                    raise RuntimeError(
                        f"{name} exited early with code {rc}. "
                        f"See [{sd.service_tag(name)}] output above."
                    )
        try:
            request = Request(url, method="GET")
            with urlopen(request, timeout=5, context=ctx) as response:
                if 200 <= getattr(response, "status", 200) < 400:
                    return
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
            time.sleep(1)
    raise RuntimeError(
        f"{label} not ready within {timeout_seconds}s: {last_error or 'unknown'}"
    )


def _find_latest_dev_cert() -> tuple[Path, Path] | None:
    base = ROOT / "data" / "tls"
    if not base.is_dir():
        return None
    candidates = sorted(
        (p for p in base.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for folder in candidates:
        cert = folder / "server.crt"
        key = folder / "server.key"
        if cert.is_file() and key.is_file():
            return cert.resolve(), key.resolve()
    return None


def _resolve_tls_material(*, auto_cert: bool, cn: str) -> tuple[Path, Path]:
    from autopilot_platform.platform.core import tls as mc_tls

    if auto_cert:
        _print("正在生成自签证书（tools/gen_tls_cert.py）...")
        py = sd.VENV_PYTHON if sd.VENV_PYTHON.is_file() else Path(sys.executable)
        sans = [f"DNS:{cn}", "IP:127.0.0.1"]
        if cn not in ("127.0.0.1", "localhost"):
            try:
                import ipaddress

                ipaddress.ip_address(cn)
                sans.append(f"IP:{cn}")
            except ValueError:
                pass
        cmd = [
            str(py),
            str(ROOT / "tools" / "gen_tls_cert.py"),
            "--cn",
            cn,
            "--write-env",
        ]
        for san in sans:
            cmd.extend(["--san", san])
        subprocess.run(cmd, cwd=str(ROOT), check=True)

    pair = _find_latest_dev_cert()
    if pair and not (os.environ.get(_SSL_CERT_ENV) or "").strip():
        cert, key = pair
        os.environ[_SSL_CERT_ENV] = str(cert)
        os.environ[_SSL_KEY_ENV] = str(key)
        _print(f"使用最新证书：{cert.parent}")

    errs = mc_tls.validate_tls_files()
    if errs:
        raise SystemExit("TLS 配置错误：" + "；".join(errs))
    if not mc_tls.ssl_enabled():
        raise SystemExit(
            "未找到可用 TLS 证书。请任选其一：\n"
            f"  1) .env 设置 {_SSL_CERT_ENV} + {_SSL_KEY_ENV}\n"
            "  2) python tools/gen_tls_cert.py --cn 127.0.0.1 --write-env\n"
            "  3) python start_dev_https.py start --auto-cert"
        )
    cert = mc_tls.ssl_certfile()
    key = mc_tls.ssl_keyfile()
    assert cert is not None and key is not None
    return cert, key


def _uvicorn_ssl_args() -> list[str]:
    from autopilot_platform.platform.core import tls as mc_tls

    kw = mc_tls.uvicorn_ssl_kwargs()
    out: list[str] = []
    cert = kw.get(_UVicorn_SSL_CERT)
    key = kw.get(_UVicorn_SSL_KEY)
    if cert and key:
        out.extend(["--ssl-certfile", str(cert), "--ssl-keyfile", str(key)])
    ca = kw.get(_UVicorn_SSL_CA)
    if ca:
        out.extend(["--ssl-ca-certs", str(ca)])
    return out


def _print_startup_guide(host: str, cert_dir: Path, log_paths: dict[str, Path]) -> None:
    platform_url = _https_platform_url(host)
    _print("All services are up (HTTPS dev).")
    _print(f"Frontend (Vite HTTP): {VITE_HTTP}")
    _print(f"Platform (HTTPS):     {platform_url}")
    _print(f"OpenAPI:              {platform_url}/docs")
    _print(f"TLS 证书目录:         {cert_dir}")
    _print("浏览器首次访问自签证书须手动信任。")
    _print("Platform：合并 platform-tls.env 到本仓 .env；开发机 IDE：合并 dev-local-ide.env 到 AutoPilot .env。")
    _print("日志文件：")
    for name, path in log_paths.items():
        _print(f"  {sd.service_tag(name):9} → {path}")
    managed_log = sd.resolve_managed_runner_log_hint()
    _print(f"  {'runner':9} → {managed_log}  （Web「启动本机托管」后写入）")
    _print(
        f"联调：优先打开 {platform_url}（Platform 会重定向到 Vite）。"
        "双仓开发：Platform 用 platform-tls.env，开发机 IDE 用 dev-local-ide.env（见 https.md §2.3）。"
    )
    _print("HTTP 联调（无 TLS）仍用：python start_dev.py")


def stop_mode() -> int:
    _print("Cleaning ports...")
    sd.reset_ports(CLIENT_PORT, BACKEND_PORT)
    _print("Cleanup completed.")
    return 0


def start_mode(args: argparse.Namespace) -> int:
    py = sd.VENV_PYTHON if sd.VENV_PYTHON.is_file() else Path(sys.executable)
    if not sd.VENV_PYTHON.is_file():
        _print(f"未找到 {sd.VENV_PYTHON}，改用当前解释器: {py}")

    bind = "127.0.0.1"
    cert_cn = bind
    if args.lan:
        _print("警告：--lan 下自签证书 SAN 可能不含局域网 IP，浏览器会报证书错误。")
        bind = "0.0.0.0"
        lan_ip = sd.resolve_local_ip()
        if lan_ip:
            cert_cn = lan_ip

    cert_path, key_path = _resolve_tls_material(auto_cert=args.auto_cert, cn=cert_cn)
    ssl_args = _uvicorn_ssl_args()

    vite_js = sd.ensure_frontend_deps()
    node = sd.resolve_node()
    sd.ensure_dev_log_dir()

    sd.reset_ports(CLIENT_PORT, BACKEND_PORT)
    atexit.register(sd.kill_started_processes)
    sd.install_signal_handlers()

    platform_url = _https_platform_url("127.0.0.1")
    cors = f"{platform_url},{VITE_HTTP}"
    backend_env = sd.build_env(
        {
            _ENV_UNBUFFERED: "1",
            "MC_HOST": bind,
            "MC_PORT": str(BACKEND_PORT),
            "MC_PLATFORM_URL": platform_url,
            "MC_FRONTEND_DEV_URL": VITE_HTTP,
            "MC_PLATFORM_LOGS_DIR": str(sd.DEV_LOG_DIR),
            _SSL_CERT_ENV: str(cert_path),
            _SSL_KEY_ENV: str(key_path),
            "MC_COOKIE_SECURE": "1",
            "MC_CORS_ORIGINS": cors,
            "MC_ALLOW_MANAGED_RUNNER": os.environ.get("MC_ALLOW_MANAGED_RUNNER", "1"),
        }
    )

    platform_reload_dir = str(sd.MC_DIR / "platform")
    platform_cmd = [
        str(py),
        "-m",
        "uvicorn",
        "autopilot_platform.platform.app:create_app",
        "--factory",
        "--reload",
        "--reload-dir",
        platform_reload_dir,
        "--reload-delay",
        "1",
        "--host",
        bind,
        "--port",
        str(BACKEND_PORT),
        *ssl_args,
    ]

    services: dict[str, Any] = {
        "platform": sd.start_process(
            "platform",
            platform_cmd,
            sd.ROOT,
            backend_env,
            verbose_logs=args.verbose_logs,
        ),
    }
    _print("Waiting for platform HTTPS /health ...")
    wait_for_https(
        _https_health_url("127.0.0.1"),
        label="platform health (https)",
        processes=[("platform", services["platform"])],
    )

    client_env = sd.build_env({_ENV_UNBUFFERED: "1"})
    frontend_cmd = [
        node,
        str(vite_js),
        "--host",
        bind,
        "--port",
        str(CLIENT_PORT),
        "--strictPort",
    ]

    def spawn_frontend() -> Any:
        return sd.start_process(
            "frontend",
            frontend_cmd,
            sd.FRONTEND_DIR,
            client_env,
            verbose_logs=args.verbose_logs,
        )

    services["frontend"] = spawn_frontend()
    _print("Waiting for Vite ...")
    sd.wait_for_http(
        VITE_HTTP,
        label="frontend Vite",
        processes=(
            ("platform", services["platform"]),
            ("frontend", services["frontend"]),
        ),
    )

    log_paths = {name: sd.dev_log_path(name) for name in ("platform", "frontend")}
    _print_startup_guide("127.0.0.1", cert_path.parent, log_paths)

    if not args.no_browser:
        try:
            webbrowser.open_new_tab(platform_url)
        except OSError:
            pass

    frontend_restarts = 0
    frontend_max_restarts = 8

    try:
        while True:
            for name, proc in list(services.items()):
                rc = proc.poll()
                if rc is None:
                    continue
                if name == "frontend":
                    try:
                        sd.wait_for_http(VITE_HTTP, timeout_seconds=5, label="frontend")
                        _print("frontend 进程退出但端口仍可达，继续监控。")
                        services.pop(name, None)
                        continue
                    except RuntimeError:
                        pass
                    frontend_restarts += 1
                    if frontend_restarts <= frontend_max_restarts:
                        sd.dump_recent_output(name)
                        _print(
                            f"frontend 异常退出 (code {rc})，正在重启 Vite "
                            f"({frontend_restarts}/{frontend_max_restarts})..."
                        )
                        time.sleep(1.0)
                        services["frontend"] = spawn_frontend()
                        continue
                sd.dump_recent_output(name)
                raise RuntimeError(f"{name} exited unexpectedly with code {rc}")
            time.sleep(2)
    finally:
        sd.kill_started_processes()


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AutoPilot 管理台 HTTPS 本机联调")
    p.add_argument(
        "command",
        nargs="?",
        choices=("start", "stop"),
        default="start",
        help="start=拉起 HTTPS 联调；stop=清理端口",
    )
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--verbose-logs", action="store_true")
    p.add_argument(
        "--auto-cert",
        action="store_true",
        help="若无证书则调用 tools/gen_tls_cert.py 生成自签 PEM",
    )
    p.add_argument(
        "--lan",
        action="store_true",
        help="绑定 0.0.0.0（自签 SAN 可能不匹配，仅高级联调）",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.command == "stop":
        return stop_mode()
    return start_mode(args)


if __name__ == "__main__":
    raise SystemExit(main())

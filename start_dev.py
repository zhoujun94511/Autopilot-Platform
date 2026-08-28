r"""本机开发一键联调（Platform API + Vite）。不得作为生产部署入口。

用法（在本仓库根目录）::

    python start_dev.py
    python start_dev.py start
    python start_dev.py start --lan
    python start_dev.py start --no-browser
    python start_dev.py start --verbose-logs
    python start_dev.py stop

拉起后端与前端、等就绪、日志写入仓库根 ``logs/``、Ctrl+C 整树退出。
``start_dev`` 不含 Runner；远控请在管理台「启动本机托管」。
"""

from __future__ import annotations

import argparse
import atexit
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from pathlib import Path
from typing import Any, Iterable, TextIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DEV_LOG_DIR = ROOT / "logs"
try:
    from autopilot_platform.platform.core.env_file import load_env_file

    load_env_file(ROOT / ".env", override=False)
except (ImportError, OSError, ValueError, TypeError):
    pass
MC_DIR = ROOT / "autopilot_platform"
FRONTEND_DIR = MC_DIR / "frontend"

IS_WINDOWS = os.name == "nt"
VENV_PYTHON = (
    ROOT / ".venv" / "Scripts" / "python.exe"
    if IS_WINDOWS
    else ROOT / ".venv" / "bin" / "python"
)

try:
    BACKEND_PORT = int(os.environ.get("MC_PORT", "8000") or "8000")
except ValueError:
    BACKEND_PORT = 8000
CLIENT_PORT = 5173
CLIENT_URL = f"http://127.0.0.1:{CLIENT_PORT}"
BACKEND_HEALTH = f"http://127.0.0.1:{BACKEND_PORT}/health"

_started_processes: list[subprocess.Popen[Any]] = []
_log_threads: list[threading.Thread] = []
_log_files: dict[str, TextIO] = {}
_log_lock = threading.Lock()
_recent_output: dict[str, deque[str]] = {}
_RECENT_OUTPUT_MAXLEN = 60

_POWERSHELL_TIMEOUT_S = 6.0
_NETSTAT_TIMEOUT_S = 8.0
_TASKLIST_TIMEOUT_S = 4.0
_TASKKILL_TIMEOUT_S = 6.0

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except (AttributeError, TypeError, ValueError, OSError):
    pass


def _print(msg: str) -> None:
    with _log_lock:
        print(f"[mc-start-dev] {msg}", flush=True)


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _sanitize_dev_log_line(line: str) -> str:
    """去掉 Vite/终端 ANSI 着色，避免 Windows 记事本打开 frontend.log 乱码。"""
    cleaned = _ANSI_ESCAPE_RE.sub("", line)
    return cleaned.replace("\u279c", "->").replace("➜", "->")


def _write_dev_log(name: str, line: str) -> None:
    handle = _log_files.get(name)
    if handle is None:
        return
    try:
        handle.write(_sanitize_dev_log_line(line) + "\n")
        handle.flush()
    except OSError:
        pass


def _dev_log_path(name: str) -> Path:
    tag = _service_tag(name)
    return DEV_LOG_DIR / f"{tag}.log"


def _ensure_dev_log_dir() -> Path:
    DEV_LOG_DIR.mkdir(parents=True, exist_ok=True)
    return DEV_LOG_DIR


def _open_dev_log(name: str) -> TextIO:
    path = _dev_log_path(name)
    is_new = not path.exists() or path.stat().st_size == 0
    handle = path.open("a", encoding="utf-8", errors="replace")
    if is_new:
        handle.write("\ufeff")
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    handle.write(f"\n--- start_dev session {stamp} ({name}) ---\n")
    handle.flush()
    return handle


def _resolve_managed_runner_log_hint() -> str:
    custom = (os.environ.get("MC_PLATFORM_LOGS_DIR") or "").strip()
    base = Path(custom) if custom else DEV_LOG_DIR
    return str(base / "managed-runner.log")


def _print_startup_guide(log_paths: dict[str, Path]) -> None:
    _print("All services are up.")
    _print(f"Frontend:  {CLIENT_URL}")
    _print(f"Backend:   http://127.0.0.1:{BACKEND_PORT}")
    _print(f"OpenAPI:   http://127.0.0.1:{BACKEND_PORT}/docs")
    _print("日志文件（完整输出，控制台默认只显示 WARN/ERROR 与少量启动行）：")
    for name, path in log_paths.items():
        _print(f"  {_service_tag(name):9} → {path}")
    managed_log = _resolve_managed_runner_log_hint()
    _print(f"  {'runner':9} → {managed_log}  （Web「启动本机托管」后写入）")
    _print(
        "远控/Android 调试：start_dev 只起 Platform+Vite，不含 Runner。"
        "请打开管理台 → 执行 → Runners →「启动本机托管」，再开设备远控。"
    )
    _print("完整控制台日志：python start_dev.py start --verbose-logs")
    _print(
        f"联调前端：{CLIENT_URL}（Vite）。"
        f"Platform {BACKEND_PORT} 根路径会转到 Vite，与 IDE「打开管理台」同一套页面。"
    )
    _print(
        "Platform 未设 MC_API_TOKEN 时服务端默认 dev-mc-token（仅 loopback）；"
        "Console 不会自动填入，Runner CLI 请显式 --token / 环境变量"
    )


def _resolve_local_ip() -> str | None:
    sock = None
    try:
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        if sock is not None:
            sock.close()


def _powershell_lines(script: str) -> list[str]:
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=_POWERSHELL_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        _print(f"powershell call failed ({exc}); fallback netstat")
        return []
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _netstat_lines(port: int) -> list[int]:
    owners: list[int] = []
    try:
        completed = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_NETSTAT_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError):
        return owners
    token = f":{port}"
    for line in completed.stdout.splitlines():
        if token not in line:
            continue
        parts = [p for p in line.split() if p]
        if len(parts) < 5:
            continue
        if not any(p.endswith(token) for p in parts):
            continue
        if not any(p in {"LISTENING", "监听"} for p in parts):
            continue
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        if pid > 0 and pid not in owners:
            owners.append(pid)
    return owners


def _lsof_owners(port: int) -> list[int]:
    owners: list[int] = []
    if shutil.which("lsof") is None:
        return owners
    try:
        completed = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_NETSTAT_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError):
        return owners
    for raw in completed.stdout.split():
        try:
            pid = int(raw.strip())
        except ValueError:
            continue
        if pid > 0 and pid not in owners:
            owners.append(pid)
    return owners


def _pid_is_running(pid: int) -> bool:
    if not IS_WINDOWS:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return True
    try:
        probe = subprocess.run(
            ["tasklist.exe", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_TASKLIST_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError):
        return True
    output = f"{probe.stdout}\n{probe.stderr}"
    return re.search(rf"\b{pid}\b", output) is not None


def get_port_owners(port: int) -> list[int]:
    if not IS_WINDOWS:
        return [p for p in _lsof_owners(port) if _pid_is_running(p)]
    owners: list[int] = []
    for raw in _powershell_lines(
        f"$ErrorActionPreference='SilentlyContinue'; "
        f"Get-NetTCPConnection -LocalPort {port} -State Listen "
        f"| Select-Object -ExpandProperty OwningProcess"
    ):
        try:
            pid = int(raw)
        except ValueError:
            continue
        if pid > 0 and pid not in owners and _pid_is_running(pid):
            owners.append(pid)
    if owners:
        return owners
    return _netstat_lines(port)


def stop_port_owner(port: int) -> None:
    for pid in get_port_owners(port):
        if not _pid_is_running(pid):
            continue
        if not IS_WINDOWS:
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, OSError) as exc:
                _print(f"Could not stop PID {pid} on port {port}: {exc}")
                continue
            for _ in range(10):
                if not _pid_is_running(pid):
                    _print(f"Freed port {port}: stopped PID {pid}")
                    break
                time.sleep(0.1)
            else:
                try:
                    os.kill(pid, signal.SIGKILL)
                    _print(f"Freed port {port}: force-killed PID {pid}")
                except (ProcessLookupError, OSError):
                    pass
            continue
        try:
            proc = subprocess.run(
                ["taskkill.exe", "/PID", str(pid), "/F", "/T"],
                capture_output=True,
                text=True,
                check=False,
                timeout=_TASKKILL_TIMEOUT_S,
            )
            if proc.returncode == 0:
                _print(f"Freed port {port}: stopped PID {pid}")
            else:
                _print(
                    f"taskkill failed for PID {pid} on port {port}: "
                    f"{proc.stderr.strip() or proc.stdout.strip()}"
                )
        except (subprocess.TimeoutExpired, OSError) as exc:
            _print(f"Could not stop PID {pid} on port {port}: {exc}")


def reset_ports(*ports: int) -> None:
    for port in ports:
        stop_port_owner(port)
    for _ in range(8):
        busy = [p for p in ports if get_port_owners(p)]
        if not busy:
            return
        for p in busy:
            stop_port_owner(p)
        time.sleep(0.5)
    remaining = []
    for port in ports:
        for pid in get_port_owners(port):
            if pid not in remaining and _pid_is_running(pid):
                remaining.append(pid)
    if remaining:
        raise RuntimeError(
            f"Ports still in use by PID(s): {', '.join(map(str, remaining))}"
        )


def wait_for_http(
    url: str,
    timeout_seconds: int = 120,
    *,
    label: str,
    processes: Iterable[tuple[str, subprocess.Popen[Any]]] | None = None,
) -> None:
    deadline = time.time() + timeout_seconds
    last_error: str | None = None
    while time.time() < deadline:
        if processes is not None:
            for name, proc in processes:
                rc = proc.poll()
                if rc is not None:
                    _dump_recent_output(name)
                    raise RuntimeError(
                        f"{name} exited early with code {rc}. "
                        f"See [{_service_tag(name)}] output above."
                    )
        try:
            request = Request(url, method="GET")
            with urlopen(request, timeout=5) as response:
                if 200 <= getattr(response, "status", 200) < 400:
                    return
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
            time.sleep(1)
    raise RuntimeError(
        f"{label} not ready within {timeout_seconds}s: {last_error or 'unknown'}"
    )


def _service_tag(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "service"


def _should_relay_log(name: str, line: str, verbose_logs: bool) -> bool:
    if verbose_logs:
        return True
    stripped = line.strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if "error" in lowered or "warn" in lowered or "fatal" in lowered:
        return True
    key = re.sub(r"[^a-z0-9]+", "", name.lower())
    if key == "platform":
        return any(
            m in stripped
            for m in (
                "Uvicorn running on",
                "Application startup complete",
                "Started server process",
                "Started reloader process",
            )
        )
    if key == "frontend":
        return any(m in stripped for m in ("VITE", "Local:", "ready in"))
    return False


def _relay_log_line(name: str, line: str, verbose_logs: bool) -> None:
    _write_dev_log(name, line)
    if not _should_relay_log(name, line, verbose_logs):
        return
    with _log_lock:
        print(f"[{_service_tag(name)}] {line.replace('➜', '->')}", flush=True)


def start_process(
    name: str,
    args: list[str],
    cwd: Path,
    env: dict[str, str],
    *,
    verbose_logs: bool,
) -> subprocess.Popen[Any]:
    _print(f"Starting {name}...")
    group_kwargs: dict[str, Any] = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if IS_WINDOWS
        else {"start_new_session": True}
    )
    proc = subprocess.Popen(
        args,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **group_kwargs,
    )
    _started_processes.append(proc)
    _recent_output[name] = deque(maxlen=_RECENT_OUTPUT_MAXLEN)
    if name not in _log_files:
        _log_files[name] = _open_dev_log(name)

    def _pump() -> None:
        if proc.stdout is None:
            return
        for raw in proc.stdout:
            line = raw.rstrip("\r\n")
            _recent_output[name].append(line)
            _relay_log_line(name, line, verbose_logs)

    t = threading.Thread(target=_pump, name=f"{_service_tag(name)}-log", daemon=True)
    t.start()
    _log_threads.append(t)
    return proc


def _dump_recent_output(name: str) -> None:
    lines = list(_recent_output.get(name, ()))
    tag = _service_tag(name)
    with _log_lock:
        if not lines:
            print(f"[{tag}] (no captured output before exit)", flush=True)
            return
        print(f"[{tag}] ---- last {len(lines)} line(s) ----", flush=True)
        for line in lines:
            print(f"[{tag}] {line}", flush=True)
        print(f"[{tag}] ---- end ----", flush=True)


def _posix_kill_tree(proc: subprocess.Popen[Any]) -> None:
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, OSError):
        pgid = None
    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGTERM)
        else:
            proc.terminate()
    except (ProcessLookupError, OSError):
        return
    try:
        proc.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, OSError):
        pass


def kill_started_processes() -> None:
    for proc in reversed(_started_processes):
        if proc.poll() is not None:
            continue
        if not IS_WINDOWS:
            _posix_kill_tree(proc)
            continue
        try:
            subprocess.run(
                ["taskkill.exe", "/PID", str(proc.pid), "/F", "/T"],
                capture_output=True,
                text=True,
                check=False,
                timeout=_TASKKILL_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass
    _close_dev_log_files()


def _close_dev_log_files() -> None:
    for name, handle in list(_log_files.items()):
        try:
            handle.close()
        except OSError:
            pass
        _log_files.pop(name, None)


_last_signal_at = 0.0
_DOUBLE_TAP_WINDOW_S = 2.0


def install_signal_handlers() -> None:
    def _children_healthy() -> bool:
        return bool(_started_processes) and all(p.poll() is None for p in _started_processes)

    def _handler(signum: int, _frame: object) -> None:
        global _last_signal_at
        now = time.monotonic()
        is_double = (now - _last_signal_at) <= _DOUBLE_TAP_WINDOW_S
        _last_signal_at = now
        if signum == signal.SIGINT and _children_healthy() and not is_double:
            _print(
                f"Received SIGINT (可能是 uvicorn reload)。"
                f"{_DOUBLE_TAP_WINDOW_S:.0f}s 内再按一次 Ctrl+C 退出。"
            )
            return
        _print(f"Received signal {signum}, shutting down...")
        kill_started_processes()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def build_env(overrides: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(overrides)
    return env


def _resolve_node() -> str:
    """Locate ``node`` on PATH (Win/Linux/macOS). Optional ``NODE_HOME`` / ``NODEJS_HOME``."""
    found = shutil.which("node")
    if found:
        return found
    home = (os.environ.get("NODE_HOME") or os.environ.get("NODEJS_HOME") or "").strip()
    if home:
        for name in ("node", "node.exe"):
            cand = Path(home) / name
            if cand.is_file():
                return str(cand.resolve())
    raise FileNotFoundError(
        "未找到 node。请安装 Node.js，并确保安装目录在 PATH 中（或设置 NODE_HOME）。"
    )


def _resolve_npm() -> str:
    """Locate ``npm`` on PATH；Windows 下 ``shutil.which`` 会解析到 ``npm.cmd``。

    若仅 node 在 PATH，再尝试与 node 同目录的 npm（官方安装包常见布局）。
    """
    found = shutil.which("npm")
    if found:
        return found
    node_dir = Path(_resolve_node()).resolve().parent
    for name in ("npm", "npm.cmd"):
        cand = node_dir / name
        if cand.is_file():
            return str(cand)
    raise FileNotFoundError(
        "未找到 npm。请安装完整的 Node.js（含 npm），并确保在 PATH 中。"
    )


def _ensure_frontend_deps() -> Path:
    vite_js = FRONTEND_DIR / "node_modules" / "vite" / "bin" / "vite.js"
    if vite_js.is_file():
        return vite_js
    _print("frontend 依赖缺失，正在 npm install ...")
    node = _resolve_node()
    npm = _resolve_npm()
    env = os.environ.copy()
    # 保证 npm 脚本能再次找到同目录的 node（IDE 裁剪 PATH 时尤其重要）
    env["PATH"] = str(Path(node).resolve().parent) + os.pathsep + env.get("PATH", "")
    completed = subprocess.run(
        [npm, "install"],
        cwd=str(FRONTEND_DIR),
        check=False,
        env=env,
    )
    if completed.returncode != 0 or not vite_js.is_file():
        raise RuntimeError(
            f"npm install 失败或缺少 Vite ({vite_js})。"
            f"请手动执行: cd {FRONTEND_DIR} && npm install"
        )
    return vite_js


def stop_mode() -> int:
    _print("Cleaning ports...")
    reset_ports(CLIENT_PORT, BACKEND_PORT)
    _print("Cleanup completed.")
    return 0


def start_mode(args: argparse.Namespace) -> int:
    py = VENV_PYTHON if VENV_PYTHON.is_file() else Path(sys.executable)
    if not VENV_PYTHON.is_file():
        _print(f"未找到 {VENV_PYTHON}，改用当前解释器: {py}")

    vite_js = _ensure_frontend_deps()
    node = _resolve_node()
    _ensure_dev_log_dir()

    reset_ports(CLIENT_PORT, BACKEND_PORT)
    atexit.register(kill_started_processes)
    install_signal_handlers()

    bind = "0.0.0.0" if args.lan else "127.0.0.1"
    services: dict[str, subprocess.Popen[Any]] = {}

    # 联调只认 Vite：Platform 根路径重定向过去，IDE 打开 :8000 也不会再吃过期 dist。
    frontend_dev = CLIENT_URL
    if args.lan:
        lan_ip = _resolve_local_ip()
        if lan_ip:
            frontend_dev = f"http://{lan_ip}:{CLIENT_PORT}"
    # MC_HOST 与真实 --host 对齐，供 create_app.validate_bind_security 拦截「LAN + 默认凭据」
    backend_env = build_env(
        {
            "PYTHONUNBUFFERED": "1",
            "MC_HOST": bind,
            "MC_FRONTEND_DEV_URL": frontend_dev,
            "MC_PLATFORM_LOGS_DIR": str(DEV_LOG_DIR),
            # 本地联调自动开放“扫描并注册 Platform 同机设备”；LAN 始终关闭。
            "MC_ALLOW_MANAGED_RUNNER": (
                "0"
                if args.lan
                else os.environ.get("MC_ALLOW_MANAGED_RUNNER", "1")
            ),
        }
    )
    # reload 仅监听 Platform API，避免改 runner 代码时误触发 uvicorn 热重载。
    platform_reload_dir = str(MC_DIR / "platform")
    services["platform"] = start_process(
        "platform",
        [
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
        ],
        ROOT,
        backend_env,
        verbose_logs=args.verbose_logs,
    )
    _print("Waiting for platform /health ...")
    wait_for_http(
        BACKEND_HEALTH,
        label="platform health",
        processes=(("platform", services["platform"]),),
    )

    client_env = build_env({"PYTHONUNBUFFERED": "1"})
    frontend_cmd = [
        node,
        str(vite_js),
        "--host",
        bind,
        "--port",
        str(CLIENT_PORT),
        "--strictPort",
    ]

    def spawn_frontend() -> subprocess.Popen[Any]:
        return start_process(
            "frontend",
            frontend_cmd,
            FRONTEND_DIR,
            client_env,
            verbose_logs=args.verbose_logs,
        )

    services["frontend"] = spawn_frontend()
    _print("Waiting for Vite ...")
    wait_for_http(
        CLIENT_URL,
        label="frontend Vite",
        processes=(
            ("platform", services["platform"]),
            ("frontend", services["frontend"]),
        ),
    )

    log_paths = {name: _dev_log_path(name) for name in ("platform", "frontend")}
    _print_startup_guide(log_paths)
    if args.lan:
        ip = _resolve_local_ip()
        if ip:
            _print(f"Frontend(LAN): http://{ip}:{CLIENT_PORT}")
            _print(f"Backend(LAN):  http://{ip}:{BACKEND_PORT}")
        else:
            _print("LAN mode on, but local IP unresolved.")

    if not args.no_browser:
        try:
            webbrowser.open_new_tab(CLIENT_URL)
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
                        wait_for_http(CLIENT_URL, timeout_seconds=5, label="frontend")
                        _print("frontend 进程退出但端口仍可达，继续监控。")
                        services.pop(name, None)
                        continue
                    except RuntimeError:
                        pass
                    frontend_restarts += 1
                    if frontend_restarts <= frontend_max_restarts:
                        _dump_recent_output(name)
                        _print(
                            f"frontend 异常退出 (code {rc})，正在重启 Vite "
                            f"({frontend_restarts}/{frontend_max_restarts})..."
                        )
                        time.sleep(1.0)
                        services["frontend"] = spawn_frontend()
                        continue
                _dump_recent_output(name)
                raise RuntimeError(f"{name} exited unexpectedly with code {rc}")
            time.sleep(2)
    finally:
        kill_started_processes()


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AutoPilot 管理台前后端联调启动")
    p.add_argument(
        "command",
        nargs="?",
        choices=("start", "stop"),
        default="start",
        help="start=拉起联调；stop=只清理端口",
    )
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--verbose-logs", action="store_true")
    p.add_argument(
        "--lan",
        action="store_true",
        help="绑定 0.0.0.0 并打印局域网 URL",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.command == "stop":
        return stop_mode()
    return start_mode(args)


# 供 start_dev_https.py 等同仓联调脚本复用的公开 API（勿当作稳定对外包接口）。
def service_tag(name: str) -> str:
    return _service_tag(name)


def dump_recent_output(name: str) -> None:
    _dump_recent_output(name)


def resolve_managed_runner_log_hint() -> str:
    return _resolve_managed_runner_log_hint()


def resolve_local_ip() -> str | None:
    return _resolve_local_ip()


def ensure_frontend_deps() -> Path:
    return _ensure_frontend_deps()


def resolve_node() -> str:
    return _resolve_node()


def ensure_dev_log_dir() -> Path:
    return _ensure_dev_log_dir()


def dev_log_path(name: str) -> Path:
    return _dev_log_path(name)


if __name__ == "__main__":
    raise SystemExit(main())

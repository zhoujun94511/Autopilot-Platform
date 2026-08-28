"""AutoPilot Console 运行环境预检（preflight）：开跑前确认依赖、资源、工具链是否就位。

本仓有两种角色，可用 ``--role`` 只体检其一（默认 all 全查）：
  * platform：Platform 服务端（FastAPI + DB + 认证 + 制品/报告）；
  * runner  ：TestRunner 执行节点（Selenium/Appium + 仓内执行核 autopilot_platform.ap）。

按本项目实际配置逐项体检，**不连真机/真服务**：
  1) Python 版本；
  2) 依赖能力（core=Platform 必需；runner/web_playwright/s3/pg/secure/dev 按需）；
  3) 内置资源（runner：resources/re_go_ios 开发者镜像，供 iOS 真机）；
  4) 派生工具链（runner：adb / go-ios，由资源解包或 PATH 提供）；
  5) 移动端外部运行时（runner：Java JDK / Node.js / Appium CLI + 驱动），
     这些非 Python 包，需各自单独安装——Android 经 Appium 必需，
     iOS 在 Windows 走直连 WDA、不经 Appium；
  5b) web 能力（runner：Selenium 浏览器 + Playwright 可选引擎）；
  6) Platform 配置体检（platform：关键环境变量 / 端口；会先加载仓库根 .env）；
  6a) 开发 Web（platform：Node.js / npm，start_dev.py 用）。

每项给 OK / WARN / FAIL，并附「按需」安装命令；仅 core 缺失以非零码退出。

用法：
    .venv/Scripts/python.exe tools/preflight.py                 # 全量体检
    .venv/Scripts/python.exe tools/preflight.py --role platform # 只查服务端
    .venv/Scripts/python.exe tools/preflight.py --role runner   # 只查执行节点
    .venv/Scripts/python.exe tools/preflight.py --install runner,web_playwright,secure   # 装可选能力
    .venv/Scripts/python.exe tools/preflight.py --install-all             # 装全部可选能力
    .venv/Scripts/python.exe tools/preflight.py --install-drivers         # 装 Appium 驱动(uiautomator2)
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MIN_PY = (3, 10)   # 与 pyproject 的 requires-python 对齐

# extra 名 → [(显示名, 导入名), ...]（导入名对应已安装的包模块）
# core 即 [project].dependencies（Platform 服务端主路径）；其余对应 optional-dependencies。
EXTRAS = {
    "core": [
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
        ("SQLAlchemy", "sqlalchemy"),
        ("httpx", "httpx"),
        ("pydantic", "pydantic"),
        ("PyJWT", "jwt"),
        ("python-multipart", "multipart"),
        ("cryptography", "cryptography"),
        ("signxml", "signxml"),
        ("pyaxmlparser", "pyaxmlparser"),
        ("lxml", "lxml"),
    ],
    "runner": [
        ("selenium", "selenium"),
        ("Jinja2", "jinja2"),
        ("Appium-Python-Client", "appium"),
        ("jsonpath-ng", "jsonpath_ng"),
        ("openpyxl", "openpyxl"),
        ("opencv-python-headless", "cv2"),
        ("numpy", "numpy"),
        ("pymobiledevice3", "pymobiledevice3"),
        ("psutil", "psutil"),
        ("PyYAML", "yaml"),
    ],
    "web_playwright": [("playwright", "playwright")],
    "s3": [("boto3", "boto3")],
    "pg": [("psycopg", "psycopg")],
    "secure": [("keyring", "keyring")],
    "dev": [("pytest", "pytest"), ("ruff", "ruff")],
}
_CAP_DESC = {
    "core": "Platform 服务端（FastAPI + DB + 认证 + 制品/报告）",
    "runner": "执行节点（Selenium/Appium + 仓内执行核）",
    "web_playwright": "Web Playwright 可选引擎（web_engine=playwright）",
    "s3": "制品/报告 S3 存储后端",
    "pg": "PostgreSQL 数据库驱动",
    "secure": "管理员密码 OS 钥匙串",
    "dev": "测试 / 静态检查（pytest / ruff）",
}
# 各角色关注的可选能力（core 两角色都需，故不在此列）
_ROLE_EXTRAS = {
    "platform": ["s3", "pg", "secure", "dev"],
    "runner": ["runner", "web_playwright", "secure", "dev"],
}

_RESET, _G, _Y, _R, _DIM = "\033[0m", "\033[32m", "\033[33m", "\033[31m", "\033[2m"
_n_fail = 0   # 核心缺失计数（决定退出码）
_n_warn = 0   # 可选缺失计数


def _line(name: str, status: str, detail: str = "") -> None:
    mark = {"OK": f"{_G}✅", "WARN": f"{_Y}⚠", "FAIL": f"{_R}❌"}.get(status, "?")
    print(f"  {mark} {name:26}{_RESET} {detail}")


def _dim(s: str) -> str:
    return f"{_DIM}{s}{_RESET}"


def _have(mod: str) -> bool:
    # noinspection PyBroadException
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


def check_python() -> None:
    global _n_fail
    print("\n[1] Python 解释器")
    v = sys.version_info
    ok = (v.major, v.minor) >= MIN_PY
    _line("Python", "OK" if ok else "FAIL",
          f"{v.major}.{v.minor}.{v.micro}（需 ≥ {MIN_PY[0]}.{MIN_PY[1]}）  {sys.executable}")
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    _line("虚拟环境", "OK" if in_venv else "WARN",
          "已在 venv 内" if in_venv else "未检测到 venv（建议在项目 .venv 内运行/安装）")
    if not ok:
        _n_fail += 1


def check_caps(role: str) -> None:
    global _n_fail, _n_warn
    print("\n[2] 依赖能力（core 必需；其余按需）")
    wanted = ["core"] + (["runner", "web_playwright", "s3", "pg", "secure", "dev"] if role == "all"
                         else _ROLE_EXTRAS.get(role, []))
    for extra in wanted:
        mods = EXTRAS[extra]
        missing = [disp for disp, imp in mods if not _have(imp)]
        desc = _CAP_DESC.get(extra, "")
        if not missing:
            _line(f"{extra}", "OK", desc)
            continue
        if extra == "core":
            _n_fail += 1
            _line("core", "FAIL", f"缺 {', '.join(missing)} → pip install -e .")
        else:
            _n_warn += 1
            _line(f"{extra}", "WARN",
                  f"{desc}｜缺 {', '.join(missing)} → pip install -e .[{extra}]")


def _res(*parts) -> Path:
    return _ROOT.joinpath("resources", *parts)


def check_resources() -> None:
    global _n_warn
    print("\n[3] 内置资源（resources/｜runner 移动端）")
    checks = [
        ("re_go_ios/devimages", _res("re_go_ios", "devimages")),
    ]
    for name, p in checks:
        if p.exists():
            _line(name, "OK", _dim(str(p.relative_to(_ROOT))))
        else:
            _n_warn += 1
            _line(name, "WARN", f"缺失：{p.relative_to(_ROOT)}（iOS 真机开发者镜像挂载不可用）")


def check_toolchain() -> None:
    global _n_warn
    print("\n[4] 派生工具链（资源解包 / PATH｜runner）")
    # adb：优先仓内解包，其次 PATH（Console runner 探测设备直接用 PATH adb）
    # noinspection PyBroadException
    try:
        from autopilot_platform.ap.mobile import adb
        exe = adb.ensure_adb()
    except Exception:
        exe = None
    if not exe:
        exe = shutil.which("adb")
    _line("adb", "OK" if exe else "WARN",
          str(exe) if exe else
          "未就绪 → 装 Android SDK platform-tools 并加入 PATH（本仓通常不带 re_adb zip；见 docs/setup/android.md）")
    if not exe:
        _n_warn += 1
    # go-ios：iOS 真机工具链（Windows 无 Mac 时直连 WDA 用）
    # noinspection PyBroadException
    try:
        from autopilot_platform.ap.mobile.ios_bootstrap import resolve_go_ios
        goios = resolve_go_ios()
    except Exception as e:  # noqa: BLE001
        goios = None
        _line("go-ios", "WARN", f"检测失败：{e}")
    else:
        _line("go-ios", "OK" if goios else "WARN",
              str(goios) if goios else "未找到（iOS 真机准备不可用）")
    if not goios:
        _n_warn += 1


def _probe(exe: str, args: list[str], timeout: int = 8) -> tuple[bool, str]:
    """探测外部命令是否可用并取一行版本信息。返回 (found, version_or_msg)。"""
    path = shutil.which(exe)
    if not path:
        return False, ""
    # noinspection PyBroadException
    try:
        r = subprocess.run([path, *args], capture_output=True, timeout=timeout)
        out = (r.stdout or b"") + (r.stderr or b"")   # java -version 走 stderr
        first = out.decode("utf-8", "replace").strip().splitlines()
        return True, (first[0] if first else path)
    except Exception:
        return True, path   # 装了但探测失败，仍算存在


def _run_full(exe: str, args: list[str], timeout: int = 25) -> str:
    path = shutil.which(exe)
    if not path:
        return ""
    # noinspection PyBroadException
    try:
        r = subprocess.run([path, *args], capture_output=True, timeout=timeout)
        return ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
    except Exception:
        return ""


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


def check_mobile_runtime() -> None:
    """移动端 Android 自动化所需的外部运行时（Appium 走 Node，且需要 JDK）。"""
    global _n_warn
    print("\n[5] 移动端外部运行时（Android 经 Appium 必需；非 Python 包｜runner）")

    has_java, jver = _probe("java", ["-version"])
    _line("Java (JDK)", "OK" if has_java else "WARN",
          (jver if has_java else "未找到 java → 装 JDK 17+ 并设 JAVA_HOME（Appium Android 必需）"))
    if has_java:
        jh = os.getenv("JAVA_HOME")
        _line("  JAVA_HOME", "OK" if jh else "WARN", jh or "未设（uiautomator2 驱动多需此变量）")
        if not jh:
            _n_warn += 1
    else:
        _n_warn += 1

    has_node, nver = _probe("node", ["--version"])
    _line("Node.js", "OK" if has_node else "WARN",
          (nver if has_node else "未找到 node → 装 Node 18+（Appium 运行时）"))
    if not has_node:
        _n_warn += 1

    has_appium, aver = _probe("appium", ["--version"])
    _line("Appium CLI", "OK" if has_appium else "WARN",
          (f"v{aver}" if has_appium else "未找到 appium → npm i -g appium"))
    if has_appium:
        text = _run_full("appium", ["driver", "list", "--installed"], timeout=25).lower()
        u2 = "uiautomator2" in text
        _line("  driver uiautomator2", "OK" if u2 else "WARN",
              "已装（宿主侧 Node 驱动）" if u2 else
              "未装 → appium driver install uiautomator2")
        if not u2:
            _n_warn += 1
        if platform.system() == "Darwin":
            xc = "xcuitest" in text
            _line("  driver xcuitest", "OK" if xc else "WARN",
                  "已装（iOS/Mac）" if xc else "未装 → appium driver install xcuitest")
    else:
        _n_warn += 1

    _line("Appium server :4723", "OK" if _port_open(4723) else "WARN",
          "在监听" if _port_open(4723) else "未启动（用时再 `appium` 起；不影响安装就绪）")

    # noinspection PyBroadException
    try:
        from autopilot_platform.ap.mobile.android_env import resolve_android_sdk_root
        sdk = resolve_android_sdk_root()
    except Exception:
        sdk = None
    ah = os.getenv("ANDROID_HOME") or os.getenv("ANDROID_SDK_ROOT") or (str(sdk) if sdk else "")
    _line("ANDROID_HOME", "OK" if ah else "WARN",
          ah or "未设 → Appium UiAutomator2 服务进程需要（export 后再起 appium）")

    if platform.system() != "Darwin":
        _line("iOS 说明", "OK",
              _dim("Windows/Linux 下 iOS 走直连 WDA（go-ios + 见上），不经 Appium/Node"))


def check_web() -> None:
    """web 能力：Selenium 浏览器 + Playwright 可选引擎。"""
    global _n_warn
    print("\n[5b] web 能力（Selenium / Playwright）")
    # noinspection PyBroadException
    try:
        from autopilot_platform.runner.local_devices import probe_host_capabilities

        caps, _ = probe_host_capabilities()
        has_web = "web" in caps
        has_pw = "web-playwright" in caps
    except Exception as e:  # noqa: BLE001
        _line("浏览器探测", "WARN", f"检测失败：{e}")
        _n_warn += 1
        return
    forced = os.environ.get("MC_RUNNER_WEB", "").strip()
    hint = f"（MC_RUNNER_WEB={forced}）" if forced else ""
    _line("Selenium 浏览器", "OK" if has_web else "WARN",
          (f"检测到浏览器，Runner 将上报 web 能力{hint}" if has_web
           else "未检测到 Chrome/Edge/Firefox → 装浏览器，或 MC_RUNNER_WEB=1"))
    if not has_web:
        _n_warn += 1
    pw_pkg = _have("playwright")
    _line("playwright 包", "OK" if pw_pkg else "WARN",
          "已安装" if pw_pkg else "未装 → pip install -e \".[web_playwright]\"")
    if not pw_pkg:
        _n_warn += 1
    pw_forced = os.environ.get("MC_RUNNER_WEB_PLAYWRIGHT", "").strip()
    pw_hint = f"（MC_RUNNER_WEB_PLAYWRIGHT={pw_forced}）" if pw_forced else ""
    _line("Playwright Chromium", "OK" if has_pw else "WARN",
          (f"浏览器就绪，Runner 将上报 web-playwright{pw_hint}" if has_pw
           else "未就绪 → playwright install chromium，或 MC_RUNNER_WEB_PLAYWRIGHT=1"))
    if pw_pkg and not has_pw:
        _n_warn += 1


def check_node_dev() -> None:
    """Platform 开发态 Web（start_dev.py / Vite）需要 Node.js。"""
    global _n_warn
    print("\n[6a] 开发 Web（Node.js｜platform）")
    has_node, nver = _probe("node", ["--version"])
    _line("Node.js", "OK" if has_node else "WARN",
          (nver if has_node else "未找到 node → 装 Node 18+（start_dev.py / Vite 必需；纯 API 生产可忽略）"))
    if not has_node:
        _n_warn += 1
    has_npm, npmver = _probe("npm", ["--version"])
    _line("npm", "OK" if has_npm else "WARN",
          (f"v{npmver}" if has_npm else "未找到 npm → 与 Node 同装"))
    if has_node and not has_npm:
        _n_warn += 1


def check_platform_config() -> None:
    """Platform 服务端关键配置体检（读环境变量；会先加载仓库根 .env）。"""
    global _n_warn
    print("\n[6] Platform 配置（环境变量 / 端口｜platform）")

    env_path = _ROOT / ".env"
    loaded = None
    # noinspection PyBroadException
    try:
        from autopilot_platform.platform.core.env_file import load_env_file

        if env_path.is_file():
            load_env_file(env_path)
            loaded = env_path
    except Exception:
        pass

    _line(".env", "OK" if env_path.is_file() else "WARN",
          _dim(str(env_path.relative_to(_ROOT))) + ("（已加载供本节检查）" if loaded else "")
          if env_path.is_file()
          else "未找到（可选；用环境变量亦可，见 .env.example）")

    jwt = os.getenv("MC_JWT_SECRET", "").strip()
    _line("MC_JWT_SECRET", "OK" if jwt else "WARN",
          "已设" if jwt else "未设 → 生产必设（用于签发/校验用户 JWT，泄露可伪造登录）")
    if not jwt:
        _n_warn += 1

    pwd = os.getenv("MC_ADMIN_PASSWORD", "").strip()
    weak = (not pwd) or pwd == "admin"
    _line("MC_ADMIN_PASSWORD", "OK" if not weak else "WARN",
          "已设自定义" if not weak else "为空或默认 'admin' → 生产必改")
    if weak:
        _n_warn += 1

    dburl = os.getenv("MC_DATABASE_URL", "").strip()
    _line("MC_DATABASE_URL", "OK", dburl or _dim("未设 → 默认本地 SQLite"))

    storage = (os.getenv("MC_STORAGE", "") or "local").strip().lower()
    if storage == "s3":
        bucket = os.getenv("MC_S3_BUCKET", "").strip()
        s3_ok = _have("boto3") and bool(bucket)
        _line("MC_STORAGE=s3", "OK" if s3_ok else "WARN",
              "boto3 + MC_S3_BUCKET 就绪" if s3_ok
              else "缺 boto3 或 MC_S3_BUCKET → pip install -e .[s3] 并设桶名")
        if not s3_ok:
            _n_warn += 1
    else:
        _line("MC_STORAGE", "OK", _dim(f"{storage}（本地磁盘）"))

    host = os.getenv("MC_HOST", "127.0.0.1")
    try:
        port = int(os.getenv("MC_PORT", "8000"))
    except ValueError:
        port = 8000
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    running = _port_open(port, probe_host)
    _line(f"服务端口 :{port}", "OK",
          "已在监听（Platform 似乎已在运行）" if running
          else _dim("空闲（未启动；启动后监听此端口）"))


def do_install(groups: list[str]) -> int:
    spec = ",".join(groups)
    target = f".[{spec}]" if spec else "."
    cmd = [sys.executable, "-m", "pip", "install", "-e", target]
    print(f"\n[安装] {' '.join(cmd)}  (cwd={_ROOT})")
    return subprocess.call(cmd, cwd=str(_ROOT))


def do_install_drivers() -> int:
    appium = shutil.which("appium")
    if not appium:
        print("未找到 appium（先 npm i -g appium），无法安装驱动")
        return 2
    drivers = ["uiautomator2"] + (["xcuitest"] if platform.system() == "Darwin" else [])
    rc = 0
    for d in drivers:
        print(f"\n[安装驱动] appium driver install {d}")
        rc |= subprocess.call([appium, "driver", "install", d])
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description="AutoPilot Console 运行环境预检")
    ap.add_argument("--role", choices=["all", "platform", "runner"], default="all",
                    help="只体检指定角色（默认 all 全查）")
    ap.add_argument("--install", default="",
                    help="安装指定可选能力（逗号分隔，如 runner,web_playwright,secure）")
    ap.add_argument("--install-all", action="store_true", help="安装全部可选能力")
    ap.add_argument("--install-drivers", action="store_true",
                    help="安装宿主侧 Appium 驱动（uiautomator2；macOS 另装 xcuitest）")
    args = ap.parse_args()

    if args.install_drivers:
        return do_install_drivers()

    if args.install or args.install_all:
        optional = [g for g in EXTRAS if g != "core"]
        groups = (optional if args.install_all
                  else [g.strip() for g in args.install.split(",") if g.strip()])
        bad = [g for g in groups if g != "core" and g not in EXTRAS]
        if bad:
            print(f"未知能力组：{bad}；可选：{optional}")
            return 2
        return do_install(groups)

    role = args.role
    print(f"=== AutoPilot Console 运行环境预检 (preflight)｜role={role} ===")
    check_python()
    check_caps(role)
    if role in ("all", "runner"):
        check_resources()
        check_toolchain()
        check_mobile_runtime()
        check_web()
    if role in ("all", "platform"):
        check_node_dev()
        check_platform_config()

    print("\n=== 小结 ===")
    if _n_fail:
        print(f"  {_R}❌ 核心未就绪（{_n_fail} 项）——先 pip install -e . 再启动{_RESET}")
    elif _n_warn:
        print(f"  {_Y}⚠ 核心就绪，可正常启动；{_n_warn} 项可选能力缺失（按需 "
              f"pip install -e .[<能力>] 或 tools/preflight.py --install <能力>）{_RESET}")
    else:
        print(f"  {_G}✅ 全部就位{_RESET}")
    if role in ("all", "platform") and not _n_fail:
        print(
            "  后续：tools/init_platform.py init｜tools/check_api_contract.py｜"
            "tools/smoke_http.py --smoke｜tools/knowledge_vector_check.py"
        )
    if role in ("all", "runner") and not _n_fail:
        print(
            "  后续：python -m autopilot_platform.runner --dry-probe "
            "（设备/后端就位；不注册、不领任务）"
        )
    return 1 if _n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())

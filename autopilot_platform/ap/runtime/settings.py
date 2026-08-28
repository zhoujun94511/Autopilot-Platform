"""轻量应用设置持久化（用户级 JSON）。

记住「上次打开的工程 / 最近工程列表」等跨会话状态。读写失败（无权限/只读盘）
一律静默降级，绝不影响启动。可用环境变量 AUTOPILOT_CONFIG_DIR 重定向（测试用）。
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from typing import Any

_MAX_RECENT = 10


def _norm(path: str) -> str:
    """比较用键：规范化分隔符 + Windows 大小写不敏感。"""
    return os.path.normcase(os.path.normpath(path)) if path else ""


def config_dir() -> str:
    return os.environ.get("AUTOPILOT_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".autopilot")


def _path() -> str:
    return os.path.join(config_dir(), "settings.json")


def load() -> dict:
    # noinspection PyBroadException
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save(data: dict) -> None:
    # noinspection PyBroadException
    try:
        os.makedirs(config_dir(), exist_ok=True)
        path = _path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _harden_path_permissions(config_dir(), is_dir=True)
        _harden_path_permissions(path, is_dir=False)
    except Exception:
        pass



def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)


def set_value(key: str, value: Any) -> None:
    data = load()
    data[key] = value
    save(data)


def recent_projects() -> list:
    """最近工程列表；剔除失效目录，并按规范化路径去重（/ 与 \\ 混用合并）。"""
    data = load()
    raw = [p for p in data.get("recent_projects", []) if isinstance(p, str) and p.strip()]
    alive: list[str] = []
    seen: set[str] = set()
    for p in raw:
        if not os.path.isdir(p):
            continue
        key = _norm(p)
        if not key or key in seen:
            continue
        seen.add(key)
        alive.append(os.path.normpath(p))
    if alive != raw:
        data["recent_projects"] = alive
        if data.get("last_project"):
            data["last_project"] = os.path.normpath(str(data["last_project"]))
        save(data)
    return alive


def remember_project(path: str) -> None:
    """把 path 记为上次工程，并置顶到最近列表（规范化去重、限长）。"""
    if not path:
        return
    path = os.path.normpath(path)
    key = _norm(path)
    data = load()
    data["last_project"] = path
    recents = [
        os.path.normpath(p) for p in data.get("recent_projects", [])
        if isinstance(p, str) and p and _norm(p) != key
    ]
    recents.insert(0, path)
    data["recent_projects"] = recents[:_MAX_RECENT]
    save(data)


def last_project() -> str:
    p = load().get("last_project") or ""
    if not isinstance(p, str) or not (p and os.path.isdir(p)):
        return ""                          # 目录已删/不存在 → 不自动恢复，回到无工程态
    return os.path.normpath(p)


# 「常用关键字」热度：带时间衰减的累计分。半衰期内高频用的排前，长期不用自然沉底；
# 存储裁到上限，避免无限增长。存储项为 {"count": 分, "ts": 最后使用 epoch}；兼容旧的裸 int。
_USAGE_CAP = 50
_USAGE_HALFLIFE_S = 14 * 24 * 3600      # 14 天


def _norm_usage(raw) -> dict:
    """归一化使用记录为 {kid: (count, ts)}；兼容旧 {kid: int} 存储。"""
    out: dict = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        try:
            if isinstance(v, dict):
                out[k] = (float(v.get("count", 0)), float(v.get("ts", 0)))
            elif isinstance(v, (int, float)):
                out[k] = (float(v), 0.0)       # 旧数据无时间戳 → ts=0（视为不额外衰减）
        except (TypeError, ValueError):
            continue
    return out


def _decayed(count: float, ts: float, now: float) -> float:
    """把历史热度按距今时间做指数衰减；旧数据(ts=0)不额外衰减，保留原值。"""
    if not ts:
        return count
    return count * (0.5 ** (max(0.0, now - ts) / _USAGE_HALFLIFE_S))


def keyword_usage() -> dict:
    """{keyword_id: 累计次数}（原始计数，向后兼容；排序请用 keyword_usage_ranked）。"""
    return {k: int(c) for k, (c, _ts) in _norm_usage(load().get("keyword_usage", {})).items()}


def keyword_usage_ranked(limit: int = 0, now: float = 0.0) -> list:
    """按「带时间衰减的近期热度」降序返回 keyword_id 列表（供「常用」分组排序）。"""
    now = now or time.time()
    m = _norm_usage(load().get("keyword_usage", {}))
    ranked = sorted(m, key=lambda k: _decayed(m[k][0], m[k][1], now), reverse=True)
    return ranked[:limit] if limit else ranked


def bump_keyword_usage(keyword_id: str, now: float = 0.0) -> None:
    """关键字被插入用例时热度 +1（在衰减后的历史热度上累加，兼顾频次与时效）。
    超过上限则按当前热度保留 top N。静默降级，绝不影响插入。"""
    if not keyword_id:
        return
    now = now or time.time()
    data = load()
    m = _norm_usage(data.get("keyword_usage", {}))
    c, ts = m.get(keyword_id, (0.0, 0.0))
    m[keyword_id] = (_decayed(c, ts, now) + 1.0, now)
    if len(m) > _USAGE_CAP:                    # 裁到上限：保留当前热度最高的 N 个
        keep = sorted(m, key=lambda k: _decayed(m[k][0], m[k][1], now), reverse=True)[:_USAGE_CAP]
        m = {k: m[k] for k in keep}
    data["keyword_usage"] = {k: {"count": round(cc, 4), "ts": tt} for k, (cc, tt) in m.items()}
    save(data)


def mobile_unicode_keyboard() -> bool:
    """移动端会话是否启用 Unicode 输入法(Appium 原生 unicodeKeyboard/resetKeyboard)。

    默认关。开启后建 Android 会话时自动装并切到 Appium 自带 UnicodeIME
    (io.appium.settings/.UnicodeIME，Apache-2.0，零额外 apk)，会话结束还原原输入法——
    中文/emoji 输入的中性方案，替代老 Utf7Ime 那套。
    环境变量 AUTOPILOT_UNICODE_KEYBOARD=1 可即时开启（优先于设置项）。
    """
    env = os.environ.get("AUTOPILOT_UNICODE_KEYBOARD")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    return bool(load().get("mobile_unicode_keyboard", False))


def set_mobile_unicode_keyboard(enabled: bool) -> None:
    set_value("mobile_unicode_keyboard", bool(enabled))


# Console 执行核无 IDE UI；仅保留 settings 键的读写（不依赖主题/QSS）。
_UI_THEME_DEFAULT = "system"
_UI_THEMES = ("system", "light", "dark")


def _normalize_ui_theme(theme: str | None) -> str:
    value = (theme or _UI_THEME_DEFAULT).strip().lower()
    return value if value in _UI_THEMES else _UI_THEME_DEFAULT


def ui_theme() -> str:
    """界面主题偏好：system | light | dark（Agent 侧仅存配置，不渲染）。"""
    value = str(load().get("ui_theme", _UI_THEME_DEFAULT) or _UI_THEME_DEFAULT).strip().lower()
    return _normalize_ui_theme(value)


def set_ui_theme(theme: str) -> None:
    set_value("ui_theme", _normalize_ui_theme(theme))


def ios_backend_mode() -> str:
    value = str(load().get("ios_backend_mode", "auto") or "auto").strip().lower()
    return value if value in ("auto", "appium", "wda") else "auto"


def set_ios_backend_mode(mode: str) -> None:
    value = str(mode or "auto").strip().lower()
    set_value("ios_backend_mode", value if value in ("auto", "appium", "wda") else "auto")


def web_engine() -> str:
    """Web 执行引擎：selenium（默认）| playwright。"""
    value = str(load().get("web_engine", "selenium") or "selenium").strip().lower()
    return value if value in ("selenium", "playwright") else "selenium"


def set_web_engine(engine: str) -> None:
    value = str(engine or "selenium").strip().lower()
    set_value("web_engine", value if value in ("selenium", "playwright") else "selenium")


def web_browser() -> str:
    """Web 默认浏览器类型：chrome|edge|firefox|headless。"""
    value = str(load().get("web_browser", "chrome") or "chrome").strip().lower()
    return value if value in ("chrome", "edge", "firefox", "headless") else "chrome"


def set_web_browser(browser: str) -> None:
    value = str(browser or "chrome").strip().lower()
    set_value(
        "web_browser",
        value if value in ("chrome", "edge", "firefox", "headless") else "chrome",
    )


# ---- 移动设备 / Appium 时序（用户级 settings.json + 环境变量；单位均为秒）----

_APPIUM_STARTUP_TIMEOUT_DEFAULT_S = 40
_APPIUM_STARTUP_TIMEOUT_MIN_S = 5
_APPIUM_STARTUP_TIMEOUT_MAX_S = 300

_DEVICE_GONE_GRACE_DEFAULT_S = 8
_DEVICE_GONE_GRACE_MIN_S = 0
_DEVICE_GONE_GRACE_MAX_S = 120


def _float_env(name: str) -> float | None:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _clamp_float(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _load_device_gone_grace_s() -> float:
    """读取设备拔出去抖（秒）；兼容旧版 settings 中的 ``device_gone_grace_ms``。"""
    data = load()
    if "device_gone_grace_s" in data:
        try:
            return float(data["device_gone_grace_s"])
        except (TypeError, ValueError):
            pass
    if "device_gone_grace_ms" in data:
        try:
            return float(data["device_gone_grace_ms"]) / 1000.0
        except (TypeError, ValueError):
            pass
    return float(_DEVICE_GONE_GRACE_DEFAULT_S)


def appium_startup_timeout_s() -> float:
    """Appium 自动拉起后等待 4723 就绪的最长秒数（默认 40）。

    环境变量 ``AUTOPILOT_APPIUM_STARTUP_TIMEOUT_S`` 优先于 settings.json。
    """
    env = _float_env("AUTOPILOT_APPIUM_STARTUP_TIMEOUT_S")
    if env is not None:
        return _clamp_float(env, _APPIUM_STARTUP_TIMEOUT_MIN_S, _APPIUM_STARTUP_TIMEOUT_MAX_S)
    try:
        raw = float(load().get("appium_startup_timeout_s", _APPIUM_STARTUP_TIMEOUT_DEFAULT_S))
    except (TypeError, ValueError):
        raw = float(_APPIUM_STARTUP_TIMEOUT_DEFAULT_S)
    return _clamp_float(raw, _APPIUM_STARTUP_TIMEOUT_MIN_S, _APPIUM_STARTUP_TIMEOUT_MAX_S)


def set_appium_startup_timeout_s(seconds: float) -> None:
    set_value(
        "appium_startup_timeout_s",
        _clamp_float(float(seconds), _APPIUM_STARTUP_TIMEOUT_MIN_S, _APPIUM_STARTUP_TIMEOUT_MAX_S),
    )


def device_gone_grace_s() -> float:
    """设备监控判定「真断开」前的去抖宽限（秒，默认 8）。

    uiautomator2/WDA 初始化时列表可能瞬时掉线；宽限内恢复则不拆会话。
    设为 0 可即时判定（测试用）。环境变量 ``AUTOPILOT_DEVICE_GONE_GRACE_S`` 优先。
    """
    env = _float_env("AUTOPILOT_DEVICE_GONE_GRACE_S")
    if env is not None:
        return _clamp_float(env, _DEVICE_GONE_GRACE_MIN_S, _DEVICE_GONE_GRACE_MAX_S)
    return _clamp_float(_load_device_gone_grace_s(), _DEVICE_GONE_GRACE_MIN_S, _DEVICE_GONE_GRACE_MAX_S)


def set_device_gone_grace_s(seconds: float) -> None:
    set_value(
        "device_gone_grace_s",
        _clamp_float(float(seconds), _DEVICE_GONE_GRACE_MIN_S, _DEVICE_GONE_GRACE_MAX_S),
    )


def ios_mirror_source() -> str:
    """iOS 实时镜像画面源：auto（默认，Mac 走 AVFoundation 高帧）| mjpeg（显式 9100）。

    环境变量 IOS_MIRROR_SOURCE 优先于设置项。Win/Linux 的 auto 等价 mjpeg。
    Mac 上高帧采集失败默认回退 MJPEG；调试时设 ``IOS_MIRROR_STRICT=1`` 关闭回退。
    """
    from ..mobile.ios_mirror import mirror_source_from_env, normalize_mirror_source, resolve_mirror_source
    from ..keywords.mobile.platform import host_os

    env_mode = mirror_source_from_env()
    if env_mode:
        return resolve_mirror_source(env_mode, host=host_os())
    value = str(load().get("ios_mirror_source", "auto") or "auto").strip().lower()
    return resolve_mirror_source(normalize_mirror_source(value), host=host_os())


def set_ios_mirror_source(mode: str) -> None:
    from ..mobile.ios_mirror import normalize_mirror_source
    set_value("ios_mirror_source", normalize_mirror_source(mode))


def ios_alert_enabled() -> bool:
    return bool(load().get("ios_alert_enabled", True))


def ios_alert_policy() -> str:
    value = str(load().get("ios_alert_policy", "auto") or "auto").strip().lower()
    return value if value in ("auto", "accept", "dismiss", "ignore", "strict") else "auto"


def ios_alert_retry_on_handled() -> bool:
    return bool(load().get("ios_alert_retry_on_handled", True))


def ios_alert_record_unknown() -> bool:
    return bool(load().get("ios_alert_record_unknown", True))


def set_ios_alert_enabled(enabled: bool) -> None:
    set_value("ios_alert_enabled", bool(enabled))


def set_ios_alert_policy(policy: str) -> None:
    value = str(policy or "auto").strip().lower()
    set_value("ios_alert_policy", value if value in ("auto", "accept", "dismiss", "ignore", "strict") else "auto")


def set_ios_alert_retry_on_handled(enabled: bool) -> None:
    set_value("ios_alert_retry_on_handled", bool(enabled))


def set_ios_alert_record_unknown(enabled: bool) -> None:
    set_value("ios_alert_record_unknown", bool(enabled))


def ios_monkey_throttle_ms() -> int:
    try:
        return max(0, int(load().get("ios_monkey_throttle_ms", 500)))
    except (TypeError, ValueError):
        return 500


def ios_monkey_throttle_jitter_ms() -> int:
    try:
        return max(0, int(load().get("ios_monkey_throttle_jitter_ms", 200)))
    except (TypeError, ValueError):
        return 200


def ios_monkey_source_interval() -> int:
    try:
        return max(1, int(load().get("ios_monkey_source_interval", 5)))
    except (TypeError, ValueError):
        return 5


def ios_monkey_policy() -> str:
    value = str(load().get("ios_monkey_policy", "balanced") or "balanced").strip().lower()
    return value if value in ("safe", "balanced", "aggressive") else "balanced"


def ios_monkey_device_logs_enabled() -> bool:
    return bool(load().get("ios_monkey_device_logs_enabled", True))


def ios_monkey_device_logs_backend() -> str:
    value = str(load().get("ios_monkey_device_logs_backend", "auto") or "auto").strip().lower()
    return value if value in ("auto", "go-ios", "pmd3", "off") else "auto"


def ios_monkey_syslog_enabled() -> bool:
    return bool(load().get("ios_monkey_syslog_enabled", True))


def ios_monkey_crash_collect_enabled() -> bool:
    return bool(load().get("ios_monkey_crash_collect_enabled", True))


def ios_monkey_report_html() -> bool:
    return bool(load().get("ios_monkey_report_html", True))


def ios_monkey_syslog_filter_bundle() -> bool:
    return bool(load().get("ios_monkey_syslog_filter_bundle", True))


def ios_monkey_syslog_max_bytes() -> int:
    try:
        return max(0, int(load().get("ios_monkey_syslog_max_bytes", 52_428_800)))
    except (TypeError, ValueError):
        return 52_428_800


def ios_monkey_syslog_mode() -> str:
    value = str(load().get("ios_monkey_syslog_mode", "full") or "full").strip().lower()
    return value if value in ("full", "ostrace") else "full"


def ios_monkey_ostrace_process() -> str:
    return str(load().get("ios_monkey_ostrace_process", "") or "").strip()


def project_platform(path: str) -> str:
    """工程默认目标平台("" 通用 / android / ios)：用例未单独标平台时，执行校验按此默认。"""
    m = load().get("project_platform", {})
    return m.get(_norm(path), "") if isinstance(m, dict) else ""


def set_project_platform(path: str, plat: str) -> None:
    data = load()
    m = data.get("project_platform", {})
    if not isinstance(m, dict):
        m = {}
    m[_norm(path)] = plat
    data["project_platform"] = m
    save(data)


def _b64_decode(key: str) -> bytes:
    raw = load().get(key, "")
    if not isinstance(raw, str) or not raw:
        return b""
    # noinspection PyBroadException
    try:
        return base64.b64decode(raw.encode("ascii"))
    except Exception:
        return b""


def _b64_encode(key: str, data: bytes) -> None:
    cfg = load()
    if data:
        cfg[key] = base64.b64encode(data).decode("ascii")
    else:
        cfg.pop(key, None)
    save(cfg)


def window_layout_state() -> bytes:
    """主窗口 QMainWindow.saveState 字节（跨会话恢复 Dock 布局）。"""
    return _b64_decode("window_layout_b64")


def set_window_layout_state(data: bytes) -> None:
    _b64_encode("window_layout_b64", data)


def right_aux_split_state() -> bytes:
    """右侧辅区 QSplitter 状态。"""
    return _b64_decode("right_aux_split_b64")


def set_right_aux_split_state(data: bytes) -> None:
    _b64_encode("right_aux_split_b64", data)


# ---- 管理台连接（Web 互补；本地池与 TR 池仍隔离）----

def mc_server_url() -> str:
    return str(load().get("mc_server_url", "") or "").strip().rstrip("/")


def set_mc_server_url(url: str) -> None:
    set_value("mc_server_url", str(url or "").strip().rstrip("/"))


def mc_web_url() -> str:
    """可选：管理台 Web 前端基址（空则跟 server 同源）。开发 Vite 可填 http://127.0.0.1:5173。"""
    return str(load().get("mc_web_url", "") or "").strip().rstrip("/")


def set_mc_web_url(url: str) -> None:
    set_value("mc_web_url", str(url or "").strip().rstrip("/"))


def mc_api_token() -> str:
    """读取 Runner API Token：优先钥匙串，其次密文落盘，并迁移旧明文键。"""
    return _read_secret(
        kind="api_token",
        enc_key="mc_api_token_enc",
        plain_key="mc_api_token",
        writer=set_mc_api_token,
    )


def set_mc_api_token(token: str) -> None:
    """优先 OS 钥匙串；否则 DPAPI/Fernet 密文落盘，清除明文键。"""
    _write_secret(
        kind="api_token",
        value=str(token or "").strip(),
        enc_key="mc_api_token_enc",
        plain_key="mc_api_token",
    )


def mc_username() -> str:
    return str(load().get("mc_username", "") or "").strip()


def set_mc_username(username: str) -> None:
    set_value("mc_username", str(username or "").strip())


def _harden_path_permissions(path: str, *, is_dir: bool) -> None:
    """收紧 ``~/.autopilot`` / settings.json 为本用户可读（AUD-P1-007）。"""
    if not path or not os.path.exists(path):
        return
    try:
        if os.name == "posix":
            os.chmod(path, 0o700 if is_dir else 0o600)
            return
        if sys.platform != "win32":
            return
        import getpass
        import subprocess

        user = (os.environ.get("USERNAME") or getpass.getuser() or "").strip()
        if not user:
            return
        # 去掉继承，仅当前用户 Full control
        subprocess.run(
            ["icacls", path, "/inheritance:r"],
            check=False,
            capture_output=True,
            text=True,
        )
        grant = f"{user}:(OI)(CI)(F)" if is_dir else f"{user}:(F)"
        subprocess.run(
            ["icacls", path, "/grant:r", grant],
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        pass


def _dpapi_data_blob_type():
    """Win32 DATA_BLOB；惰性构造以免非 Windows 导入失败。"""
    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    return DataBlob


def _dpapi_protect(raw: bytes) -> bytes | None:
    """Windows DPAPI（当前用户）；非 Windows / 失败返回 None。"""
    if sys.platform != "win32" or not raw:
        return None
    try:
        import ctypes
    except ImportError:
        return None

    data_blob = _dpapi_data_blob_type()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buffer_in = ctypes.create_string_buffer(raw, len(raw))
    blob_in = data_blob(len(raw), buffer_in)
    blob_out = data_blob()
    ui_forbidden = 0x01
    ok = crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        "AutoPilot.MC",
        None,
        None,
        None,
        ui_forbidden,
        ctypes.byref(blob_out),
    )
    if not ok:
        return None
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        if blob_out.pbData:
            kernel32.LocalFree(blob_out.pbData)


def _dpapi_unprotect(blob: bytes) -> bytes | None:
    if sys.platform != "win32" or not blob:
        return None
    try:
        import ctypes
    except ImportError:
        return None

    data_blob = _dpapi_data_blob_type()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buffer_in = ctypes.create_string_buffer(blob, len(blob))
    blob_in = data_blob(len(blob), buffer_in)
    blob_out = data_blob()
    ui_forbidden = 0x01
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        ui_forbidden,
        ctypes.byref(blob_out),
    )
    if not ok:
        return None
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        if blob_out.pbData:
            kernel32.LocalFree(blob_out.pbData)


def _mc_fernet():
    """Fernet 回退密钥（hostname + 网卡 node + 用户）；优先用 DPAPI/钥匙串。"""
    import getpass
    import hashlib
    import socket
    import uuid

    from cryptography.fernet import Fernet

    material = "|".join(
        [
            "autopilot-mc-pwd-v1",
            socket.gethostname() or "host",
            f"{uuid.getnode():x}",
            getpass.getuser() or "user",
        ]
    )
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt_mc_password(password: str) -> str:
    """落盘密文：Windows 优先 DPAPI（v2dpapi），否则 Fernet（v1）。"""
    raw = (password or "").encode("utf-8")
    if not raw:
        return ""
    protected = _dpapi_protect(raw)
    if protected:
        return "v2dpapi:" + base64.b64encode(protected).decode("ascii")
    return "v1:" + _mc_fernet().encrypt(raw).decode("ascii")


def _decrypt_mc_password(token: str) -> str:
    t = (token or "").strip()
    if not t:
        return ""
    if t.startswith("v2dpapi:"):
        try:
            blob = base64.b64decode(t[8:].encode("ascii"))
        except (ValueError, TypeError):
            return ""
        plain = _dpapi_unprotect(blob)
        if not plain:
            return ""
        try:
            return plain.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    if not t.startswith("v1:"):
        return ""
    try:
        from cryptography.fernet import InvalidToken
    except ImportError:
        return ""
    try:
        return _mc_fernet().decrypt(t[3:].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return ""


def _mc_keyring_get(user: str) -> str | None:
    """从 OS 钥匙串读密码；未安装 keyring 或失败时返回 None。"""
    try:
        # noinspection PyPackageRequirements
        import keyring
        # noinspection PyPackageRequirements
        from keyring.errors import KeyringError
    except ImportError:
        return None
    try:
        value = keyring.get_password("AutoPilot.MC", user)
        return str(value) if value else None
    except KeyringError:
        return None


def _mc_keyring_store(user: str, password: str) -> bool:
    """写入或清除钥匙串；成功返回 True（调用方即可不再写文件密文）。"""
    try:
        # noinspection PyPackageRequirements
        import keyring
        # noinspection PyPackageRequirements
        from keyring.errors import KeyringError, PasswordDeleteError
    except ImportError:
        return False
    try:
        if password:
            keyring.set_password("AutoPilot.MC", user, password)
        else:
            try:
                keyring.delete_password("AutoPilot.MC", user)
            except PasswordDeleteError:
                pass
        return True
    except KeyringError:
        return False


_KR_SECRET_SERVICE = "AutoPilot.MC.Secrets"


def _secret_keyring_get(kind: str) -> str | None:
    try:
        # noinspection PyPackageRequirements
        import keyring
        # noinspection PyPackageRequirements
        from keyring.errors import KeyringError
    except ImportError:
        return None
    try:
        value = keyring.get_password(_KR_SECRET_SERVICE, kind)
        return str(value) if value else None
    except KeyringError:
        return None


def _secret_keyring_store(kind: str, value: str) -> bool:
    try:
        # noinspection PyPackageRequirements
        import keyring
        # noinspection PyPackageRequirements
        from keyring.errors import KeyringError, PasswordDeleteError
    except ImportError:
        return False
    try:
        if value:
            keyring.set_password(_KR_SECRET_SERVICE, kind, value)
        else:
            try:
                keyring.delete_password(_KR_SECRET_SERVICE, kind)
            except PasswordDeleteError:
                pass
        return True
    except KeyringError:
        return False


def _read_secret(*, kind: str, enc_key: str, plain_key: str, writer) -> str:
    from_kr = _secret_keyring_get(kind)
    if from_kr:
        return from_kr
    data = load()
    enc = str(data.get(enc_key, "") or "").strip()
    if enc:
        plain = _decrypt_mc_password(enc)
        # 旧 Fernet 密文在可升级时迁到钥匙串 / DPAPI
        if plain and enc.startswith("v1:"):
            try:
                writer(plain)
            except (OSError, RuntimeError, ValueError, TypeError):
                pass
        return plain
    plain = str(data.get(plain_key, "") or "").strip()
    if plain:
        try:
            writer(plain)
        except (OSError, RuntimeError, ValueError, TypeError):
            return plain
        return plain
    return ""


def _write_secret(*, kind: str, value: str, enc_key: str, plain_key: str) -> None:
    stored = _secret_keyring_store(kind, value)
    data = load()
    data.pop(plain_key, None)
    if stored:
        data.pop(enc_key, None)
    elif value:
        data[enc_key] = _encrypt_mc_password(value)
    else:
        data.pop(enc_key, None)
    save(data)


def mc_password() -> str:
    """读取管理台密码：优先 OS 钥匙串，其次 ``mc_password_enc``，再迁移旧明文。"""
    user = mc_username() or "default"
    from_keyring = _mc_keyring_get(user)
    if from_keyring:
        return from_keyring
    data = load()
    enc = str(data.get("mc_password_enc", "") or "").strip()
    if enc:
        plain = _decrypt_mc_password(enc)
        if plain and enc.startswith("v1:"):
            try:
                set_mc_password(plain)
            except (OSError, RuntimeError, ValueError, TypeError):
                pass
        return plain
    plain = str(data.get("mc_password", "") or "")
    if plain:
        try:
            set_mc_password(plain)
        except (OSError, RuntimeError, ValueError, TypeError):
            return plain
        return plain
    return ""


def set_mc_password(password: str) -> None:
    """优先写入 OS 钥匙串；否则 DPAPI/Fernet 密文。始终清除 settings.json 中的明文。"""
    pwd = str(password or "")
    user = mc_username() or "default"
    stored_in_keyring = _mc_keyring_store(user, pwd)

    data = load()
    data.pop("mc_password", None)
    if stored_in_keyring:
        # 钥匙串已存：去掉文件内密文，避免双源
        data.pop("mc_password_enc", None)
    elif pwd:
        data["mc_password_enc"] = _encrypt_mc_password(pwd)
    else:
        data.pop("mc_password_enc", None)
    save(data)


def mc_jwt() -> str:
    """读取 Access JWT：优先钥匙串，其次密文落盘，并迁移旧明文键。"""
    return _read_secret(
        kind="jwt",
        enc_key="mc_jwt_enc",
        plain_key="mc_jwt",
        writer=set_mc_jwt,
    )


def set_mc_jwt(token: str) -> None:
    """优先 OS 钥匙串；否则 DPAPI/Fernet 密文落盘，清除明文键。"""
    _write_secret(
        kind="jwt",
        value=str(token or "").strip(),
        enc_key="mc_jwt_enc",
        plain_key="mc_jwt",
    )


def mc_refresh() -> str:
    """读取 Refresh Token：优先钥匙串，其次密文落盘，并迁移旧明文键。"""
    return _read_secret(
        kind="refresh",
        enc_key="mc_refresh_enc",
        plain_key="mc_refresh",
        writer=set_mc_refresh,
    )


def set_mc_refresh(token: str) -> None:
    """优先 OS 钥匙串；否则 DPAPI/Fernet 密文落盘，清除明文键。"""
    _write_secret(
        kind="refresh",
        value=str(token or "").strip(),
        enc_key="mc_refresh_enc",
        plain_key="mc_refresh",
    )


def mc_user_id() -> str:
    return str(load().get("mc_user_id", "") or "").strip()


def mc_user_role() -> str:
    return str(load().get("mc_user_role", "") or "").strip()


def set_mc_user_profile(*, user_id: str = "", username: str = "", role: str = "") -> None:
    """缓存最近一次登录的用户档案（与 Web JWT 用户对齐）。"""
    if username:
        set_mc_username(username)
    set_value("mc_user_id", str(user_id or "").strip())
    set_value("mc_user_role", str(role or "").strip())


def clear_mc_session() -> None:
    set_mc_jwt("")
    set_mc_refresh("")
    set_value("mc_user_id", "")
    set_value("mc_user_role", "")


def mc_is_logged_in() -> bool:
    return bool(mc_jwt())


def mc_session_display() -> str:
    """状态栏/菜单用的短会话文案。"""
    user = mc_username()
    if mc_jwt() and user:
        role = mc_user_role()
        return f"{user}" + (f" · {role}" if role else "")
    return ""


def mc_project_id() -> str:
    """默认项目空间 id（须为账号可见成员项目；空则禁止上传/回写）。"""
    return str(load().get("mc_project_id", "") or "").strip()


def set_mc_project_id(project_id: str) -> None:
    set_value("mc_project_id", str(project_id or "").strip())


def mc_org_id() -> str:
    """可选组织上下文（发往 Platform 的 X-Org-Id）。"""
    return str(load().get("mc_org_id", "") or "").strip()


def set_mc_org_id(org_id: str) -> None:
    set_value("mc_org_id", str(org_id or "").strip())

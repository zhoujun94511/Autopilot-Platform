"""多环境 profile：api_env.yaml → 变量池。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context import ExecutionContext
from ..registry import KeywordError, keyword
from .session import get_http_session


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # 延迟：可选 PyYAML extra
    except ImportError as exc:
        raise KeywordError("api_env_use 需要 PyYAML") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise KeywordError(f"api_env 文件格式错误: {path}")
    return data


def _project_root(ctx: ExecutionContext | None = None, project_dir: str = "") -> Path | None:
    if str(project_dir or "").strip():
        root = Path(str(project_dir).strip())
        if root.is_dir():
            return root
    if ctx is not None:
        raw = getattr(ctx, "project_path", None) or ctx.get_var("__project_path__")
        if raw:
            root = Path(str(raw))
            if root.is_dir():
                return root
    return None


def find_api_env_file(
    *,
    ctx: ExecutionContext | None = None,
    project_dir: str = "",
    env_file: str = "",
) -> Path | None:
    """定位 api_env.yaml；找不到返回 None。"""
    candidates: list[Path] = []
    specified = str(env_file or "").strip()
    if specified:
        candidates.append(Path(specified))
    root = _project_root(ctx, project_dir)
    if root is not None:
        if specified:
            candidates.append(root / specified)
        candidates.append(root / "api_env.yaml")
        candidates.append(root / "config" / "api_env.yaml")
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            return path
    return None


def _profiles_map(path: Path) -> dict[str, Any]:
    data = _load_yaml(path)
    profiles = data.get("profiles") or data
    return profiles if isinstance(profiles, dict) else {}


def list_api_env_profiles(project_dir: str = "", env_file: str = "") -> list[str]:
    path = find_api_env_file(project_dir=project_dir, env_file=env_file)
    if path is None:
        return []
    try:
        profiles = _profiles_map(path)
    except KeywordError:
        return []
    return [str(k).strip() for k in profiles.keys() if str(k).strip()]


def is_auto_http_profile(profile: str) -> bool:
    name = str(profile or "").strip()
    return not name or name.lower() == "auto"


def _expand_profile_block(name: str, block: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "api_env_profile": name,
        "__http_env_profile__": name,
    }
    base_url = str(block.get("base_url") or "").strip()
    if base_url:
        out["base_url"] = base_url
    vars_map = block.get("vars") or {}
    if isinstance(vars_map, dict):
        for key, value in vars_map.items():
            out[str(key)] = value
    return out


@dataclass(frozen=True)
class HttpEnvResolution:
    """api_env.yaml profile 解析结果（Job / 本地跑 / 编写共用）。"""

    profile: str
    variables: dict[str, Any]
    env_path: str
    error: str

    @property
    def ok(self) -> bool:
        return not self.error


def resolve_http_env_profile(
    *,
    project_dir: str = "",
    profile: str = "",
    env_file: str = "",
    ctx: ExecutionContext | None = None,
) -> HttpEnvResolution:
    """定位 yaml 并展开 profile。auto/空视为成功且无变量。"""
    name = str(profile or "").strip()
    if is_auto_http_profile(name):
        return HttpEnvResolution("", {}, "", "")
    path = find_api_env_file(ctx=ctx, project_dir=project_dir, env_file=env_file)
    if path is None:
        return HttpEnvResolution(
            name,
            {},
            "",
            f"指定了 API 环境 {name!r}，但未找到 api_env.yaml（工程根或 config/）",
        )
    try:
        profiles = _profiles_map(path)
    except KeywordError as exc:
        return HttpEnvResolution(name, {}, str(path), str(exc))
    if name not in profiles:
        available = ", ".join(str(k) for k in profiles.keys()) or "(空)"
        return HttpEnvResolution(
            name,
            {},
            str(path),
            f"api_env.yaml 中不存在 profile {name!r}（已有：{available}）",
        )
    block = profiles.get(name) or {}
    if not isinstance(block, dict):
        return HttpEnvResolution(
            name, {}, str(path), f"profile {name} 必须是映射"
        )
    return HttpEnvResolution(
        name, _expand_profile_block(name, block), str(path), ""
    )


def vars_from_api_env_profile(
    project_dir: str,
    profile: str,
    env_file: str = "",
) -> dict[str, Any]:
    """把 profile 展开成可写入 base_vars 的字典；缺文件/缺 profile 返回空。"""
    return dict(
        resolve_http_env_profile(
            project_dir=project_dir, profile=profile, env_file=env_file
        ).variables
    )


def apply_job_http_env(
    base_vars: dict,
    *,
    project_dir: str,
    profile: str,
    strict: bool = True,
) -> dict:
    """Job / IDE 批跑注入：profile 写入 ctx，并带上 yaml 里的 base_url / vars。

    指定了非 auto 但找不到 yaml / profile 时：
    - ``strict=True``（默认，Job / 本地跑）：抛 ``KeywordError``，任务失败；
    - ``strict=False``（编写预览）：不写入假 profile，由调用方展示 ``error``。
    """
    resolved = resolve_http_env_profile(project_dir=project_dir, profile=profile)
    if not resolved.profile:
        return base_vars
    if resolved.error:
        if strict:
            raise KeywordError(resolved.error)
        return base_vars
    for key, value in resolved.variables.items():
        base_vars.setdefault(key, value)
    return base_vars


def _find_env_file(ctx: ExecutionContext, env_file: str) -> Path:
    path = find_api_env_file(ctx=ctx, env_file=env_file)
    if path is None:
        raise KeywordError(
            "未找到 api_env.yaml（工程根或 config/，或通过 env_file 指定）"
        )
    return path


@keyword("api_env_use", name="切换API环境", category="Http")
def api_env_use(
    ctx: ExecutionContext,
    profile: str = "",
    env_file: str = "",
    **_kw: Any,
) -> dict:
    """加载 api_env.yaml 中指定 profile 的变量；可选同步 Session base_url。

    未传 profile 时回退批跑注入的 ``__http_env_profile__``。

    文件示例::

        profiles:
          dev:
            base_url: http://127.0.0.1:8000
            vars:
              token: demo
    """
    name = (
        str(profile or "").strip()
        or str(ctx.get_var("__http_env_profile__") or "").strip()
        or str(ctx.get_var("api_env_profile") or "").strip()
    )
    if not name or name.lower() == "auto":
        raise KeywordError("api_env_use: profile 不能为空")
    path = _find_env_file(ctx, str(env_file or "").strip())
    profiles = _profiles_map(path)
    if name not in profiles:
        raise KeywordError(f"api_env 中不存在 profile: {name}")
    block = profiles[name] or {}
    if not isinstance(block, dict):
        raise KeywordError(f"profile {name} 必须是映射")
    base_url = str(block.get("base_url") or "").strip()
    vars_map = block.get("vars") or {}
    if base_url:
        ctx.set_var("base_url", base_url)
        state = get_http_session(ctx)
        if state is not None:
            state.base_url = base_url.rstrip("/")
            try:
                state.client.base_url = base_url.rstrip("/")
            except (AttributeError, TypeError, ValueError, RuntimeError):
                pass
    if isinstance(vars_map, dict):
        for key, value in vars_map.items():
            ctx.set_var(str(key), value)
    ctx.set_var("api_env_profile", name)
    ctx.set_var("__http_env_profile__", name)
    ctx.log(f"已切换 API 环境: {name} ({path})")
    return {}

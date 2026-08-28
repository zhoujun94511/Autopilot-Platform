"""One-shot: converge platform root modules into packages with shims."""
from __future__ import annotations

raise SystemExit(2)  # spent one-shot: archive/platform_package_converge — do not run

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "autopilot_platform" / "platform"

# Modules that remain at platform root (or as shims) — imports to these become `.X`
# when a file moves one level deeper. Sibling modules moved into the SAME package
# must keep single-dot imports.


def rewrite_imports(text: str, *, sibling_modules: set[str], _parent_modules: set[str]) -> str:
    """Rewrite relative imports for a file moved into a subpackage.

    - sibling_modules: stay as `.name`
    - parent_modules / everything else under platform: become `.name`
    """

    def repl_from_import(m: re.Match[str]) -> str:
        # from . import a, b as c
        names = m.group(1)
        parts = [p.strip() for p in names.split(",")]
        out: list[str] = []
        for part in parts:
            base = part.split(" as ")[0].strip()
            if base in sibling_modules:
                out.append(f"from . import {part}")
            else:
                out.append(f"from .. import {part}")
        return "; ".join(out) if len(out) > 1 else out[0]

    def repl_from_mod(m: re.Match[str]) -> str:
        mod = m.group(1)
        rest = m.group(2)
        if mod in sibling_modules:
            return f"from .{mod} import {rest}"
        return f"from ..{mod} import {rest}"

    # from . import foo
    text = re.sub(
        r"^from \. import ([^\n]+)$",
        repl_from_import,
        text,
        flags=re.M,
    )
    # from .mod import ...
    text = re.sub(
        r"^from \.([a-zA-Z_]\w*) import ([^\n]+)$",
        repl_from_mod,
        text,
        flags=re.M,
    )
    return text


def is_shim(path: Path) -> bool:
    if not path.exists():
        return False
    head = path.read_text(encoding="utf-8")[:200]
    return head.lstrip().startswith('"""Shim') or "真源：" in head


def move_group(filenames: list[str], pkg: str) -> None:
    sibling = {f[:-3] for f in filenames}
    dest_dir = ROOT / pkg
    dest_dir.mkdir(parents=True, exist_ok=True)

    for filename in filenames:
        src = ROOT / filename
        if not src.exists():
            print(f"missing {filename}")
            continue
        if is_shim(src):
            print(f"already shim {filename}")
            continue
        body = src.read_text(encoding="utf-8")
        body = rewrite_imports(body, sibling_modules=sibling, _parent_modules=set())
        (dest_dir / filename).write_text(body, encoding="utf-8")
        mod = filename[:-3]
        src.write_text(
            f'"""Shim — 真源：autopilot_platform.platform.{pkg}.{mod}"""\n'
            f"from .{pkg}.{mod} import *  # noqa: F403\n",
            encoding="utf-8",
        )
        print(f"moved {filename} -> {pkg}/{filename}")


def ensure_init(pkg: str, text: str) -> None:
    path = ROOT / pkg / "__init__.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {pkg}/__init__.py")


def move_schedules() -> None:
    src = ROOT / "schedules.py"
    if is_shim(src):
        print("schedules already shim")
        return
    body = src.read_text(encoding="utf-8")
    # siblings inside services that schedules may want; it currently imports platform.services package
    body = rewrite_imports(body, sibling_modules=set(), _parent_modules=set())
    # from . import services  is circular; use absolute package import
    body = body.replace(
        "from .. import services",
        "from autopilot_platform.platform import services",
    )
    (ROOT / "services" / "schedules.py").write_text(body, encoding="utf-8")
    src.write_text(
        '"""Shim — 真源：autopilot_platform.platform.services.schedules"""\n'
        "from .services.schedules import *  # noqa: F403\n",
        encoding="utf-8",
    )
    print("moved schedules.py -> services/schedules.py")


def main() -> None:
    move_group(["projects.py"], "tenancy")
    ensure_init(
        "tenancy",
        '''"""租户域：项目与组织统一入口。

真源：
- projects → tenancy.projects
- organizations → tenancy.organizations
"""
from __future__ import annotations

from . import projects
from .projects import (
    assert_can_access_project,
    assert_can_write_project,
    is_ops_admin,
    is_platform_admin,
    member_project_ids,
    member_role,
    project_to_out,
    visible_project_filter,
)

from . import organizations

__all__ = [
    "projects",
    "organizations",
    "assert_can_access_project",
    "assert_can_write_project",
    "is_ops_admin",
    "is_platform_admin",
    "member_project_ids",
    "member_role",
    "project_to_out",
    "visible_project_filter",
]
''',
    )

    move_group(["acl.py"], "authz")
    ensure_init(
        "authz",
        '''"""授权域：资源 ACL + RBAC 策略求值入口。"""
from __future__ import annotations

from . import acl
from .acl import (
    RESOURCE_TYPES,
    assert_can_access_resource,
    can_access_resource,
    filter_resources_by_acl,
    has_acl,
    runner_can_access_assigned_resource,
)

from . import rbac

__all__ = [
    "acl",
    "rbac",
    "RESOURCE_TYPES",
    "assert_can_access_resource",
    "can_access_resource",
    "filter_resources_by_acl",
    "has_acl",
    "runner_can_access_assigned_resource",
]
''',
    )

    move_group(
        [
            "users_artifacts.py",
            "app_builds.py",
            "app_build_storage.py",
            "artifact_manifest.py",
            "storage.py",
            "quality_check.py",
            "upload_stream.py",
        ],
        "artifacts",
    )
    ensure_init(
        "artifacts",
        '''"""制品与应用资源域（含存储 / 清单 / 质量门禁）。"""
from __future__ import annotations

from . import (
    app_build_storage,
    app_builds,
    artifact_manifest,
    quality_check,
    storage,
    upload_stream,
    users_artifacts,
)

__all__ = [
    "users_artifacts",
    "app_builds",
    "app_build_storage",
    "artifact_manifest",
    "storage",
    "quality_check",
    "upload_stream",
]
''',
    )

    move_group(
        [
            "ai_client.py",
            "ai_config.py",
            "ai_case_generator.py",
            "ai_requirements_analyze.py",
        ],
        "ai",
    )
    ensure_init(
        "ai",
        '''"""AI / LLM 客户端与生成、需求分析。"""
from __future__ import annotations

from . import ai_case_generator, ai_client, ai_config, ai_requirements_analyze

__all__ = [
    "ai_client",
    "ai_config",
    "ai_case_generator",
    "ai_requirements_analyze",
]
''',
    )

    move_schedules()
    print("DONE")


if __name__ == "__main__":
    main()

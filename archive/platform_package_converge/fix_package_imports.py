"""Fix relative imports after package convergence."""
from __future__ import annotations

raise SystemExit(2)  # spent one-shot: archive/platform_package_converge — do not run

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "autopilot_platform" / "platform"

# modules that live under platform/services/
SERVICES_SIBLINGS = {
    "_common",
    "devices",
    "jobs",
    "runners",
    "reports",
    "rbac",
    "organizations",
    "session_tokens",
    "resource_pools",
    "device_reservations",
    "managed_runner",
    "project_invites",
    "schedules",
    "design",
    "design_access",
    "design_automation_sync",
    "design_chat",
    "design_documents",
    "design_enqueue",
    "design_experimental_actions",
    "design_export",
    "design_knowledge",
    "design_knowledge_import",
    "design_list_query",
    "design_requirements",
    "design_requirements_import",
    "design_stats",
    "design_test_points",
}

ARTIFACT_SIBLINGS = {
    "storage",
    "app_build_storage",
    "artifact_manifest",
    "app_builds",
    "users_artifacts",
    "quality_check",
    "upload_stream",
}

AI_SIBLINGS = {
    "ai_config",
    "ai_client",
    "ai_case_generator",
    "ai_requirements_analyze",
}


def fix_services_file(path: Path) -> None:
    """Inside services/: sibling …X -> .X ; keep …parent for platform-root modules."""
    text = path.read_text(encoding="utf-8")
    orig = text

    def repl_mod(m: re.Match[str]) -> str:
        indent, dots, mod, rest = m.group(1), m.group(2), m.group(3), m.group(4)
        top = mod.split(".", 1)[0]
        if dots == ".." and top in SERVICES_SIBLINGS:
            return f"{indent}from .{mod} import {rest}"
        if dots == "." and top not in SERVICES_SIBLINGS:
            return f"{indent}from ..{mod} import {rest}"
        return m.group(0)

    text = re.sub(
        r"(^[ \t]*)from (\.\.?)([a-zA-Z_][\w.]*) import (.+)$",
        repl_mod,
        text,
        flags=re.M,
    )
    if text != orig:
        path.write_text(text, encoding="utf-8")
        print("services fixed", path.name)


def fix_subpkg(path: Path, siblings: set[str]) -> None:
    """Inside tenancy/authz/artifacts/AI: non-sibling .X -> …X."""
    text = path.read_text(encoding="utf-8")
    orig = text

    def repl_mod(m: re.Match[str]) -> str:
        indent, mod, rest = m.group(1), m.group(2), m.group(3)
        top = mod.split(".", 1)[0]
        if top in siblings:
            return m.group(0)
        return f"{indent}from ..{mod} import {rest}"

    text = re.sub(
        r"(^[ \t]*)from \.([a-zA-Z_][\w.]*) import (.+)$",
        repl_mod,
        text,
        flags=re.M,
    )

    def repl_pkg(m: re.Match[str]) -> str:
        indent, names = m.group(1), m.group(2)
        bases = [p.split(" as ")[0].strip() for p in names.split(",")]
        if all(b in siblings for b in bases):
            return m.group(0)
        return f"{indent}from .. import {names}"

    text = re.sub(
        r"(^[ \t]*)from \. import (.+)$",
        repl_pkg,
        text,
        flags=re.M,
    )
    if text != orig:
        path.write_text(text, encoding="utf-8")
        print("subpkg fixed", path)


def main() -> None:
    for p in (ROOT / "services").glob("*.py"):
        if p.name == "__init__.py":
            continue
        fix_services_file(p)

    for p in (ROOT / "artifacts").glob("*.py"):
        if p.name != "__init__.py":
            fix_subpkg(p, ARTIFACT_SIBLINGS)
    for p in (ROOT / "ai").glob("*.py"):
        if p.name != "__init__.py":
            fix_subpkg(p, AI_SIBLINGS)
    for p in (ROOT / "tenancy").glob("*.py"):
        if p.name != "__init__.py":
            fix_subpkg(p, {"projects"})
    for p in (ROOT / "authz").glob("*.py"):
        if p.name != "__init__.py":
            fix_subpkg(p, {"acl"})

    # schedules: models lazy imports
    sched = ROOT / "services" / "schedules.py"
    t = sched.read_text(encoding="utf-8")
    t2 = re.sub(r"(^[ \t]*)from \.models import ", r"\1from ..models import ", t, flags=re.M)
    if "from autopilot_platform.platform import services" not in t2:
        t2 = t2.replace(
            "from .. import services",
            "from autopilot_platform.platform import services",
        )
    if t2 != t:
        sched.write_text(t2, encoding="utf-8")
        print("schedules patched")
    print("DONE")


if __name__ == "__main__":
    main()

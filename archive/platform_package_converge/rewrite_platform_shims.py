"""Rewrite root shims to alias the real module (preserves underscore exports)."""
from __future__ import annotations

raise SystemExit(2)  # spent one-shot: archive/platform_package_converge — do not run

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "autopilot_platform" / "platform"

SHIMS = {
    "projects.py": "tenancy.projects",
    "acl.py": "authz.acl",
    "users_artifacts.py": "artifacts.users_artifacts",
    "app_builds.py": "artifacts.app_builds",
    "app_build_storage.py": "artifacts.app_build_storage",
    "artifact_manifest.py": "artifacts.artifact_manifest",
    "storage.py": "artifacts.storage",
    "quality_check.py": "artifacts.quality_check",
    "upload_stream.py": "artifacts.upload_stream",
    "ai_client.py": "ai.ai_client",
    "ai_config.py": "ai.ai_config",
    "ai_case_generator.py": "ai.ai_case_generator",
    "ai_requirements_analyze.py": "ai.ai_requirements_analyze",
    "schedules.py": "services.schedules",
}


def main() -> None:
    for filename, dotted in SHIMS.items():
        pkg, mod = dotted.rsplit(".", 1)
        path = ROOT / filename
        path.write_text(
            f'"""Shim — 真源：autopilot_platform.platform.{dotted}\n\n'
            "本模块对象被替换为真源模块，保留 ``_`` 私有符号的旧 import 路径。\n"
            '"""\n'
            "from __future__ import annotations\n\n"
            "import sys\n\n"
            f"from .{pkg} import {mod} as _impl\n\n"
            f"sys.modules[__name__] = _impl\n",
            encoding="utf-8",
        )
        print(f"rewrote shim {filename} -> {dotted}")


if __name__ == "__main__":
    main()

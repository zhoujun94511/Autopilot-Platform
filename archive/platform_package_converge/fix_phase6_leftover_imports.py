"""Fix leftover `from platform import X` and mock path strings after Phase 6 deshim."""
from __future__ import annotations

raise SystemExit(2)  # spent one-shot: archive/platform_package_converge — do not run

import re
from pathlib import Path

MAP = {
    "ai_config": "autopilot_platform.platform.ai.ai_config",
    "ai_client": "autopilot_platform.platform.ai.ai_client",
    "db": "autopilot_platform.platform.core.db",
    "settings": "autopilot_platform.platform.core.settings",
    "models": "autopilot_platform.platform.core.models",
    "notify": "autopilot_platform.platform.ops.notify",
    "oidc": "autopilot_platform.platform.identity.oidc",
    "saml": "autopilot_platform.platform.identity.saml",
    "alerts": "autopilot_platform.platform.ops.alerts",
    "audit": "autopilot_platform.platform.ops.audit",
    "security": "autopilot_platform.platform.core.security",
    "runtime_config": "autopilot_platform.platform.ops.runtime_config",
    "runtime_compat": "autopilot_platform.platform.ops.runtime_compat",
    "scheduler_loop": "autopilot_platform.platform.ops.scheduler_loop",
    "design_models": "autopilot_platform.platform.design.design_models",
    "design_schemas": "autopilot_platform.platform.design.design_schemas",
    "intent_normalize": "autopilot_platform.platform.design.intent_normalize",
    "rag_context": "autopilot_platform.platform.design.rag_context",
    "projects": "autopilot_platform.platform.tenancy.projects",
    "acl": "autopilot_platform.platform.authz.acl",
    "schedules": "autopilot_platform.platform.services.execution.schedules",
    "storage": "autopilot_platform.platform.artifacts.storage",
    "app_builds": "autopilot_platform.platform.artifacts.app_builds",
    "app_build_storage": "autopilot_platform.platform.artifacts.app_build_storage",
    "artifact_manifest": "autopilot_platform.platform.artifacts.artifact_manifest",
    "quality_check": "autopilot_platform.platform.artifacts.quality_check",
    "upload_stream": "autopilot_platform.platform.artifacts.upload_stream",
    "users_artifacts": "autopilot_platform.platform.artifacts.users_artifacts",
    "app_meta": "autopilot_platform.platform.artifacts.app_meta",
    "ai_case_generator": "autopilot_platform.platform.ai.ai_case_generator",
    "ai_requirements_analyze": "autopilot_platform.platform.ai.ai_requirements_analyze",
    "env_file": "autopilot_platform.platform.core.env_file",
    "api_messages": "autopilot_platform.platform.core.api_messages",
    "error_handlers": "autopilot_platform.platform.core.error_handlers",
    "metrics": "autopilot_platform.platform.core.metrics",
    "login_rate": "autopilot_platform.platform.core.login_rate",
}


def rewrite(text: str) -> str:
    for name, newmod in MAP.items():
        text = re.sub(
            rf"from autopilot_platform\.platform import {name} as (\w+)",
            rf"import {newmod} as \1",
            text,
        )
        text = re.sub(
            rf"from autopilot_platform\.platform import {name}\b(?!\s*\.)",
            rf"import {newmod} as {name}",
            text,
        )
        text = text.replace(f"autopilot_platform.platform.{name}.", f"{newmod}.")
        text = text.replace(f'"autopilot_platform.platform.{name}"', f'"{newmod}"')
        text = text.replace(f"'autopilot_platform.platform.{name}'", f"'{newmod}'")
    return text


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = list((root / "tests").rglob("*.py"))
    paths += list((root / "autopilot_platform").rglob("*.py"))
    start = root / "start_dev.py"
    if start.exists():
        paths.append(start)
    n = 0
    for p in paths:
        orig = p.read_text(encoding="utf-8")
        text = rewrite(orig)
        if text != orig:
            p.write_text(text, encoding="utf-8")
            n += 1
            print("fixed", p.relative_to(root))
    print("files", n)


if __name__ == "__main__":
    main()

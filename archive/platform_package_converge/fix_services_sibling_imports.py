"""Restore `from . import <services-sibling>` that were wrongly rewritten to `…`."""
from __future__ import annotations

raise SystemExit(2)  # spent one-shot: archive/platform_package_converge — do not run

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "autopilot_platform" / "platform" / "services"
SIBS = {
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
    "_common",
}


def main() -> None:
    for path in ROOT.glob("*.py"):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8")
        orig = text

        def repl(m: re.Match[str]) -> str:
            indent, names = m.group(1), m.group(2)
            parts = [x.strip() for x in names.split(",")]
            bases = [p.split(" as ")[0].strip() for p in parts]
            if bases and all(b in SIBS for b in bases):
                return f"{indent}from . import {names}"
            return m.group(0)

        text = re.sub(r"(^[ \t]*)from \.\. import (.+)$", repl, text, flags=re.M)
        if text != orig:
            path.write_text(text, encoding="utf-8")
            print("fixed", path.name)
    print("DONE")


if __name__ == "__main__":
    main()

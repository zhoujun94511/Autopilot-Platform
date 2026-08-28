"""Rewrite tests/platform callers off protected _SessionLocal."""
from __future__ import annotations

raise SystemExit(2)  # spent one-shot: archive/platform_package_converge — do not run

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rewrite_text(text: str) -> str:
    text = text.replace(
        "from autopilot_platform.platform.core.db import _SessionLocal",
        "from autopilot_platform.platform.core.db import session_factory",
    )
    text = re.sub(
        r"assert _SessionLocal is not None\n([ \t]+)with _SessionLocal\(\) as db:",
        r"_factory = session_factory()\n\1assert _factory is not None\n\1with _factory() as db:",
        text,
    )
    text = re.sub(
        r"assert _SessionLocal is not None\n([ \t]+)db = _SessionLocal\(\)",
        r"_factory = session_factory()\n\1assert _factory is not None\n\1db = _factory()",
        text,
    )
    text = text.replace(
        "session = db_module._SessionLocal()",
        "_sf = db_module.session_factory()\n    assert _sf is not None\n    session = _sf()",
    )
    return text


def main() -> None:
    n = 0
    for p in list((ROOT / "tests").rglob("*.py")) + list(
        (ROOT / "autopilot_platform").rglob("*.py")
    ):
        if p.name == "db.py" and "core" in p.parts:
            continue
        orig = p.read_text(encoding="utf-8")
        if "_SessionLocal" not in orig:
            continue
        text = rewrite_text(orig)
        if text != orig:
            p.write_text(text, encoding="utf-8")
            n += 1
            print("updated", p.relative_to(ROOT))
        elif "_SessionLocal" in text and "session_factory" not in text.replace(
            "_SessionLocal", ""
        ):
            print("UNHANDLED", p.relative_to(ROOT))
    # leftover scan
    for p in (ROOT / "tests").rglob("*.py"):
        t = p.read_text(encoding="utf-8")
        if "_SessionLocal" in t:
            print("LEFTOVER", p.relative_to(ROOT))
    for p in (ROOT / "autopilot_platform").rglob("*.py"):
        if p.name == "db.py":
            continue
        t = p.read_text(encoding="utf-8")
        if "_SessionLocal" in t:
            print("LEFTOVER", p.relative_to(ROOT))
    print("files", n)


if __name__ == "__main__":
    main()

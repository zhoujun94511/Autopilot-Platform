"""Phase 6: move remaining root modules; rewrite imports; delete shims for clean ls."""
from __future__ import annotations

raise SystemExit(2)  # spent one-shot: archive/platform_package_converge — do not run

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "autopilot_platform" / "platform"

# old_module_name -> package
PKG_OF: dict[str, str] = {
    # phase 1-5
    "projects": "tenancy",
    "acl": "authz",
    "users_artifacts": "artifacts",
    "app_builds": "artifacts",
    "app_build_storage": "artifacts",
    "artifact_manifest": "artifacts",
    "storage": "artifacts",
    "quality_check": "artifacts",
    "upload_stream": "artifacts",
    "app_meta": "artifacts",
    "ai_client": "ai",
    "ai_config": "ai",
    "ai_case_generator": "ai",
    "ai_requirements_analyze": "ai",
    "schedules": "services",
    # phase 6
    "db": "core",
    "settings": "core",
    "env_file": "core",
    "security": "core",
    "api_messages": "core",
    "error_handlers": "core",
    "metrics": "core",
    "login_rate": "core",
    "models": "core",
    "alerts": "ops",
    "notify": "ops",
    "runtime_config": "ops",
    "runtime_compat": "ops",
    "scheduler_loop": "ops",
    "audit": "ops",
    "oidc": "identity",
    "saml": "identity",
    "design_models": "design",
    "design_schemas": "design",
    "intent_normalize": "design",
    "rag_context": "design",
}

PHASE6_FILES = [
    "db.py",
    "settings.py",
    "env_file.py",
    "security.py",
    "api_messages.py",
    "error_handlers.py",
    "metrics.py",
    "login_rate.py",
    "models.py",
    "alerts.py",
    "notify.py",
    "runtime_config.py",
    "runtime_compat.py",
    "scheduler_loop.py",
    "audit.py",
    "oidc.py",
    "saml.py",
    "design_models.py",
    "design_schemas.py",
    "intent_normalize.py",
    "rag_context.py",
    "app_meta.py",
]


def siblings_in_pkg(pkg: str) -> set[str]:
    return {name for name, p in PKG_OF.items() if p == pkg}


def is_shim(path: Path) -> bool:
    if not path.exists() or path.stat().st_size > 2500:
        return False
    head = path.read_text(encoding="utf-8")[:300]
    return "sys.modules[__name__]" in head or "真源：" in head or '"""Shim' in head


def rewrite_for_subpkg(text: str, pkg: str) -> str:
    """Rewrite relative imports for a file living in platform/<pkg>/."""
    sibs = siblings_in_pkg(pkg)

    def repl_from_mod(m: re.Match[str]) -> str:
        indent, mod, rest = m.group(1), m.group(2), m.group(3)
        top = mod.split(".", 1)[0]
        if top in sibs:
            return m.group(0)
        if top in PKG_OF:
            return f"{indent}from ..{PKG_OF[top]}.{top} import {rest}" if PKG_OF[top] != pkg else m.group(0)
        # still at platform root (auth, routes, etc.)
        return f"{indent}from ..{mod} import {rest}"

    text = re.sub(
        r"(^[ \t]*)from \.([a-zA-Z_][\w.]*) import (.+)$",
        repl_from_mod,
        text,
        flags=re.M,
    )

    def repl_from_import(m: re.Match[str]) -> str:
        indent, names = m.group(1), m.group(2)
        parts = [p.strip() for p in names.split(",")]
        lines: list[str] = []
        for part in parts:
            base = part.split(" as ")[0].strip()
            alias = part.split(" as ")[1].strip() if " as " in part else base
            if base in sibs:
                lines.append(f"{indent}from . import {part}")
            elif base in PKG_OF:
                p = PKG_OF[base]
                if p == pkg:
                    lines.append(f"{indent}from . import {part}")
                else:
                    lines.append(f"{indent}from ..{p} import {base} as {alias}")
            else:
                lines.append(f"{indent}from .. import {part}")
        # collapse consecutive same-style if all "from . import"
        if all(x.startswith(f"{indent}from . import") for x in lines):
            merged = ", ".join(x.split("import ", 1)[1] for x in lines)
            return f"{indent}from . import {merged}"
        return "\n".join(lines)

    text = re.sub(r"(^[ \t]*)from \. import (.+)$", repl_from_import, text, flags=re.M)
    return text


def write_shim(name: str) -> None:
    pkg = PKG_OF[name]
    (ROOT / f"{name}.py").write_text(
        f'"""Shim — 真源：autopilot_platform.platform.{pkg}.{name}"""\n'
        "from __future__ import annotations\n\n"
        "import sys\n\n"
        f"from .{pkg} import {name} as _impl\n\n"
        "sys.modules[__name__] = _impl\n",
        encoding="utf-8",
    )


def move_phase6() -> None:
    for filename in PHASE6_FILES:
        name = filename[:-3]
        pkg = PKG_OF[name]
        src = ROOT / filename
        if not src.exists():
            print("missing", filename)
            continue
        if is_shim(src):
            print("already shim", filename)
            continue
        dest_dir = ROOT / pkg
        dest_dir.mkdir(parents=True, exist_ok=True)
        body = rewrite_for_subpkg(src.read_text(encoding="utf-8"), pkg)
        (dest_dir / filename).write_text(body, encoding="utf-8")
        write_shim(name)
        print(f"moved {filename} -> {pkg}/{filename}")

    for pkg, doc in (
        ("core", '"""基础设施：db / settings / security / models / messages。"""\n'),
        ("ops", '"""运维：告警 / 通知 / 运行时配置 / 审计 / 调度循环。"""\n'),
        ("identity", '"""身份联邦：OIDC / SAML。auth 暂留 platform 根。"""\n'),
        ("design", '"""设计域模型与 schema。"""\n'),
    ):
        init = ROOT / pkg / "__init__.py"
        if not init.exists():
            init.write_text(doc, encoding="utf-8")


def rewrite_all_imports() -> None:
    """Point all known old imports at new package paths."""
    names = sorted(PKG_OF.keys(), key=len, reverse=True)
    files = list(ROOT.rglob("*.py")) + list((REPO / "tests").rglob("*.py"))
    if (REPO / "start_dev.py").exists():
        files.append(REPO / "start_dev.py")
    for path in files:
        if "__pycache__" in path.parts:
            continue
        if path.parent == ROOT and is_shim(path):
            continue
        text = path.read_text(encoding="utf-8")
        orig = text
        for name in names:
            pkg = PKG_OF[name]
            # absolute
            text = re.sub(
                rf"from autopilot_platform\.platform\.{name} import ",
                f"from autopilot_platform.platform.{pkg}.{name} import ",
                text,
            )
            text = re.sub(
                rf"import autopilot_platform\.platform\.{name}\b(?!\.)",
                f"import autopilot_platform.platform.{pkg}.{name} as {name}",
                text,
            )
        # relative from platform subpackages: from …name import
        try:
            rel = path.relative_to(ROOT)
        except ValueError:
            rel = None
        if rel is not None and len(rel.parts) >= 2:
            cur_pkg = rel.parts[0]
            for name in names:
                pkg = PKG_OF[name]
                if pkg == cur_pkg:
                    # from ..name -> from .name (same package)
                    text = re.sub(
                        rf"from \.\.{name} import ",
                        f"from .{name} import ",
                        text,
                    )
                else:
                    text = re.sub(
                        rf"from \.\.{name} import ",
                        f"from ..{pkg}.{name} import ",
                        text,
                    )
                    text = re.sub(
                        rf"from \.{name} import ",
                        f"from ..{pkg}.{name} import ",
                        text,
                    )
            # from … import name[, name2]
            def repl_list(m: re.Match[str]) -> str:
                indent, dots, names_part = m.group(1), m.group(2), m.group(3)
                parts = [p.strip() for p in names_part.split(",")]
                lines: list[str] = []
                leftover: list[str] = []
                for part in parts:
                    base = part.split(" as ")[0].strip()
                    alias = part.split(" as ")[1].strip() if " as " in part else base
                    if base in PKG_OF:
                        p = PKG_OF[base]
                        if dots == ".." and p == cur_pkg:
                            lines.append(f"{indent}from . import {base} as {alias}" if alias != base else f"{indent}from . import {base}")
                        else:
                            lines.append(f"{indent}from ..{p} import {base} as {alias}")
                    else:
                        leftover.append(part)
                out = []
                if leftover:
                    out.append(f"{indent}from {dots} import {', '.join(leftover)}")
                out.extend(lines)
                return "\n".join(out)

            text = re.sub(
                r"(^[ \t]*)from (\.\.) import (.+)$",
                repl_list,
                text,
                flags=re.M,
            )
            text = re.sub(
                r"(^[ \t]*)from (\.) import (.+)$",
                repl_list,
                text,
                flags=re.M,
            )

        # root-level platform files (app.py, auth.py, routes.py, api/* uses ..)
        if rel is not None and len(rel.parts) == 1:
            for name in names:
                pkg = PKG_OF[name]
                text = re.sub(
                    rf"from \.{name} import ",
                    f"from .{pkg}.{name} import ",
                    text,
                )

            def repl_root_imp(m: re.Match[str]) -> str:
                indent, names_part = m.group(1), m.group(2)
                parts = [p.strip() for p in names_part.split(",")]
                lines = []
                leftover = []
                for part in parts:
                    base = part.split(" as ")[0].strip()
                    alias = part.split(" as ")[1].strip() if " as " in part else base
                    if base in PKG_OF:
                        p = PKG_OF[base]
                        lines.append(f"{indent}from .{p} import {base} as {alias}")
                    else:
                        leftover.append(part)
                out = []
                if leftover:
                    out.append(f"{indent}from . import {', '.join(leftover)}")
                out.extend(lines)
                return "\n".join(out)

            text = re.sub(r"(^[ \t]*)from \. import (.+)$", repl_root_imp, text, flags=re.M)

        if text != orig:
            path.write_text(text, encoding="utf-8")
            print("rewrote", path.relative_to(REPO))


def delete_all_shims() -> None:
    for name in PKG_OF:
        path = ROOT / f"{name}.py"
        if path.exists() and is_shim(path):
            path.unlink()
            print("deleted shim", name)


def main() -> None:
    move_phase6()
    # also ensure earlier moved packages get cross-pkg import fix for core/ops targets
    for pkg in ("tenancy", "authz", "artifacts", "ai", "services", "api", "rag", "core", "ops", "identity", "design"):
        d = ROOT / pkg
        if not d.exists():
            continue
        for path in d.rglob("*.py"):
            if path.name == "__init__.py":
                continue
            # normalize any lingering from …X where X moved
            text = path.read_text(encoding="utf-8")
            orig = text
            cur = pkg
            for name, p in PKG_OF.items():
                if p == cur:
                    text = re.sub(rf"from \.\.{name} import ", f"from .{name} import ", text)
                else:
                    text = re.sub(rf"from \.\.{name} import ", f"from ..{p}.{name} import ", text)
            if text != orig:
                path.write_text(text, encoding="utf-8")
                print("normalized", path.relative_to(ROOT))

    rewrite_all_imports()
    delete_all_shims()
    print("DONE")


if __name__ == "__main__":
    main()

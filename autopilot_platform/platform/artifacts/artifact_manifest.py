"""制品 manifest.json 校验。"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = (
    "schema_version",
    "artifact_version",
    "project_id",
    "sha256",
    "required_runtime_version",
    "required_capabilities",
    "case_index",
)


def find_manifest_path(extract_root: str) -> Path | None:
    root = Path(extract_root or "")
    if not root.is_dir():
        return None
    candidates = [
        root / "manifest.json",
        root / "ArtifactManifest.json",
        root / "META" / "manifest.json",
    ]
    for p in candidates:
        if p.is_file():
            return p
    # 单层子目录常见：zip 解压多一层
    try:
        children = [c for c in root.iterdir() if c.is_dir() and not c.name.startswith(".")]
    except OSError:
        return None
    if len(children) == 1:
        nested = children[0] / "manifest.json"
        if nested.is_file():
            return nested
    return None


def validate_artifact_manifest(
    extract_root: str,
    *,
    expected_project_id: str = "",
) -> dict[str, Any]:
    """返回 {status, warnings, errors, manifest}。

    status: missing | valid | invalid
    """
    path = find_manifest_path(extract_root)
    if path is None:
        return {
            "status": "missing",
            "warnings": ["未找到 manifest.json（建议 IDE 发布时写入 ArtifactManifest）"],
            "errors": [],
            "manifest": None,
            "path": "",
        }

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "status": "invalid",
            "warnings": [],
            "errors": [f"manifest.json 无法解析: {exc}"],
            "manifest": None,
            "path": str(path),
        }

    if not isinstance(data, dict):
        return {
            "status": "invalid",
            "warnings": [],
            "errors": ["manifest.json 根节点必须是对象"],
            "manifest": None,
            "path": str(path),
        }

    errors: list[str] = []
    warnings: list[str] = []
    for key in REQUIRED_FIELDS:
        if key not in data:
            errors.append(f"缺少必填字段: {key}")

    if data.get("schema_version") not in (None, "1.0", 1, "1"):
        warnings.append(f"未识别的 schema_version: {data.get('schema_version')!r}")

    sha = str(data.get("sha256") or "")
    if sha and not re_fullmatch_hex64(sha):
        errors.append("sha256 应为 64 位十六进制")
    elif sha:
        actual_sha = compute_artifact_content_sha256(Path(extract_root), manifest_path=path)
        if sha.lower() != actual_sha:
            errors.append(
                "manifest.sha256 与制品内容不一致"
                f"（声明 {sha.lower()}，实际 {actual_sha}）"
            )

    caps = data.get("required_capabilities")
    if caps is not None and not isinstance(caps, list):
        errors.append("required_capabilities 应为数组")

    case_index = data.get("case_index")
    if case_index is not None:
        if not isinstance(case_index, list):
            errors.append("case_index 应为数组")
        else:
            for i, item in enumerate(case_index):
                if not isinstance(item, dict) or not str(item.get("relative_path") or "").strip():
                    errors.append(f"case_index[{i}] 缺少 relative_path")

    exp_pid = (expected_project_id or "").strip()
    man_pid = str(data.get("project_id") or "").strip()
    if exp_pid and man_pid and exp_pid != man_pid:
        mismatch = f"manifest.project_id={man_pid} 与上传 project_id={exp_pid} 不一致"
        from ..core.settings import is_production, require_artifact_manifest

        if is_production() or require_artifact_manifest():
            errors.append(mismatch)
        else:
            warnings.append(mismatch)

    # 粗略检查入口文件是否存在
    root = Path(extract_root)
    if isinstance(case_index, list):
        for item in case_index[:50]:
            if not isinstance(item, dict):
                continue
            rel = str(item.get("relative_path") or "").replace("\\", "/").lstrip("/")
            if not rel:
                continue
            # extract 可能多一层
            if not _exists_rel(root, rel):
                warnings.append(f"case_index 路径未找到: {rel}")

    status = "valid" if not errors else "invalid"
    return {
        "status": status,
        "warnings": warnings,
        "errors": errors,
        "manifest": data if status == "valid" else data,
        "path": str(path),
        "artifact_version": str(data.get("artifact_version") or ""),
        "required_runtime_version": str(data.get("required_runtime_version") or ""),
    }


def re_fullmatch_hex64(value: str) -> bool:
    import re

    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", value or ""))


def compute_artifact_content_sha256(root: Path, *, manifest_path: Path | None = None) -> str:
    """计算解压内容树哈希：按相对路径排序，排除 manifest 自身。

    每项编码为 ``UTF-8 相对路径 + NUL + 文件内容 + NUL``，路径统一使用 ``/``。
    """
    base = root.resolve()
    excluded = manifest_path.resolve() if manifest_path is not None else None
    digest = hashlib.sha256()
    files = sorted(
        (p for p in base.rglob("*") if p.is_file() and (excluded is None or p.resolve() != excluded)),
        key=lambda p: p.relative_to(base).as_posix(),
    )
    for item in files:
        digest.update(item.relative_to(base).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with item.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _exists_rel(root: Path, rel: str) -> bool:
    direct = root / rel
    if direct.is_file():
        return True
    try:
        for child in root.iterdir():
            if child.is_dir() and (child / rel).is_file():
                return True
    except OSError:
        return False
    return False

"""APPROVED 逻辑用例 → 创建批跑 Job 的最小桥。

前提：制品已由 IDE 打包上传，且 case 文件 / manifest.case_index 含 logical_case_id。
仅允许 review_status=APPROVED 的用例入队。
入口解析优先用本机解压目录；解压缺失时回退扫描制品 zip。
"""
from __future__ import annotations
import json
import os
import zipfile
from pathlib import Path
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session
from autopilot_platform.core.entries import norm_rel, strip_zip_arcroot
from autopilot_platform.core.schemas import JobCreate, JobOut
from autopilot_platform.platform.design.design_models import LogicalCaseRow
from autopilot_platform.platform.design.design_schemas import LogicalCaseEnqueueJobIn
from autopilot_platform.platform.core.models import ArtifactRow, db_get
from autopilot_platform.platform.services.execution.jobs.creation import create_job
from autopilot_platform.platform.artifacts.artifact_manifest import find_manifest_path

def _load_manifest(extract_root: str) -> dict[str, Any] | None:
    path = find_manifest_path(extract_root or '')
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None

def _paths_from_manifest(manifest: dict[str, Any], wanted: set[str]) -> dict[str, str]:
    """logical_case_id → relative_path。"""
    out: dict[str, str] = {}
    index = manifest.get('case_index')
    if not isinstance(index, list):
        return out
    for item in index:
        if not isinstance(item, dict):
            continue
        lc = str(item.get('logical_case_id') or '').strip()
        rel = str(item.get('relative_path') or '').replace('\\', '/').lstrip('/')
        if lc and rel and (not wanted or lc in wanted):
            out[lc] = rel
    return out

def _scan_yaml_logical_ids(extract_root: str, wanted: set[str]) -> dict[str, str]:
    root = Path(extract_root or '')
    if not root.is_dir():
        return {}
    try:
        import yaml  # 延迟：可选 extra，未装则跳过 YAML 扫描
    except ImportError:
        return {}
    out: dict[str, str] = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            low = name.lower()
            if not (low.endswith('.tc.yaml') or low.endswith('.tc.yml') or low.endswith('.yaml') or low.endswith('.yml')):
                continue
            full = Path(dirpath) / name
            try:
                data = yaml.safe_load(full.read_text(encoding='utf-8'))
            except (OSError, UnicodeDecodeError, ValueError, TypeError):
                continue
            if not isinstance(data, dict):
                continue
            lc = str(data.get('logical_case_id') or '').strip()
            if not lc:
                continue
            if wanted and lc not in wanted:
                continue
            rel = full.relative_to(root).as_posix()
            out[lc] = rel
    return out

def _artifact_zip_path(art: ArtifactRow) -> str:
    stored = str(getattr(art, "stored_path", "") or "").strip()
    if not stored:
        return ""
    try:
        from autopilot_platform.platform.artifacts.storage import get_artifact_store

        path = get_artifact_store().resolve_zip_path(stored)
    except (OSError, FileNotFoundError, RuntimeError, ValueError, TypeError):
        return ""
    return str(path) if path and path.is_file() else ""


def _zip_rel_map(zf: zipfile.ZipFile) -> dict[str, str]:
    members = [n for n in zf.namelist() if n and not str(n).endswith("/")]
    rels = strip_zip_arcroot(members)
    out: dict[str, str] = {}
    if len(rels) == len(members):
        for member, rel in zip(members, rels):
            key = norm_rel(rel)
            if key:
                out[key] = member
        return out
    prefix = ""
    if members and rels:
        m0 = norm_rel(members[0])
        r0 = norm_rel(rels[0])
        if r0 and m0.endswith(r0):
            prefix = m0[: -len(r0)]
    for member in members:
        nm = norm_rel(member)
        rel = nm[len(prefix) :] if prefix and nm.startswith(prefix) else nm
        rel = rel.lstrip("/")
        if rel:
            out[rel] = member
    return out


def _load_manifest_from_zip(zip_path: str) -> dict[str, Any] | None:
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            rel_map = _zip_rel_map(zf)
            for cand in ("manifest.json", "ArtifactManifest.json", "META/manifest.json"):
                member = rel_map.get(cand)
                if not member:
                    continue
                data = json.loads(zf.read(member).decode("utf-8"))
                return data if isinstance(data, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile, ValueError):
        return None
    return None


def _scan_yaml_logical_ids_in_zip(zip_path: str, wanted: set[str]) -> dict[str, str]:
    try:
        import yaml  # 延迟：可选 extra，未装则跳过 YAML 扫描
    except ImportError:
        return {}
    out: dict[str, str] = {}
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            rel_map = _zip_rel_map(zf)
            for rel, member in rel_map.items():
                low = rel.lower()
                if not (
                    low.endswith(".tc.yaml")
                    or low.endswith(".tc.yml")
                    or low.endswith(".yaml")
                    or low.endswith(".yml")
                ):
                    continue
                try:
                    data = yaml.safe_load(zf.read(member).decode("utf-8"))
                except (OSError, UnicodeDecodeError, ValueError, TypeError):
                    continue
                if not isinstance(data, dict):
                    continue
                lc = str(data.get("logical_case_id") or "").strip()
                if not lc:
                    continue
                if wanted and lc not in wanted:
                    continue
                out[lc] = rel
    except (OSError, zipfile.BadZipFile, ValueError):
        return out
    return out


def _merge_logical_id_map(
    *,
    extract: str,
    zip_path: str,
    wanted: set[str],
) -> dict[str, str]:
    """解压目录优先，否则扫 zip；两者都不可用则失败。"""
    if extract and os.path.isdir(extract):
        mapping = _paths_from_manifest(_load_manifest(extract) or {}, wanted)
        for lc, rel in _scan_yaml_logical_ids(extract, wanted).items():
            mapping.setdefault(lc, rel)
        return mapping
    if zip_path:
        mapping = _paths_from_manifest(_load_manifest_from_zip(zip_path) or {}, wanted)
        for lc, rel in _scan_yaml_logical_ids_in_zip(zip_path, wanted).items():
            mapping.setdefault(lc, rel)
        return mapping
    raise ValueError("制品无法解析用例入口（解压目录与 zip 均不可用）")


def resolve_entry_paths_for_cases(db: Session, *, artifact_id: str, logical_case_ids: list[str]) -> tuple[list[str], dict[str, str], list[str]]:
    """返回 (entry_paths, id→path, missing_ids)。解压目录优先，否则扫 zip。"""
    art = db_get(db, ArtifactRow, artifact_id)
    if art is None:
        raise LookupError(f'制品不存在: {artifact_id}')
    extract = (art.extract_path or '').strip()
    zip_path = _artifact_zip_path(art)
    wanted = {str(x).strip() for x in logical_case_ids if str(x).strip()}
    mapping = _merge_logical_id_map(extract=extract, zip_path=zip_path, wanted=wanted)
    if not wanted:
        return sorted(set(mapping.values())), mapping, []
    missing = sorted(wanted - set(mapping.keys()))
    entry_paths = [mapping[i] for i in sorted(wanted) if i in mapping]
    seen: set[str] = set()
    uniq: list[str] = []
    for p in entry_paths:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq, mapping, missing

def _safe_binding_stem(logical_case_id: str) -> str:
    bid = (logical_case_id or '').strip() or '_unknown'
    return ''.join((c if c.isalnum() or c in '-_.' else '_' for c in bid))[:120]

def _binding_stems_present(names: list[str]) -> set[str]:
    present: set[str] = set()
    for raw in names:
        parts = norm_rel(raw).split("/")
        if len(parts) < 2:
            continue
        if parts[-2].lower() != "bindings":
            continue
        base = parts[-1]
        if base.lower().endswith(".json"):
            present.add(base[:-5])
    return present


def _binding_readiness_warnings(
    extract_root: str,
    logical_case_ids: list[str],
    *,
    zip_path: str = "",
) -> list[str]:
    """Intent 批跑软提示：缺 Binding 仍可入队（靠运行时 resolve/heal），但成功率更低。"""
    if not logical_case_ids:
        return []
    warnings: list[str] = []
    missing: list[str] = []
    root = Path(extract_root or "")
    if root.is_dir():
        bindings_dir = root / "bindings"
        for cid in logical_case_ids:
            stem = _safe_binding_stem(cid)
            path = bindings_dir / f"{stem}.json"
            if not path.is_file():
                missing.append(cid)
        has_any = bindings_dir.is_dir() and any(bindings_dir.glob("*.json"))
    elif zip_path and os.path.isfile(zip_path):
        stems: set[str] = set()
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                stems = _binding_stems_present(list(_zip_rel_map(zf).keys()))
        except (OSError, zipfile.BadZipFile, ValueError):
            stems = set()
        for cid in logical_case_ids:
            if _safe_binding_stem(cid) not in stems:
                missing.append(cid)
        has_any = bool(stems)
    else:
        return []
    if missing:
        sample = ", ".join(missing[:8])
        more = f" 等共 {len(missing)} 条" if len(missing) > 8 else ""
        warnings.append(
            f"制品缺少部分 Binding（bindings/<logical_case_id>.json）：{sample}{more}。"
            "云端将依赖运行时解析/自愈；建议 IDE 本地跑通后再打包。"
        )
    elif not has_any:
        warnings.append(
            "制品未包含 bindings/*.json：Intent 步骤将纯靠运行时解析（可选 Vision），"
            "建议 IDE 固化 Binding 后上传。"
        )
    return warnings

def enqueue_approved_cases_job(db: Session, body: LogicalCaseEnqueueJobIn, auth) -> JobOut:
    pid = (body.project_id or '').strip()
    if not pid:
        raise ValueError('project_id 必填')
    aid = (body.artifact_id or '').strip()
    if not aid:
        raise ValueError('artifact_id 必填（APPROVED 用例需经 IDE 打包制品后批跑）')
    ids = [str(x).strip() for x in body.logical_case_ids or [] if str(x).strip()]
    if ids:
        rows = []
        for cid in ids:
            row = db_get(db, LogicalCaseRow, cid)
            if row is None:
                raise LookupError(f'逻辑用例不存在: {cid}')
            if str(row.project_id or '').strip() != pid:
                raise PermissionError(f'用例 {cid} 不属于项目 {pid}')
            if str(row.review_status or '') != 'APPROVED':
                raise ValueError(f'用例 {cid} 未 APPROVED（当前 {row.review_status}）')
            rows.append(row)
    else:
        rows = list(db.scalars(select(LogicalCaseRow).where(LogicalCaseRow.project_id == pid, LogicalCaseRow.review_status == 'APPROVED')).all())
        if not rows:
            raise ValueError('项目内无 APPROVED 逻辑用例')
        ids = [str(r.id) for r in rows]
    entry_paths, _mapping, missing = resolve_entry_paths_for_cases(db, artifact_id=aid, logical_case_ids=ids)
    if missing:
        raise ValueError('制品中找不到以下 logical_case_id 的入口（需 IDE 导入并打包）: ' + ', '.join(missing[:20]))
    if not entry_paths:
        raise ValueError('未能解析任何执行入口 entry_paths')
    art = db_get(db, ArtifactRow, aid)
    extract = (art.extract_path or '').strip() if art is not None else ''
    zip_path = _artifact_zip_path(art) if art is not None else ''
    readiness_warnings = _binding_readiness_warnings(extract, ids, zip_path=zip_path)
    plat = (body.platform or 'android').strip() or 'android'
    job_body = JobCreate(name=(body.name or '').strip() or f'approved-{pid[:8]}', artifact_id=aid, app_build_id=(body.app_build_id or '').strip() or None, project_id=pid, platform=plat, web_engine=getattr(body, 'web_engine', None) or 'selenium', backend_mode=getattr(body, 'backend_mode', None) or 'auto', wda_bundle=getattr(body, 'wda_bundle', None) or '', parallel=bool(getattr(body, 'parallel', False)), parallel_workers=int(getattr(body, 'parallel_workers', 0) or 0), device_udids=list(body.device_udids or []), entry_paths=entry_paths, preferred_runner_id=body.preferred_runner_id or None, webhook_url=body.webhook_url or '')
    out = create_job(db, job_body, auth=auth)
    merged = [*(out.warnings or []), *readiness_warnings]
    if merged:
        # 去重保序
        seen: set[str] = set()
        uniq: list[str] = []
        for w in merged:
            s = str(w or "").strip()
            if s and s not in seen:
                seen.add(s)
                uniq.append(s)
        try:
            return out.model_copy(update={'warnings': uniq})
        except AttributeError:
            data = out.model_dump()
            data['warnings'] = uniq
            return JobOut(**data)
    return out

"""应用资源（apk/ipa）领域服务。"""

from __future__ import annotations

from ..core import api_messages as msg

from datetime import timedelta
from pathlib import Path

# noinspection PyPackageRequirements
from sqlalchemy import func, select
# noinspection PyPackageRequirements
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import AppBuildOut, AppBuildUpdate

from ..authz.acl import assert_can_access_resource
from .app_build_storage import get_app_build_store, infer_platform, sha256_hex
from ..auth import AuthContext
from ..core.models import AppBuildRow, utcnow, db_get, new_id
from ..tenancy.projects import assert_can_access_project, assert_can_write_project


def app_build_to_out(row: AppBuildRow, *, reused: bool = False) -> AppBuildOut:
    return AppBuildOut(
        id=row.id,
        name=row.name or "",
        filename=row.filename or "",
        platform=row.platform or "",
        version_name=row.version_name or "",
        version_code=int(row.version_code or 0),
        size_bytes=int(row.size_bytes or 0),
        sha256=row.sha256 or "",
        package_id=row.package_id or "",
        main_activity=row.main_activity or "",
        uploaded_by=row.uploaded_by or "",
        project_id=row.project_id or "",
        created_at=row.created_at,
        updated_at=row.updated_at,
        reused=reused,
    )


def _validate_upload(filename: str, data: bytes, platform: str) -> str:
    """校验后缀、体积、ZIP 魔数；返回规范化 platform。"""
    from ..core.settings import app_build_max_mb

    if not data:
        raise ValueError(msg.UPLOAD_EMPTY)
    fname = filename or "app.bin"
    plat = (platform or "").strip().lower() or infer_platform(fname)
    if plat not in ("android", "ios"):
        raise ValueError(msg.APP_BUILD_PLATFORM_REQUIRED)
    low = fname.lower()
    if plat == "android" and not low.endswith((".apk", ".apex", ".xapk")):
        raise ValueError(msg.APP_BUILD_ANDROID_EXT)
    if plat == "ios" and not low.endswith(".ipa"):
        raise ValueError(msg.APP_BUILD_IOS_EXT)

    max_mb = app_build_max_mb()
    if max_mb > 0 and len(data) > max_mb * 1024 * 1024:
        raise ValueError(f"文件过大：上限 {max_mb} MB（MC_APP_BUILD_MAX_MB）")

    # apk / ipa / apex 均为 ZIP 容器；至少校验本地文件头
    if not data.startswith(b"PK\x03\x04") and not data.startswith(b"PK\x05\x06"):
        raise ValueError(msg.APP_BUILD_INVALID_ZIP)
    return plat


def _validate_upload_file(filename: str, source: Path, platform: str) -> str:
    from ..core.settings import app_build_max_mb

    size = source.stat().st_size
    if size <= 0:
        raise ValueError(msg.UPLOAD_EMPTY)
    fname = filename or "app.bin"
    plat = (platform or "").strip().lower() or infer_platform(fname)
    if plat not in ("android", "ios"):
        raise ValueError(msg.APP_BUILD_PLATFORM_REQUIRED)
    low = fname.lower()
    if plat == "android" and not low.endswith((".apk", ".apex", ".xapk")):
        raise ValueError(msg.APP_BUILD_ANDROID_EXT)
    if plat == "ios" and not low.endswith(".ipa"):
        raise ValueError(msg.APP_BUILD_IOS_EXT)
    max_mb = app_build_max_mb()
    if max_mb > 0 and size > max_mb * 1024 * 1024:
        raise ValueError(f"文件过大：上限 {max_mb} MB（MC_APP_BUILD_MAX_MB）")
    with source.open("rb") as stream:
        magic = stream.read(4)
    if magic not in (b"PK\x03\x04", b"PK\x05\x06"):
        raise ValueError(msg.APP_BUILD_INVALID_ZIP)
    return plat


def _sha256_file(source: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _try_parse_xapk_manifest(source: Path) -> tuple[str, str, str, int]:
    """XAPK 根目录 manifest.json：package_name / version_name / version_code。"""
    import json
    import zipfile

    try:
        with zipfile.ZipFile(source, "r") as zf:
            names = {n.replace("\\", "/"): n for n in zf.namelist()}
            member = names.get("manifest.json")
            if not member:
                return "", "", "", 0
            data = json.loads(zf.read(member).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile, ValueError):
        return "", "", "", 0
    if not isinstance(data, dict):
        return "", "", "", 0
    pkg = str(data.get("package_name") or data.get("package") or "").strip()
    ver = str(data.get("version_name") or data.get("versionName") or "").strip()
    try:
        code = int(data.get("version_code") or data.get("versionCode") or 0)
    except (TypeError, ValueError):
        code = 0
    return pkg, "", ver, code


def _try_parse_meta_file(filename: str, source: Path) -> tuple[str, str, str, int]:
    from .app_meta import parse_apk_meta, parse_ipa_meta

    low = filename.lower()
    try:
        if low.endswith(".xapk"):
            parsed = _try_parse_xapk_manifest(source)
            if any(parsed):
                return parsed
            return parse_apk_meta(str(source))
        if low.endswith((".apk", ".apex")):
            return parse_apk_meta(str(source))
        if low.endswith(".ipa"):
            return parse_ipa_meta(str(source))
    except (OSError, ValueError, TypeError, AttributeError, ImportError, RuntimeError):
        pass
    return "", "", "", 0


def _assert_project_quota(db: Session, project_id: str, incoming_bytes: int) -> None:
    from ..core.settings import app_build_max_count_per_project, app_build_max_total_mb_per_project

    pid = (project_id or "").strip()
    if not pid:
        return
    max_n = app_build_max_count_per_project()
    if max_n > 0:
        n = db.scalar(
            select(func.count()).select_from(AppBuildRow).where(AppBuildRow.project_id == pid)
        )
        if int(n or 0) >= max_n:
            raise ValueError(f"项目空间应用资源数量已达上限 {max_n}（MC_APP_BUILD_MAX_COUNT）")
    max_total_mb = app_build_max_total_mb_per_project()
    if max_total_mb > 0:
        total = db.scalar(
            select(func.coalesce(func.sum(AppBuildRow.size_bytes), 0)).where(
                AppBuildRow.project_id == pid
            )
        )
        if int(total or 0) + int(incoming_bytes) > max_total_mb * 1024 * 1024:
            raise ValueError(
                f"项目空间应用资源容量将超过上限 {max_total_mb} MB（MC_APP_BUILD_MAX_TOTAL_MB）"
            )


def _try_parse_meta(filename: str, data: bytes) -> tuple[str, str, str, int]:
    """返回 (package_id, main_activity, version_name, version_code)。解析失败则空。"""
    import tempfile

    from .app_meta import parse_apk_meta, parse_ipa_meta

    low = (filename or "").lower()
    suffix = (
        ".xapk"
        if low.endswith(".xapk")
        else ".apk"
        if low.endswith((".apk", ".apex"))
        else ".ipa"
        if low.endswith(".ipa")
        else ""
    )
    if not suffix:
        return "", "", "", 0
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            path = tmp.name
        try:
            if suffix == ".ipa":
                return parse_ipa_meta(path)
            if suffix == ".xapk":
                parsed = _try_parse_xapk_manifest(Path(path))
                if any(parsed):
                    return parsed
            return parse_apk_meta(path)
        finally:
            Path(path).unlink(missing_ok=True)
    except (OSError, ValueError, TypeError, AttributeError, ImportError, RuntimeError):
        return "", "", "", 0


def save_app_build(
    db: Session,
    *,
    upload_name: str,
    data: bytes,
    display_name: str = "",
    platform: str = "",
    version_name: str = "",
    version_code: int = 0,
    uploaded_by: str = "",
    project_id: str = "",
    auth: AuthContext | None = None,
) -> AppBuildOut:
    fname = upload_name or "app.bin"
    plat = _validate_upload(fname, data, platform)
    pid = (project_id or "").strip()
    if auth is not None:
        assert_can_write_project(db, auth, pid)

    digest = sha256_hex(data)
    # 同项目空间（含空）内按 sha256 去重：复用既有记录
    existing = db.scalars(
        select(AppBuildRow)
        .where(AppBuildRow.sha256 == digest, AppBuildRow.project_id == pid)
        .order_by(AppBuildRow.created_at.desc())
    ).first()
    if existing is not None:
        if auth is not None:
            assert_can_access_resource(
                db,
                auth,
                resource_type="app_build",
                resource_id=str(existing.id),
                project_id=str(existing.project_id or ""),
                owner_username=str(existing.uploaded_by or ""),
            )
        return app_build_to_out(existing, reused=True)

    _assert_project_quota(db, pid, len(data))

    bid = new_id()
    store = get_app_build_store()
    stored = store.put_file(bid, fname, data)
    pkg, act, parsed_ver, parsed_code = _try_parse_meta(fname, data)
    row = AppBuildRow(
        id=bid,
        name=(display_name or Path(fname).stem or bid).strip(),
        filename=fname,
        platform=plat,
        version_name=(version_name or parsed_ver or "").strip(),
        version_code=int(version_code or parsed_code or 0),
        stored_path=stored,
        size_bytes=len(data),
        sha256=digest,
        package_id=pkg,
        main_activity=act,
        uploaded_by=uploaded_by or "",
        project_id=pid,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return app_build_to_out(row)


def save_app_build_file(
    db: Session,
    *,
    upload_name: str,
    source_path: str | Path,
    display_name: str = "",
    platform: str = "",
    version_name: str = "",
    version_code: int = 0,
    uploaded_by: str = "",
    project_id: str = "",
    auth: AuthContext | None = None,
) -> AppBuildOut:
    source = Path(source_path)
    fname = upload_name or "app.bin"
    plat = _validate_upload_file(fname, source, platform)
    size_bytes = source.stat().st_size
    pid = (project_id or "").strip()
    if auth is not None:
        assert_can_write_project(db, auth, pid)
    digest = _sha256_file(source)
    existing = db.scalars(
        select(AppBuildRow)
        .where(AppBuildRow.sha256 == digest, AppBuildRow.project_id == pid)
        .order_by(AppBuildRow.created_at.desc())
    ).first()
    if existing is not None:
        if auth is not None:
            assert_can_access_resource(
                db,
                auth,
                resource_type="app_build",
                resource_id=str(existing.id),
                project_id=str(existing.project_id or ""),
                owner_username=str(existing.uploaded_by or ""),
            )
        return app_build_to_out(existing, reused=True)
    _assert_project_quota(db, pid, size_bytes)
    bid = new_id()
    stored = get_app_build_store().put_file_path(bid, fname, source)
    pkg, act, parsed_ver, parsed_code = _try_parse_meta_file(fname, source)
    row = AppBuildRow(
        id=bid,
        name=(display_name or Path(fname).stem or bid).strip(),
        filename=fname,
        platform=plat,
        version_name=(version_name or parsed_ver or "").strip(),
        version_code=int(version_code or parsed_code or 0),
        stored_path=stored,
        size_bytes=size_bytes,
        sha256=digest,
        package_id=pkg,
        main_activity=act,
        uploaded_by=uploaded_by or "",
        project_id=pid,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return app_build_to_out(row)


def list_app_builds(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 50,
    project_id: str = "",
    platform: str = "",
    auth: AuthContext | None = None,
) -> tuple[list[AppBuildOut], int]:
    from ..authz.acl import can_access_resource
    from ..core.list_page import slice_page
    from ..services.shared.pagination import paginate

    pid = (project_id or "").strip()
    plat = (platform or "").strip().lower()
    stmt = select(AppBuildRow).order_by(AppBuildRow.created_at.desc())
    if pid:
        if auth is not None:
            assert_can_access_project(db, auth, pid)
        stmt = stmt.where(AppBuildRow.project_id == pid)
    if plat:
        stmt = stmt.where(AppBuildRow.platform == plat)
    size = max(1, min(200, int(page_size)))
    pg = max(1, int(page))
    if auth is None or pid:
        rows, total = paginate(db, stmt, page=pg, page_size=size)
        return [app_build_to_out(r) for r in rows], total
    rows = list(db.scalars(stmt).all())
    filtered = [
        app_build_to_out(r)
        for r in rows
        if can_access_resource(
            db,
            auth,
            resource_type="app_build",
            resource_id=str(r.id),
            project_id=str(r.project_id or ""),
            owner_username=str(r.uploaded_by or ""),
        )
    ]
    return slice_page(filtered, page=pg, page_size=size)


def get_app_build(db: Session, build_id: str) -> AppBuildRow | None:
    return db_get(db, AppBuildRow, build_id)


def _app_build_has_active_references(db: Session, build_id: str) -> bool:
    from autopilot_platform.core.constants import JobStatus
    from ..core.models import DeviceRow, JobRow, ScheduleRow

    jobs = list(db.scalars(select(JobRow).where(JobRow.app_build_id == build_id)).all())
    active = {
        JobStatus.PENDING.value,
        JobStatus.CLAIMED.value,
        JobStatus.RUNNING.value,
    }
    if any(job.status in active for job in jobs):
        return True
    cancelled_ids = [job.id for job in jobs if job.status == JobStatus.CANCELLED.value]
    if cancelled_ids and db.scalars(
        select(DeviceRow).where(DeviceRow.busy_job_id.in_(cancelled_ids))
    ).first() is not None:
        return True
    return db.scalars(
        select(ScheduleRow).where(
            ScheduleRow.app_build_id == build_id,
            ScheduleRow.enabled.is_(True),
        )
    ).first() is not None


def update_app_build(
    db: Session,
    build_id: str,
    body: AppBuildUpdate,
    auth: AuthContext | None = None,
) -> AppBuildOut:
    row = db_get(db, AppBuildRow, build_id)
    if row is None:
        raise LookupError(msg.APP_BUILD_NOT_FOUND)
    if auth is not None:
        assert_can_access_resource(
            db,
            auth,
            resource_type="app_build",
            resource_id=str(row.id),
            project_id=str(row.project_id or ""),
            owner_username=str(row.uploaded_by or ""),
            need_write=True,
        )
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise ValueError(msg.APP_BUILD_NAME_REQUIRED)
        row.name = name
    if body.version_name is not None:
        row.version_name = body.version_name.strip()
    if body.version_code is not None:
        row.version_code = int(body.version_code)
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return app_build_to_out(row)


def delete_app_build(db: Session, build_id: str, auth: AuthContext | None = None) -> None:
    row = db_get(db, AppBuildRow, build_id)
    if row is None:
        raise LookupError(msg.APP_BUILD_NOT_FOUND)
    if auth is not None:
        assert_can_access_resource(
            db,
            auth,
            resource_type="app_build",
            resource_id=str(row.id),
            project_id=str(row.project_id or ""),
            owner_username=str(row.uploaded_by or ""),
            need_write=True,
        )
    if _app_build_has_active_references(db, build_id):
        raise ValueError("应用资源仍被活动任务或已启用计划引用，不能删除")
    stored_path = str(row.stored_path or "")
    db.delete(row)
    db.commit()
    get_app_build_store().delete(str(row.id), stored_path)


def purge_app_builds(
    db: Session,
    *,
    older_than_days: int | None = None,
) -> tuple[int, int]:
    """删除早于 N 天的应用资源；返回 (deleted, days_used)。"""
    from ..core.settings import app_build_retention_days

    days = app_build_retention_days() if older_than_days is None else max(0, int(older_than_days))
    if days <= 0:
        return 0, days
    cutoff = utcnow() - timedelta(days=days)
    rows = list(
        db.scalars(select(AppBuildRow).where(AppBuildRow.created_at < cutoff)).all()
    )
    rows = [row for row in rows if not _app_build_has_active_references(db, str(row.id))]
    stored = [(str(row.id), str(row.stored_path or "")) for row in rows]
    for row in rows:
        db.delete(row)
    db.commit()
    store = get_app_build_store()
    for build_id, stored_path in stored:
        store.delete(build_id, stored_path)
    return len(rows), days

"""用户与制品服务。"""

from __future__ import annotations

from ..core import api_messages as msg

from pathlib import Path

# noinspection PyPackageRequirements
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
# noinspection PyPackageRequirements
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import (
    USER_CREATE_DUTIES,
    ArtifactOut,
    LoginIn,
    TokenOut,
    UserCreate,
    UserOut,
    UserUpdate,
)

from ..auth import AuthContext
from ..core.models import (
    ArtifactRow,
    OrganizationMemberRow,
    OrganizationRow,
    ProjectMemberRow,
    ProjectRow,
    RefreshTokenRow,
    ResourceAclRow,
    UserRow,
    db_get,
    new_id,
)
from ..authz.acl import assert_can_access_resource
from ..tenancy.projects import assert_can_access_project, assert_can_write_project, is_platform_admin
from ..core.security import hash_password, validate_password_policy, verify_password
from .storage import get_artifact_store


def user_to_out(row: UserRow) -> UserOut:
    return UserOut(
        id=row.id,
        username=row.username,
        role=row.role or "operator",
        disabled=bool(row.disabled),
        created_at=row.created_at,
    )


def login(db: Session, body: LoginIn) -> TokenOut:
    row = db.scalars(select(UserRow).where(UserRow.username == body.username)).first()
    if row is None or row.disabled or not verify_password(body.password, row.password_hash):
        raise PermissionError(msg.LOGIN_INVALID_CREDENTIALS)
    from ..identity.session_tokens import issue_session

    return issue_session(db, row)


def expand_create_duty(
    duty: str,
    *,
    org_id: str = "",
    project_id: str = "",
) -> tuple[str, str, str, str]:
    """duty → (平台角色, 组织角色, 项目 id, 项目角色)。空串表示这一层不写。"""
    d = (duty or "").strip()
    if d not in USER_CREATE_DUTIES:
        raise ValueError(msg.USER_CREATE_DUTY_INVALID)
    oid = (org_id or "").strip()
    pid = (project_id or "").strip()
    if d == "user":
        return "operator", "", "", ""
    if d == "sys_admin":
        return "admin", ("member" if oid else ""), "", ""
    if d == "org_member":
        if not oid:
            raise ValueError(msg.USER_CREATE_ORG_REQUIRED)
        return "operator", "member", "", ""
    if d == "org_admin":
        if not oid:
            raise ValueError(msg.USER_CREATE_ORG_REQUIRED)
        return "operator", "admin", "", ""
    if d in ("project_member", "project_owner", "project_viewer"):
        if not pid:
            raise ValueError(msg.USER_CREATE_PROJECT_REQUIRED)
        prole = {
            "project_member": "member",
            "project_owner": "owner",
            "project_viewer": "viewer",
        }[d]
        return "operator", "member", pid, prole
    raise ValueError(msg.USER_CREATE_DUTY_INVALID)


def _resolve_create_user_org_project(
    db: Session,
    auth: AuthContext | None,
    body: UserCreate,
) -> tuple[str, str, str, str, str]:
    """返回 (platform_role, org_id, org_role, project_id, project_role)。"""
    header_org = ((getattr(auth, "org_id", "") or "") if auth else "").strip()
    pid = (body.project_id or "").strip()
    platform_role, org_role, pid, prole = expand_create_duty(
        body.duty, org_id=header_org, project_id=pid
    )
    oid = header_org if org_role else ""
    if pid:
        proj = db.get(ProjectRow, pid)
        if proj is None:
            raise LookupError(msg.PROJECT_NOT_FOUND)
        poid = (getattr(proj, "org_id", None) or "").strip()
        if oid and poid and oid != poid:
            raise ValueError(msg.USER_CREATE_PROJECT_ORG_MISMATCH)
        if not oid:
            oid = poid
        if not oid:
            raise ValueError(msg.USER_CREATE_ORG_REQUIRED)
        org_role = org_role or "member"
    if oid:
        if db.get(OrganizationRow, oid) is None:
            raise LookupError(msg.ORG_NOT_FOUND)
    return platform_role, oid, org_role, pid, prole


def _assert_can_assign_on_create(
    db: Session,
    auth: AuthContext,
    *,
    org_id: str,
    org_role: str,
    project_id: str,
    project_role: str,
) -> None:
    from ..tenancy.organizations import assert_can_manage_org, org_member_role
    from ..authz.rbac import (
        can_assign_org_role,
        can_assign_project_role,
        org_admin_elevates_project,
    )

    if org_id:
        assert_can_manage_org(db, auth, org_id)
        if not is_platform_admin(auth):
            actor = org_member_role(db, auth.user_id, org_id)
            if not can_assign_org_role(actor, org_role or "member"):
                raise PermissionError(msg.ORG_ROLE_CANNOT_ELEVATE)
    if project_id:
        if is_platform_admin(auth):
            return
        mem = db.scalars(
            select(ProjectMemberRow).where(
                ProjectMemberRow.project_id == project_id,
                ProjectMemberRow.user_id == auth.user_id,
            )
        ).first()
        org_owns = org_admin_elevates_project(db, auth, project_id=project_id)
        if org_owns:
            actor_role = "owner"
        elif mem is not None and mem.role == "owner":
            actor_role = mem.role or "owner"
        else:
            raise PermissionError(msg.PROJECT_OWNER_ADMIN_ADD)
        want = project_role
        if (org_role or "member") in ("owner", "admin"):
            want = "owner"
        if not can_assign_project_role(actor_role, want):
            raise PermissionError(msg.PROJECT_ROLE_CANNOT_ELEVATE)


def create_user(db: Session, body: UserCreate, auth: AuthContext | None = None) -> UserOut:
    validate_password_policy(body.password)
    exists = db.scalars(select(UserRow).where(UserRow.username == body.username)).first()
    if exists is not None:
        raise LookupError(msg.AUTH_USERNAME_EXISTS.format(username=body.username))

    role, org_id, org_role, project_id, project_role = _resolve_create_user_org_project(
        db, auth, body
    )
    if (
        auth is not None
        and (getattr(auth, "role", "") or "") != "admin"
        and not org_id
        and not project_id
    ):
        raise PermissionError(msg.AUTH_ADMIN_REQUIRED)
    if auth is not None and (org_id or project_id):
        _assert_can_assign_on_create(
            db,
            auth,
            org_id=org_id,
            org_role=org_role,
            project_id=project_id,
            project_role=project_role,
        )

    row = UserRow(
        id=new_id(),
        username=body.username.strip(),
        password_hash=hash_password(body.password),
        role=role,
    )
    try:
        db.add(row)
        db.flush()
        if org_id:
            already = db.scalars(
                select(OrganizationMemberRow).where(
                    OrganizationMemberRow.org_id == org_id,
                    OrganizationMemberRow.user_id == row.id,
                )
            ).first()
            if already is None:
                db.add(
                    OrganizationMemberRow(
                        id=new_id(),
                        org_id=org_id,
                        user_id=row.id,
                        role=org_role or "member",
                    )
                )
            else:
                already.role = org_role or already.role
        if project_id:
            want = project_role or "member"
            if org_role in ("owner", "admin"):
                want = "owner"
            db.add(
                ProjectMemberRow(
                    id=new_id(),
                    project_id=project_id,
                    user_id=row.id,
                    role=want,
                )
            )
        db.commit()
    except IntegrityError:
        db.rollback()
        clash = db.scalars(
            select(UserRow).where(UserRow.username == body.username.strip())
        ).first()
        if clash is not None:
            raise LookupError(msg.AUTH_USERNAME_EXISTS.format(username=body.username)) from None
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(row)
    return user_to_out(row)


def list_users(
    db: Session,
    auth: AuthContext | None = None,
    *,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[UserOut], int]:
    from ..core.list_page import slice_page

    oid = ((getattr(auth, "org_id", "") or "") if auth else "").strip()
    if oid:
        uids = list(
            db.scalars(
                select(OrganizationMemberRow.user_id).where(OrganizationMemberRow.org_id == oid)
            ).all()
        )
        if not uids:
            return [], 0
        rows = list(
            db.scalars(
                select(UserRow).where(UserRow.id.in_(uids)).order_by(UserRow.username)
            ).all()
        )
    else:
        rows = list(db.scalars(select(UserRow).order_by(UserRow.username)).all())
    filtered = [user_to_out(r) for r in rows]
    size = max(1, min(200, int(page_size)))
    pg = max(1, int(page))
    return slice_page(filtered, page=pg, page_size=size)


def update_user(
    db: Session, user_id: str, body: UserUpdate, auth: AuthContext
) -> UserOut:
    if not is_platform_admin(auth):
        raise PermissionError(msg.AUTH_ADMIN_REQUIRED)
    row = db_get(db, UserRow, user_id)
    if row is None:
        raise LookupError(msg.AUTH_USER_NOT_FOUND)
    if body.password is not None:
        validate_password_policy(body.password)
        row.password_hash = hash_password(body.password)
        from ..identity.session_tokens import revoke_all_refresh_tokens

        revoke_all_refresh_tokens(db, row.id)
    if body.role is not None:
        role = body.role.strip()
        if role not in ("admin", "operator"):
            raise ValueError(msg.AUTH_ROLE_ADMIN_OR_OPERATOR)
        row.role = role
    if body.disabled is not None:
        row.disabled = bool(body.disabled)
    db.commit()
    db.refresh(row)
    return user_to_out(row)


def delete_user(db: Session, user_id: str, auth: AuthContext) -> None:
    if auth.user_id == user_id:
        raise ValueError(msg.AUTH_CANNOT_DELETE_SELF)
    row = db_get(db, UserRow, user_id)
    if row is None:
        raise LookupError(msg.AUTH_USER_NOT_FOUND)
    # Remove foreign-key dependents before deleting the account in the same transaction.
    for model in (RefreshTokenRow, ProjectMemberRow, OrganizationMemberRow, ResourceAclRow):
        db.execute(delete(model).where(model.user_id == user_id))
    db.delete(row)
    db.commit()


def artifact_to_out(row: ArtifactRow, *, reused: bool = False) -> ArtifactOut:
    import json

    warnings: list[str] = []
    errors: list[str] = []
    required_runtime_version = ""
    try:
        notes = json.loads(getattr(row, "manifest_notes_json", None) or "[]")
        if isinstance(notes, dict):
            warnings = [str(x) for x in (notes.get("warnings") or [])]
            errors = [str(x) for x in (notes.get("errors") or [])]
            required_runtime_version = str(
                notes.get("required_runtime_version") or ""
            ).strip()
        elif isinstance(notes, list):
            warnings = [str(x) for x in notes]
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return ArtifactOut(
        id=row.id,
        name=row.name or "",
        filename=row.filename or "",
        size_bytes=int(row.size_bytes or 0),
        uploaded_by=row.uploaded_by or "",
        project_id=row.project_id or "",
        created_at=row.created_at,
        manifest_status=getattr(row, "manifest_status", "") or "",
        manifest_version=getattr(row, "manifest_version", "") or "",
        required_runtime_version=required_runtime_version,
        manifest_warnings=warnings,
        manifest_errors=errors,
        sha256=str(getattr(row, "sha256", "") or ""),
        reused=reused,
    )


def list_artifact_entries(row: ArtifactRow) -> list[dict[str, str]]:
    """从已解压目录或 zip 列出可执行入口。"""
    import os

    from autopilot_platform.core.entries import list_runnable_entries, list_runnable_entries_in_zip

    extract = (row.extract_path or "").strip()
    if extract and os.path.isdir(extract):
        return list_runnable_entries(extract)
    stored = (row.stored_path or "").strip()
    if not stored:
        raise FileNotFoundError(msg.ARTIFACT_STORAGE_MISSING)
    path = get_artifact_store().resolve_zip_path(stored)
    return list_runnable_entries_in_zip(str(path))


def _artifact_tree_sha256(extract_path: str) -> str:
    """解压目录的内容哈希，排除 manifest.json。清单每次打包都会变，不能参与去重。"""
    root = Path(extract_path or "")
    if not root.is_dir():
        return ""
    from .artifact_manifest import compute_artifact_content_sha256, find_manifest_path

    manifest = find_manifest_path(str(root))
    has_payload = any(
        path.is_file() and (manifest is None or path.resolve() != manifest.resolve())
        for path in root.rglob("*")
    )
    if not has_payload:
        return ""
    return compute_artifact_content_sha256(root, manifest_path=manifest)


def save_artifact_zip(
    db: Session,
    *,
    upload_name: str,
    data: bytes | None = None,
    source_path: str | Path | None = None,
    display_name: str,
    uploaded_by: str,
    project_id: str = "",
    auth: AuthContext | None = None,
) -> ArtifactOut:
    source = Path(source_path) if source_path else None
    size_bytes = source.stat().st_size if source is not None and source.is_file() else len(data or b"")
    if size_bytes <= 0:
        raise ValueError(msg.UPLOAD_EMPTY)
    from ..core.settings import artifact_max_mb

    max_mb = artifact_max_mb()
    if max_mb > 0 and size_bytes > max_mb * 1024 * 1024:
        raise ValueError(f"文件过大：上限 {max_mb} MB（MC_ARTIFACT_MAX_MB）")
    pid = (project_id or "").strip()
    if auth is not None:
        assert_can_write_project(db, auth, pid)
    aid = new_id()
    store = get_artifact_store()
    if source is not None:
        stored_uri, extract_path = store.put_zip_path(aid, source)
    else:
        stored_uri, extract_path = store.put_zip(aid, data or b"")
    # 按解压后的文件内容去重。zip 时间戳每次打包都会变，按压缩包字节哈希对不上同一工程。
    sha = _artifact_tree_sha256(extract_path)
    existing = db.scalars(
        select(ArtifactRow)
        .where(ArtifactRow.sha256 == sha, ArtifactRow.project_id == pid)
        .order_by(ArtifactRow.created_at.desc())
    ).first()
    if existing is not None and sha:
        try:
            store.delete(aid, stored_uri)
        except (OSError, RuntimeError, ValueError, TypeError):
            pass
        if auth is not None:
            assert_can_access_resource(
                db,
                auth,
                resource_type="artifact",
                resource_id=str(existing.id),
                project_id=str(existing.project_id or ""),
                owner_username=str(existing.uploaded_by or ""),
            )
        return artifact_to_out(existing, reused=True)
    import json

    row = ArtifactRow(
        id=aid,
        name=(display_name or Path(upload_name).stem or aid).strip(),
        filename=upload_name or "project.zip",
        stored_path=stored_uri,
        extract_path=extract_path,
        size_bytes=size_bytes,
        uploaded_by=uploaded_by or "",
        project_id=pid,
        sha256=sha,
    )
    # 校验 ArtifactManifest（默认不阻断；MC_REQUIRE_ARTIFACT_MANIFEST=1 时要求 valid）
    try:
        from .artifact_manifest import validate_artifact_manifest

        result = validate_artifact_manifest(extract_path or "", expected_project_id=pid)
        row.manifest_status = str(result.get("status") or "")
        row.manifest_version = str(result.get("artifact_version") or "")
        row.manifest_notes_json = json.dumps(
            {
                "warnings": result.get("warnings") or [],
                "errors": result.get("errors") or [],
                "path": result.get("path") or "",
                "required_runtime_version": result.get("required_runtime_version") or "",
            },
            ensure_ascii=False,
        )
    except Exception as exc:  # noqa: BLE001
        result = {
            "status": "invalid",
            "warnings": [],
            "errors": [f"manifest 校验异常: {exc}"],
        }
        row.manifest_status = "invalid"
        row.manifest_notes_json = json.dumps(
            {"warnings": [], "errors": result["errors"]},
            ensure_ascii=False,
        )

    from ..core.settings import require_artifact_manifest

    if require_artifact_manifest() and (row.manifest_status or "") != "valid":
        try:
            store.delete(aid, stored_uri)
        except (OSError, RuntimeError, ValueError, TypeError):
            pass
        detail_bits = list(result.get("errors") or []) if isinstance(result, dict) else []
        if not detail_bits and isinstance(result, dict):
            detail_bits = list(result.get("warnings") or [])
        detail = "; ".join(str(x) for x in detail_bits[:5]) or (
            row.manifest_status or "missing"
        )
        raise ValueError(msg.ARTIFACT_MANIFEST_REQUIRED.format(detail=detail))

    db.add(row)
    db.commit()
    db.refresh(row)
    return artifact_to_out(row)


def list_artifacts(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 50,
    project_id: str = "",
    auth: AuthContext | None = None,
) -> tuple[list[ArtifactOut], int]:
    from ..authz.acl import can_access_resource
    from ..core.list_page import slice_page
    from ..services.shared.pagination import paginate

    pid = (project_id or "").strip()
    stmt = select(ArtifactRow).order_by(ArtifactRow.created_at.desc())
    if pid:
        if auth is not None:
            assert_can_access_project(db, auth, pid)
        stmt = stmt.where(ArtifactRow.project_id == pid)
    size = max(1, min(200, int(page_size)))
    pg = max(1, int(page))
    if pid or auth is None:
        rows, total = paginate(db, stmt, page=pg, page_size=size)
        return [artifact_to_out(r) for r in rows], total
    rows = list(db.scalars(stmt).all())
    filtered = [
        artifact_to_out(r)
        for r in rows
        if can_access_resource(
            db,
            auth,
            resource_type="artifact",
            resource_id=str(r.id),
            project_id=str(r.project_id or ""),
            owner_username=str(r.uploaded_by or ""),
        )
    ]
    return slice_page(filtered, page=pg, page_size=size)


def get_artifact(db: Session, artifact_id: str) -> ArtifactRow | None:
    return db_get(db, ArtifactRow, artifact_id)


def _artifact_has_active_references(db: Session, artifact_id: str) -> bool:
    from autopilot_platform.core.constants import JobStatus
    from ..core.models import DeviceRow, JobRow, ScheduleRow

    jobs = list(db.scalars(select(JobRow).where(JobRow.artifact_id == artifact_id)).all())
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
            ScheduleRow.artifact_id == artifact_id,
            ScheduleRow.enabled.is_(True),
        )
    ).first() is not None


def delete_artifact(db: Session, artifact_id: str, auth: AuthContext | None = None) -> None:
    row = db_get(db, ArtifactRow, artifact_id)
    if row is None:
        raise LookupError(msg.ARTIFACT_NOT_FOUND)
    if auth is not None:
        assert_can_access_resource(
            db,
            auth,
            resource_type="artifact",
            resource_id=str(row.id),
            project_id=str(row.project_id or ""),
            owner_username=str(row.uploaded_by or ""),
            need_write=True,
        )
    if _artifact_has_active_references(db, artifact_id):
        raise ValueError("制品仍被活动任务或已启用计划引用，不能删除")
    store = get_artifact_store()
    stored_path = str(row.stored_path or "")
    db.delete(row)
    db.commit()
    store.delete(str(row.id), stored_path)


def purge_artifacts(
    db: Session,
    *,
    older_than_days: int | None = None,
) -> tuple[int, int]:
    """删除早于 N 天的制品；返回 (deleted, days_used)。"""
    from datetime import timedelta

    from ..core.models import utcnow
    from ..core.settings import artifact_retention_days

    days = artifact_retention_days() if older_than_days is None else max(0, int(older_than_days))
    if days <= 0:
        return 0, days
    cutoff = utcnow() - timedelta(days=days)
    rows = list(
        db.scalars(select(ArtifactRow).where(ArtifactRow.created_at < cutoff)).all()
    )
    rows = [row for row in rows if not _artifact_has_active_references(db, str(row.id))]
    stored = [(str(row.id), str(row.stored_path or "")) for row in rows]
    for row in rows:
        db.delete(row)
    db.commit()
    store = get_artifact_store()
    for artifact_id, stored_path in stored:
        store.delete(artifact_id, stored_path)
    return len(rows), days

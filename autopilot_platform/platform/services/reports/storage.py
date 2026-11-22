"""报告列表、对比与存储。"""

from __future__ import annotations

import io
import json
import logging
import shutil
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from ...core import api_messages as msg

from sqlalchemy import select
from sqlalchemy.orm import Session

from .compare import compare_case_lists, refine_verdict
from autopilot_platform.core.schemas import ReportIndex

from autopilot_platform.core.constants import JobStatus
from ...core.list_page import slice_page
from ...core.models import ArtifactRow, AppBuildRow, JobRow, ReportRow, db_get, new_id, utcnow
from ...core.settings import job_report_retention_days, reports_root
from ..execution.job_claims import lock_job_upload_claim
from ..shared.pagination import paginate

log = logging.getLogger(__name__)


def _version_fields_from_job(db: Session, job: JobRow) -> dict:
    """从 Job 解析制品/应用资源快照（结档时写入 reports）。"""
    artifact_id = (getattr(job, "artifact_id", None) or "").strip() or None
    app_build_id = (getattr(job, "app_build_id", None) or "").strip() or None
    artifact_name = ""
    app_build_name = ""
    app_version_name = ""
    app_platform = ""
    if artifact_id:
        art = db_get(db, ArtifactRow, artifact_id)
        if art is not None:
            artifact_name = str(art.name or art.filename or "")
    if app_build_id:
        build = db_get(db, AppBuildRow, app_build_id)
        if build is not None:
            app_build_name = str(build.name or build.filename or "")
            app_version_name = str(build.version_name or "")
            app_platform = str(build.platform or "")
    if not app_platform:
        app_platform = str(job.platform or "")
    return {
        "artifact_id": artifact_id,
        "artifact_name": artifact_name,
        "app_build_id": app_build_id,
        "app_build_name": app_build_name,
        "app_version_name": app_version_name,
        "app_platform": app_platform,
    }


def apply_version_snapshot(db: Session, rep: ReportRow, job: JobRow) -> None:
    """把任务关联的制品/应用版本冻结到报告行。"""
    meta = _version_fields_from_job(db, job)
    rep.artifact_id = meta["artifact_id"]
    rep.artifact_name = meta["artifact_name"]
    rep.app_build_id = meta["app_build_id"]
    rep.app_build_name = meta["app_build_name"]
    rep.app_version_name = meta["app_version_name"]
    rep.app_platform = meta["app_platform"]


def report_to_index(db: Session, r: ReportRow, job: JobRow | None = None) -> ReportIndex:
    if job is None:
        job = db_get(db, JobRow, r.job_id)
    # 旧报告无冻结字段时，实时回退 Job（尽力而为）
    artifact_id = getattr(r, "artifact_id", None) or (job.artifact_id if job else None)
    app_build_id = getattr(r, "app_build_id", None) or (
        getattr(job, "app_build_id", None) if job else None
    )
    artifact_name = getattr(r, "artifact_name", "") or ""
    app_build_name = getattr(r, "app_build_name", "") or ""
    app_version_name = getattr(r, "app_version_name", "") or ""
    app_platform = getattr(r, "app_platform", "") or ""
    if job is not None and (not artifact_name or not app_build_name) and (
        artifact_id or app_build_id
    ):
        live = _version_fields_from_job(db, job)
        if not artifact_name:
            artifact_name = live["artifact_name"]
        if not app_build_name:
            app_build_name = live["app_build_name"]
        if not app_version_name:
            app_version_name = live["app_version_name"]
        if not app_platform:
            app_platform = live["app_platform"]
    return ReportIndex(
        job_id=r.job_id,
        report_path=r.report_path or "",
        passed=r.passed,
        failed=r.failed,
        total=r.total,
        duration_ms=r.duration_ms,
        summary=r.summary or "",
        stored=bool((r.stored_path or "").strip()),
        artifact_id=artifact_id,
        artifact_name=artifact_name,
        app_build_id=app_build_id,
        app_build_name=app_build_name,
        app_version_name=app_version_name,
        app_platform=app_platform or (job.platform if job else "") or "",
        job_name=(job.name if job else "") or "",
        project_id=(job.project_id if job else "") or "",
        platform=(job.platform if job else "") or "",
    )


def list_reports(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 50,
    project_id: str = "",
    artifact_id: str = "",
    app_build_id: str = "",
    platform: str = "",
    auth=None,
) -> tuple[list[ReportIndex], int]:
    from ...authz.acl import can_access_resource

    q = select(ReportRow).order_by(ReportRow.created_at.desc())
    pid = (project_id or "").strip()
    aid = (artifact_id or "").strip()
    bid = (app_build_id or "").strip()
    plat = (platform or "").strip().lower()
    if pid and auth is not None:
        from ...tenancy.projects import assert_can_access_project

        assert_can_access_project(db, auth, pid)
    need_job_join = bool(pid or plat)
    if need_job_join or aid or bid:
        q = q.outerjoin(JobRow, ReportRow.job_id == JobRow.id)
    if pid:
        q = q.where(JobRow.project_id == pid)
    if plat:
        q = q.where(JobRow.platform == plat)
    if aid:
        q = q.where(
            (ReportRow.artifact_id == aid)
            | ((ReportRow.artifact_id.is_(None)) & (JobRow.artifact_id == aid))
        )
    if bid:
        q = q.where(
            (ReportRow.app_build_id == bid)
            | ((ReportRow.app_build_id.is_(None)) & (JobRow.app_build_id == bid))
        )
    size = max(1, min(200, int(page_size)))
    pg = max(1, int(page))
    if auth is None or pid:
        rows, total = paginate(db, q, page=pg, page_size=size)
        return [report_to_index(db, r) for r in rows], total
    rows = list(db.scalars(q).all())
    filtered: list[ReportIndex] = []
    for r in rows:
        job = db_get(db, JobRow, r.job_id)
        if job is None:
            continue
        if not can_access_resource(
            db,
            auth,
            resource_type="job",
            resource_id=job.id,
            project_id=job.project_id or "",
            owner_username=job.created_by or "",
        ):
            continue
        filtered.append(report_to_index(db, r, job))
    return slice_page(filtered, page=pg, page_size=size)


def _report_snapshot(db: Session, job_id: str, auth=None) -> dict:
    from ...authz.acl import assert_can_access_resource

    jid = (job_id or "").strip()
    if not jid:
        raise ValueError(msg.REPORT_JOB_ID_REQUIRED)
    job = db_get(db, JobRow, jid)
    if job is None:
        raise LookupError(msg.JOB_NOT_FOUND)
    if auth is not None:
        assert_can_access_resource(
            db,
            auth,
            resource_type="job",
            resource_id=job.id,
            project_id=job.project_id or "",
            owner_username=job.created_by or "",
        )
    rep = job.report
    if rep is None:
        raise LookupError(msg.REPORT_NOT_FOUND_JOB.format(job_id=jid))
    idx = report_to_index(db, rep, job)
    return {
        "job_id": job.id,
        "job_name": job.name or "",
        "job_status": job.status or "",
        "parent_job_id": job.parent_job_id or "",
        "platform": job.platform or "",
        "passed": int(rep.passed or 0),
        "failed": int(rep.failed or 0),
        "total": int(rep.total or 0),
        "duration_ms": int(rep.duration_ms or 0),
        "summary": rep.summary or "",
        "stored": bool((rep.stored_path or "").strip()),
        "created_at": job.created_at.isoformat() if job.created_at else "",
        "artifact_id": idx.artifact_id or "",
        "artifact_name": idx.artifact_name or "",
        "app_build_id": idx.app_build_id or "",
        "app_build_name": idx.app_build_name or "",
        "app_version_name": idx.app_version_name or "",
        "app_platform": idx.app_platform or "",
    }


def _load_result_cases(db: Session, job_id: str) -> list | None:
    """读取已上传 result.json 的 cases[]；缺失则 None（对比仍可用汇总数字）。"""
    try:
        path = resolve_job_result_json_path(db, job_id)
    except (LookupError, FileNotFoundError, OSError):
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    cases = payload.get("cases")
    return cases if isinstance(cases, list) else None


def compare_reports(db: Session, left_job_id: str, right_job_id: str, auth=None) -> dict:
    """对比两个任务的报告指标（right - left 为 delta），并附用例级 diff。"""
    left_id = (left_job_id or "").strip()
    right_id = (right_job_id or "").strip()
    if not left_id or not right_id:
        raise ValueError(msg.REPORT_COMPARE_IDS_REQUIRED)
    if left_id == right_id:
        raise ValueError(msg.REPORT_COMPARE_SAME)
    left = _report_snapshot(db, left_id, auth=auth)
    right = _report_snapshot(db, right_id, auth=auth)
    keys = ("passed", "failed", "total", "duration_ms")
    delta: dict[str, int | float | None] = {k: int(right[k]) - int(left[k]) for k in keys}

    def pass_rate(snapshot: dict) -> float | None:
        if not snapshot["total"]:
            return None
        return float(snapshot["passed"]) / float(snapshot["total"])

    lp, rp = pass_rate(left), pass_rate(right)
    delta["pass_rate"] = None if lp is None or rp is None else round(rp - lp, 4)
    verdict = "same"
    failed_d = int(delta["failed"] or 0)
    passed_d = int(delta["passed"] or 0)
    duration_d = int(delta["duration_ms"] or 0)
    if failed_d < 0 <= passed_d:
        verdict = "improved"
    elif failed_d > 0 or (passed_d < 0 <= failed_d):
        verdict = "regressed"
    elif duration_d != 0 and failed_d == 0 and passed_d == 0:
        verdict = "timing_only"
    same_app = (left.get("app_build_id") or "") == (right.get("app_build_id") or "")
    same_art = (left.get("artifact_id") or "") == (right.get("artifact_id") or "")
    left_cases = _load_result_cases(db, left_id)
    right_cases = _load_result_cases(db, right_id)
    available = left_cases is not None and right_cases is not None
    case_diff = compare_case_lists(left_cases or [], right_cases or [])
    if available:
        verdict = refine_verdict(verdict, case_diff)
    return {
        "left": left,
        "right": right,
        "delta": delta,
        "verdict": verdict,
        "same_app_build": same_app,
        "same_artifact": same_art,
        "cases": {
            "available": available,
            **case_diff,
        },
    }


def store_job_report(
    db: Session,
    job_id: str,
    *,
    data: bytes | None = None,
    source_path=None,
    filename: str = "report.html",
    runner_id: str,
    claimed_at: datetime | None,
) -> ReportIndex:
    """Store a report or its evidence for the current Runner claim."""
    lock_job_upload_claim(db, job_id, runner_id, claimed_at)
    row = db_get(db, JobRow, job_id)
    if row is None:
        raise LookupError(msg.JOB_NOT_FOUND)
    source = Path(source_path) if source_path else None
    size_bytes = source.stat().st_size if source is not None and source.is_file() else len(data or b"")
    if size_bytes <= 0:
        raise ValueError(msg.REPORT_EMPTY)
    rep = row.report
    if rep is None:
        rep = ReportRow(id=new_id(), job_id=row.id)
        db.add(rep)
        row.report = rep
    dest_dir = reports_root() / job_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    name = (filename or "").strip().lower()
    if name.endswith(".zip") or name == "evidence.zip":

        ev_root = dest_dir / "evidence"
        if ev_root.exists():
            shutil.rmtree(ev_root, ignore_errors=True)
        ev_root.mkdir(parents=True, exist_ok=True)
        raw = source.read_bytes() if source is not None else (data or b"")
        max_entries = 2000
        max_total_bytes = 512 * 1024 * 1024
        total_bytes = 0
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                infos = zf.infolist()
                if len(infos) > max_entries:
                    raise ValueError(f"证据压缩包条目过多（>{max_entries}）")
                for info in infos:
                    if info.is_dir():
                        continue
                    # 规范化并拒绝路径穿越
                    rel = info.filename.replace("\\", "/").lstrip("/")
                    if ".." in rel.split("/"):
                        continue
                    # 统一落到 evidence/ 下（zip 内可能已带 reports/evidence/ 前缀）
                    if rel.startswith("reports/evidence/"):
                        rel = rel[len("reports/evidence/") :]
                    elif rel.startswith("evidence/"):
                        rel = rel[len("evidence/") :]
                    target = (ev_root / rel).resolve()
                    try:
                        target.relative_to(ev_root.resolve())
                    except ValueError:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    chunk_data = zf.read(info)
                    total_bytes += len(chunk_data)
                    if total_bytes > max_total_bytes:
                        raise ValueError("证据压缩包解压总大小超出限制")
                    target.write_bytes(chunk_data)
        except zipfile.BadZipFile as exc:
            raise ValueError(f"无效的证据压缩包：{exc}") from exc
        # 报告索引仍返回当前 ReportIndex（evidence 为附属）
        apply_version_snapshot(db, rep, row)
        db.commit()
        db.refresh(rep)
        return report_to_index(db, rep, row)
    if name.endswith(".json") or name == "result.json":
        path = dest_dir / "result.json"
        if source is not None:

            shutil.copyfile(source, path)
            json_data = path.read_bytes()
        else:
            json_data = data or b""
            path.write_bytes(json_data)
        rep.result_json_path = str(path.resolve())
        # 尝试用 suite 摘要补齐计数（若尚未有）；有 logical_case_id 则回写设计态
        try:
            payload = json.loads(json_data.decode("utf-8"))
            suite = payload.get("suite") if isinstance(payload, dict) else None
            if isinstance(suite, dict):
                if not rep.total:
                    rep.passed = int(suite.get("passed") or 0)
                    rep.failed = int(suite.get("failed") or 0)
                    rep.total = int(suite.get("total") or 0)
                    rep.duration_ms = int(suite.get("duration_ms") or 0)
                    rep.summary = str(suite.get("summary") or rep.summary or "")
            if isinstance(payload, dict):
                try:
                    from ..design.automation_sync import apply_result_json_to_logical_cases  # 延迟：仅有 logical_case 时回写

                    apply_result_json_to_logical_cases(
                        db, payload, project_id=str(row.project_id or "")
                    )
                except (OSError, RuntimeError, TypeError, ValueError, LookupError) as exc:
                    log.warning(
                        "automation_status sync from result.json failed: %s", exc
                    )
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            pass
    else:
        path = dest_dir / "report.html"
        if source is not None:

            shutil.copyfile(source, path)
        else:
            path.write_bytes(data or b"")
        rep.stored_path = str(path.resolve())
        if not rep.report_path:
            rep.report_path = filename or "report.html"

    apply_version_snapshot(db, rep, row)
    db.commit()
    db.refresh(rep)
    return report_to_index(db, rep, row)


def resolve_job_result_json_path(db: Session, job_id: str):
    row = db_get(db, JobRow, job_id)
    if row is None or row.report is None:
        raise LookupError(msg.REPORT_NOT_FOUND)
    stored = (getattr(row.report, "result_json_path", None) or "").strip()
    if not stored:
        # 兼容：同目录约定文件名
        candidate = reports_root() / job_id / "result.json"
        if candidate.is_file():
            return candidate.resolve()
        raise FileNotFoundError("result.json 尚未上传")
    root = reports_root().resolve()
    p = Path(stored).resolve()
    try:
        p.relative_to(root)
    except ValueError as exc:
        raise FileNotFoundError(msg.REPORT_PATH_INVALID) from exc
    if not p.is_file():
        raise FileNotFoundError(stored)
    return p


def resolve_job_report_path(db: Session, job_id: str):
    row = db_get(db, JobRow, job_id)
    if row is None or row.report is None:
        raise LookupError(msg.REPORT_NOT_FOUND)
    stored = (row.report.stored_path or "").strip()
    if not stored:
        raise FileNotFoundError(msg.REPORT_FILE_MISSING)
    root = reports_root().resolve()
    p = Path(stored).resolve()
    try:
        p.relative_to(root)
    except ValueError as exc:
        raise FileNotFoundError(msg.REPORT_PATH_INVALID) from exc
    if not p.is_file():
        raise FileNotFoundError(stored)
    return p


def resolve_job_evidence_file(db: Session, job_id: str, rel_path: str):
    """解析 reports_root/{job_id}/evidence 下的安全相对路径。"""
    row = db_get(db, JobRow, job_id)
    if row is None:
        raise LookupError(msg.JOB_NOT_FOUND)
    raw = (rel_path or "").replace("\\", "/").lstrip("/")
    if not raw or ".." in raw.split("/"):
        raise FileNotFoundError(msg.REPORT_PATH_INVALID)
    # 兼容 result.json 中的 reports/evidence/... 前缀
    for prefix in ("reports/evidence/", "evidence/"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    if not raw or ".." in raw.split("/"):
        raise FileNotFoundError(msg.REPORT_PATH_INVALID)
    root = (reports_root() / job_id / "evidence").resolve()
    if not root.is_dir():
        raise FileNotFoundError("evidence 尚未上传")
    target = (root / raw).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise FileNotFoundError(msg.REPORT_PATH_INVALID) from exc
    if not target.is_file():
        raise FileNotFoundError(raw)
    return target


def list_job_evidence_files(db: Session, job_id: str, *, limit: int = 200) -> list[dict[str, str]]:
    """列举已解压的 evidence 文件（相对 evidence/ 根）。无目录时返回空列表。"""
    row = db_get(db, JobRow, job_id)
    if row is None:
        raise LookupError(msg.JOB_NOT_FOUND)
    root = (reports_root() / job_id / "evidence").resolve()
    if not root.is_dir():
        return []
    cap = max(1, min(int(limit or 200), 500))
    out: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if ".." in rel.split("/"):
            continue
        low = rel.lower()
        if low.endswith(".mp4"):
            kind = "video"
        elif low.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            kind = "image"
        else:
            kind = "file"
        out.append({"path": rel, "kind": kind})
        if len(out) >= cap:
            break
    return out


def purge_job_reports(
    db: Session,
    *,
    older_than_days: int | None = None,
) -> tuple[int, int]:
    """删除早于 N 天的**终态** Job 报告目录与 ReportRow；返回 (deleted, days_used)。

    不删 JobRow；不碰 claimed/running；不碰 job_logs_root。
    """



    days = (
        job_report_retention_days()
        if older_than_days is None
        else max(0, int(older_than_days))
    )
    if days <= 0:
        return 0, days
    cutoff = utcnow() - timedelta(days=days)
    terminal = frozenset(
        {
            JobStatus.SUCCEEDED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        }
    )
    rows = list(
        db.scalars(select(ReportRow).where(ReportRow.created_at < cutoff)).all()
    )
    to_delete: list[ReportRow] = []
    for rep in rows:
        job = db_get(db, JobRow, rep.job_id)
        if job is None or (job.status or "") in terminal:
            to_delete.append(rep)
    job_ids = [str(r.job_id) for r in to_delete]
    for rep in to_delete:
        db.delete(rep)
    db.commit()
    root = reports_root()
    for jid in job_ids:
        dest = root / jid
        if dest.is_dir():
            shutil.rmtree(dest, ignore_errors=True)
    return len(to_delete), days

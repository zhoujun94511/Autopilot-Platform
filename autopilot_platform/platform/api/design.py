"""设计域 API：需求 / 逻辑用例 / 知识 / 文档；配置与 Chat 见子路由模块。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from ..auth import AuthContext, require_auth
from ..core.db import get_session
from ..core.list_page import normalize_page_params
from ..ops import audit as audit_svc
from ..design.design_schemas import (
    AnalysisHistoryListPage,
    DesignDocumentListPage,
    DesignDocumentOut,
    DocumentBatchDeleteIn,
    DocumentPreviewOut,
    KnowledgeBatchDeleteIn,
    KnowledgeItemCreate,
    KnowledgeItemOut,
    KnowledgeItemUpdate,
    KnowledgeListPage,
    KnowledgeRebuildIn,
    KnowledgeSearchIn,
    KnowledgeSearchOut,
    LogicalCaseBatchGenerateIn,
    LogicalCaseCreate,
    LogicalCaseEnqueueJobIn,
    LogicalCaseExportBundle,
    LogicalCaseGenerateIn,
    LogicalCaseListPage,
    LogicalCaseOut,
    LogicalCaseUpdate,
    RequirementBatchDeleteIn,
    RequirementCreate,
    RequirementListPage,
    RequirementOut,
    RequirementUpdate,
    TestPointListPage,
)
from ..services.design.cases import crud as case_svc
from ..services.design.cases import generation as generation_svc
from ..services.design.cases import webhooks as case_webhooks
from ..services.design import access as design_access
from ..services.design.documents import crud as doc_svc
from ..services.design.documents import import_batch as document_import_svc
from ..services.design.documents.analysis import persist as document_analysis_history_svc
from ..services.design.documents.analysis import pipeline as document_analysis_svc
from ..services.design import export as export_svc
from ..services.design.knowledge import crud as knowledge_svc
from ..services.design.knowledge import importing as knowledge_import_svc
from ..services.design.requirements import crud as req_svc
from ..services.design.requirements import importing as req_import_svc
from ..services.design import test_points as test_points_svc

router = APIRouter(tags=["design"])

from . import design_chat_routes, design_config, design_dashboard

router.include_router(design_dashboard.router)
router.include_router(design_config.router)
router.include_router(design_chat_routes.router)


@router.post("/design/requirements", response_model=RequirementOut)
def api_create_requirement(
    body: RequirementCreate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> RequirementOut:
    design_access.require_design_user(auth)
    design_access.ensure_project_write(db, auth, body.project_id)
    out = req_svc.create_requirement(db, body, auth)
    audit_svc.write_audit_auth(
        db, auth, action="design.requirement.create", resource_type="requirement", resource_id=out.id
    )
    return out


@router.get("/design/requirements")
def api_list_requirements(
    project_id: str | None = Query(default=None),
    source_document_id: str | None = Query(default=None),
    q: str | None = Query(default=None, description="标题/编号/内容关键词"),
    priority: str | None = Query(default=None),
    sort_by: str | None = Query(default="created_at"),
    order: str = Query(default="desc"),
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> list[RequirementOut] | RequirementListPage:
    """无 page 时返回 list（兼容旧客户端）；带 page 时返回分页对象。"""
    scope = design_access.resolve_list_scope(db, auth, project_id)
    items, total, page_n, size = req_svc.query_requirements(
        db,
        project_ids=scope,
        source_document_id=source_document_id,
        q=q,
        priority=priority,
        sort_by=sort_by,
        order=order,
        page=page,
        page_size=page_size,
    )
    if page is None:
        return items
    return RequirementListPage(items=items, total=total, page=page_n or 1, page_size=size)


@router.get("/design/requirements/export")
def api_export_requirements(
    project_id: str | None = Query(default=None),
    source_document_id: str | None = Query(default=None),
    fmt: str = Query(default="excel", alias="format"),
    req_ids: str | None = Query(default=None, description="逗号分隔"),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
):
    scope = design_access.resolve_list_scope(db, auth, project_id)
    ids = [x.strip() for x in (req_ids or "").split(",") if x.strip()] or None
    return export_svc.export_requirements(
        db,
        project_id=project_id,
        project_ids=scope,
        source_document_id=source_document_id,
        req_ids=ids,
        fmt=fmt,
    )


@router.post("/design/requirements/batch-delete")
def api_batch_delete_requirements(
    body: RequirementBatchDeleteIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    design_access.require_design_user(auth)
    if not body.item_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="item_ids 不能为空")
    # 写权限在 service 层对每条资源预检（防跨项目夹带）
    out = req_svc.batch_delete_requirements(db, body.item_ids, auth)
    audit_svc.write_audit_auth(
        db,
        auth,
        action="design.requirement.batch_delete",
        resource_type="requirement",
        detail=out.get("message") or "",
    )
    return out


@router.get("/design/requirements/{req_id}", response_model=RequirementOut)
def api_get_requirement(
    req_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> RequirementOut:
    try:
        out = req_svc.get_requirement(db, req_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    design_access.ensure_row_project_access(db, auth, out.project_id)
    return out


@router.patch("/design/requirements/{req_id}", response_model=RequirementOut)
def api_update_requirement(
    req_id: str,
    body: RequirementUpdate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> RequirementOut:
    design_access.require_design_user(auth)
    try:
        existing = req_svc.get_requirement(db, req_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    design_access.ensure_row_project_write(db, auth, existing.project_id)
    try:
        out = req_svc.update_requirement(db, req_id, body, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db, auth, action="design.requirement.update", resource_type="requirement", resource_id=out.id
    )
    return out


@router.delete("/design/requirements/{req_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_delete_requirement(
    req_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> Response:
    design_access.require_design_user(auth)
    try:
        existing = req_svc.get_requirement(db, req_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    design_access.ensure_row_project_write(db, auth, existing.project_id)
    try:
        req_svc.delete_requirement(db, req_id, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db, auth, action="design.requirement.delete", resource_type="requirement", resource_id=req_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/design/requirements/import")
async def api_import_requirements(
    project_id: str = Form(...),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    """结构化需求批量导入（CSV/JSON/MD/TXT/YAML）。"""
    design_access.require_design_user(auth)
    design_access.ensure_project_write(db, auth, project_id)
    payload: list[tuple[str, bytes]] = []
    for f in files or []:
        name = (f.filename or "").strip() or "upload.bin"
        raw = await f.read()
        payload.append((name, raw))
    try:
        out = req_import_svc.import_requirement_files(
            db, project_id=project_id, files=payload, auth=auth
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db,
        auth,
        action="design.requirement.import",
        resource_type="requirement",
        resource_id=project_id,
        detail=out.get("message") or "",
    )
    return out


@router.post("/design/logical-cases", response_model=LogicalCaseOut)
def api_create_logical_case(
    body: LogicalCaseCreate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> LogicalCaseOut:
    design_access.require_design_user(auth)
    design_access.ensure_project_write(db, auth, body.project_id)
    try:
        out = case_svc.create_logical_case(db, body, auth)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db,
        auth,
        action="design.logical_case.create",
        resource_type="logical_case",
        resource_id=out.logical_case_id,
    )
    return out


@router.get("/design/logical-cases")
def api_list_logical_cases(
    project_id: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    automation_status: str | None = Query(default=None),
    q: str | None = Query(default=None, description="标题/编号/描述关键词"),
    sort_by: str | None = Query(default="updated_at"),
    order: str = Query(default="desc"),
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> list[LogicalCaseOut] | LogicalCaseListPage:
    """无 page 时返回 list（兼容旧客户端）；带 page 时返回分页对象。"""
    scope = design_access.resolve_list_scope(db, auth, project_id)
    items, total, page_n, size = case_svc.query_logical_cases(
        db,
        project_ids=scope,
        review_status=review_status,
        automation_status=automation_status,
        q=q,
        sort_by=sort_by,
        order=order,
        page=page,
        page_size=page_size,
    )
    if page is None:
        return items
    return LogicalCaseListPage(items=items, total=total, page=page_n or 1, page_size=size)


@router.post("/design/logical-cases/export")
def api_export_logical_cases_file(
    body: dict | None = None,
    project_id: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    fmt_q: str = Query(default="excel", alias="format"),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
):
    """导出逻辑用例 Excel/CSV。"""
    payload = body if isinstance(body, dict) else {}
    pid = (payload.get("project_id") or project_id or "").strip() or None
    rs = (payload.get("review_status") or review_status or "").strip() or None
    fmt = str(payload.get("format") or fmt_q or "excel").strip()
    case_ids = payload.get("case_ids") if isinstance(payload.get("case_ids"), list) else None
    scope = design_access.resolve_list_scope(db, auth, pid)
    return export_svc.export_logical_cases(
        db,
        project_id=pid,
        project_ids=scope,
        review_status=rs,
        case_ids=case_ids,
        fmt=fmt,
    )


@router.get("/design/logical-cases/template")
def api_logical_cases_template(fmt: str = Query(default="excel", alias="format")):
    return export_svc.cases_template(fmt=fmt)


@router.post("/design/logical-cases/generate", response_model=list[LogicalCaseOut])
def api_generate_logical_cases(
    body: LogicalCaseGenerateIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> list[LogicalCaseOut]:
    design_access.require_design_user(auth)
    design_access.ensure_project_write(db, auth, body.project_id)
    if not (body.requirement_text or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="requirement_text 不能为空")
    out = generation_svc.generate_logical_cases(db, body, auth)
    audit_svc.write_audit_auth(
        db,
        auth,
        action="design.logical_case.generate",
        resource_type="project",
        resource_id=body.project_id,
        detail=f"count={len(out)}",
    )
    return out


@router.post("/design/logical-cases/batch-generate")
def api_batch_generate_logical_cases(
    body: LogicalCaseBatchGenerateIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    design_access.require_design_user(auth)
    design_access.ensure_project_write(db, auth, body.project_id)
    try:
        out = generation_svc.batch_generate_logical_cases(db, body, auth)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db,
        auth,
        action="design.logical_case.batch_generate",
        resource_type="project",
        resource_id=body.project_id,
        detail=out.get("message") or "",
    )
    return out


@router.post("/design/logical-cases/batch-delete")
def api_batch_delete_logical_cases(
    body: dict,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    design_access.require_design_user(auth)
    ids = body.get("case_ids") if isinstance(body, dict) else None
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="需要 case_ids 数组")
    # 写权限在 service 层对每条资源预检（防跨项目夹带）
    out = case_svc.batch_delete_logical_cases(db, [str(x) for x in ids], auth)
    audit_svc.write_audit_auth(
        db,
        auth,
        action="design.logical_case.batch_delete",
        detail=f"deleted={out.get('deleted_count', 0)} failed={out.get('failed_count', 0)}",
    )
    return out


@router.post("/design/logical-cases/{case_id}/regenerate", response_model=list[LogicalCaseOut])
def api_regenerate_logical_case(
    case_id: str,
    body: dict | None = None,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> list[LogicalCaseOut]:
    design_access.require_design_user(auth)
    try:
        existing = case_svc.get_logical_case(db, case_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    design_access.ensure_row_project_write(db, auth, existing.project_id)
    payload = body if isinstance(body, dict) else {}
    max_cases = payload.get("max_cases")
    use_rag = payload.get("use_rag")
    try:
        out = generation_svc.regenerate_logical_case(
            db,
            case_id,
            auth,
            max_cases=int(max_cases) if max_cases is not None else None,
            use_rag=bool(use_rag) if use_rag is not None else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db,
        auth,
        action="design.logical_case.regenerate",
        resource_type="logical_case",
        resource_id=case_id,
        detail=f"count={len(out)}",
    )
    return out


@router.get("/design/logical-cases/{case_id}", response_model=LogicalCaseOut)
def api_get_logical_case(
    case_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> LogicalCaseOut:
    try:
        out = case_svc.get_logical_case(db, case_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    design_access.ensure_row_project_access(db, auth, out.project_id)
    return out


@router.patch("/design/logical-cases/{case_id}", response_model=LogicalCaseOut)
def api_update_logical_case(
    case_id: str,
    body: LogicalCaseUpdate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> LogicalCaseOut:
    design_access.require_design_user(auth)
    try:
        existing = case_svc.get_logical_case(db, case_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    design_access.ensure_row_project_write(db, auth, existing.project_id)
    try:
        out = case_svc.update_logical_case(db, case_id, body, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db,
        auth,
        action="design.logical_case.update",
        resource_type="logical_case",
        resource_id=out.logical_case_id,
    )
    return out


@router.delete("/design/logical-cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_delete_logical_case(
    case_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> Response:
    design_access.require_design_user(auth)
    try:
        existing = case_svc.get_logical_case(db, case_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    design_access.ensure_row_project_write(db, auth, existing.project_id)
    try:
        case_svc.delete_logical_case(db, case_id, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db,
        auth,
        action="design.logical_case.delete",
        resource_type="logical_case",
        resource_id=case_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/design/projects/{project_id}/logical-cases/export",
    response_model=LogicalCaseExportBundle,
)
def api_export_approved_logical_cases(
    project_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> LogicalCaseExportBundle:
    """IDE 拉取：仅导出 APPROVED 逻辑用例（不含底层关键字）。"""
    design_access.ensure_project_access(db, auth, project_id)
    return case_webhooks.export_approved_cases(db, project_id)


@router.post("/design/logical-cases/enqueue-job")
def api_enqueue_approved_job(
    body: LogicalCaseEnqueueJobIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
):
    """APPROVED 用例一键创建批跑 Job（需 artifact 含 logical_case_id 入口）。"""
    # 延迟：入队桥会拉 jobs.creation，仅该端点需要
    from autopilot_platform.core.schemas import JobOut
    from ..services.design import enqueue as enqueue_svc

    design_access.require_design_user(auth)
    design_access.ensure_project_write(db, auth, body.project_id)
    try:
        out: JobOut = enqueue_svc.enqueue_approved_cases_job(db, body, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db,
        auth,
        action="design.logical_case.enqueue_job",
        resource_type="job",
        resource_id=out.id,
        detail=f"project={body.project_id} artifact={body.artifact_id}",
    )
    return out


@router.post("/design/knowledge", response_model=KnowledgeItemOut)
def api_create_knowledge(
    body: KnowledgeItemCreate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> KnowledgeItemOut:
    design_access.require_design_user(auth)
    design_access.ensure_project_write(db, auth, body.project_id)
    out = knowledge_svc.create_knowledge_item(db, body, auth)
    audit_svc.write_audit_auth(
        db, auth, action="design.knowledge.create", resource_type="knowledge", resource_id=out.id
    )
    return out


@router.get("/design/test-points", response_model=TestPointListPage)
def api_list_test_points(
    project_id: str = Query(...),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> TestPointListPage:
    """列出项目内测试点（文档分析落库后可查）。"""
    design_access.require_design_user(auth)
    design_access.ensure_project_access(db, auth, project_id)
    try:
        return test_points_svc.list_test_points(
            db, project_id=project_id, page=page, page_size=page_size
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/design/knowledge")
def api_list_knowledge(
    project_id: str | None = Query(default=None),
    q: str | None = Query(default=None, description="标题/内容关键词"),
    category: str | None = Query(default=None),
    confirmed: bool | None = Query(default=None),
    sort_by: str | None = Query(default="created_at"),
    order: str = Query(default="desc"),
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> list[KnowledgeItemOut] | KnowledgeListPage:
    scope = design_access.resolve_list_scope(db, auth, project_id)
    items, total, page_n, size = knowledge_svc.query_knowledge_items(
        db,
        project_ids=scope,
        q=q,
        category=category,
        confirmed=confirmed,
        sort_by=sort_by,
        order=order,
        page=page,
        page_size=page_size,
    )
    if page is None:
        return items
    return KnowledgeListPage(items=items, total=total, page=page_n or 1, page_size=size)


@router.post("/design/knowledge/search", response_model=KnowledgeSearchOut)
def api_search_knowledge(
    body: KnowledgeSearchIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> KnowledgeSearchOut:
    design_access.ensure_project_access(db, auth, body.project_id)
    try:
        data = knowledge_svc.search_knowledge(
            db,
            project_id=body.project_id,
            query=body.query,
            top_k=body.top_k,
            score_threshold=body.score_threshold,
            confirmed_only=body.confirmed_only,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return KnowledgeSearchOut(**data)


@router.post("/design/knowledge/rebuild")
def api_rebuild_knowledge(
    body: KnowledgeRebuildIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    design_access.require_design_user(auth)
    design_access.ensure_project_write(db, auth, body.project_id)
    try:
        out = knowledge_svc.rebuild_knowledge_index(
            db, project_id=body.project_id, clear_all=body.clear_all
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db,
        auth,
        action="design.knowledge.rebuild",
        resource_type="project",
        resource_id=body.project_id,
    )
    return out


@router.post("/design/knowledge/batch-delete")
def api_batch_delete_knowledge(
    body: KnowledgeBatchDeleteIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    design_access.require_design_user(auth)
    if not body.item_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="item_ids 不能为空")
    out = knowledge_svc.batch_delete_knowledge_items(db, body.item_ids, auth)
    audit_svc.write_audit_auth(
        db,
        auth,
        action="design.knowledge.batch_delete",
        resource_type="knowledge",
        detail=out.get("message") or "",
    )
    return out


@router.post("/design/knowledge/import")
async def api_import_knowledge(
    project_id: str = Form(...),
    category: str = Form("other"),
    confirmed: bool = Form(True),
    description: str = Form(""),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    design_access.require_design_user(auth)
    design_access.ensure_project_write(db, auth, project_id)
    payload: list[tuple[str, bytes]] = []
    for f in files or []:
        name = (f.filename or "").strip() or "upload.bin"
        raw = await f.read()
        payload.append((name, raw))
    try:
        out = knowledge_import_svc.import_knowledge_files(
            db,
            project_id=project_id,
            files=payload,
            auth=auth,
            category=category,
            confirmed=confirmed,
            description=description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db,
        auth,
        action="design.knowledge.import",
        resource_type="knowledge",
        resource_id=project_id,
        detail=out.get("message") or "",
    )
    return out


@router.get("/design/knowledge/{item_id}", response_model=KnowledgeItemOut)
def api_get_knowledge(
    item_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> KnowledgeItemOut:
    try:
        out = knowledge_svc.get_knowledge_item(db, item_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    design_access.ensure_row_project_access(db, auth, out.project_id)
    return out


@router.patch("/design/knowledge/{item_id}", response_model=KnowledgeItemOut)
def api_update_knowledge(
    item_id: str,
    body: KnowledgeItemUpdate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> KnowledgeItemOut:
    design_access.require_design_user(auth)
    try:
        existing = knowledge_svc.get_knowledge_item(db, item_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    design_access.ensure_row_project_write(db, auth, existing.project_id)
    try:
        out = knowledge_svc.update_knowledge_item(db, item_id, body, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db, auth, action="design.knowledge.update", resource_type="knowledge", resource_id=out.id
    )
    return out


@router.delete("/design/knowledge/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_delete_knowledge(
    item_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> Response:
    design_access.require_design_user(auth)
    try:
        existing = knowledge_svc.get_knowledge_item(db, item_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    design_access.ensure_row_project_write(db, auth, existing.project_id)
    try:
        knowledge_svc.delete_knowledge_item(db, item_id, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db, auth, action="design.knowledge.delete", resource_type="knowledge", resource_id=item_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/design/documents", response_model=DesignDocumentOut)
async def api_upload_document(
    project_id: str = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> DesignDocumentOut:
    design_access.require_design_user(auth)
    design_access.ensure_project_write(db, auth, project_id)
    data = await file.read()
    try:
        out = doc_svc.save_document(
            db,
            project_id=project_id,
            filename=file.filename or "upload.txt",
            data=data,
            auth=auth,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db, auth, action="design.document.upload", resource_type="document", resource_id=out.id
    )
    return out


@router.post("/design/documents/import")
async def api_import_documents(
    project_id: str = Form(...),
    auto_analyze: bool = Form(True),
    max_requirements: int = Form(20),
    use_llm: bool = Form(True),
    analysis_type: str = Form("requirements"),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    design_access.require_design_user(auth)
    design_access.ensure_project_write(db, auth, project_id)
    payload: list[tuple[str, bytes]] = []
    for f in files or []:
        name = (f.filename or "").strip() or "upload.bin"
        raw = await f.read()
        payload.append((name, raw))
    try:
        out = document_import_svc.import_documents(
            db,
            project_id=project_id,
            files=payload,
            auth=auth,
            auto_analyze=auto_analyze,
            max_requirements=max(1, min(int(max_requirements or 20), 100)),
            use_llm=use_llm,
            analysis_type=(analysis_type or "requirements").strip() or "requirements",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db,
        auth,
        action="design.document.import",
        resource_type="document",
        resource_id=project_id,
        detail=out.get("message") or "",
    )
    return out


@router.get("/design/documents")
def api_list_documents(
    project_id: str | None = Query(default=None),
    q: str | None = Query(default=None, description="文件名/内容关键词"),
    file_type: str | None = Query(default=None),
    sort_by: str | None = Query(default="created_at"),
    order: str = Query(default="desc"),
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> list[DesignDocumentOut] | DesignDocumentListPage:
    scope = design_access.resolve_list_scope(db, auth, project_id)
    items, total, page_n, size = doc_svc.query_documents(
        db,
        project_ids=scope,
        q=q,
        file_type=file_type,
        sort_by=sort_by,
        order=order,
        page=page,
        page_size=page_size,
    )
    if page is None:
        return items
    return DesignDocumentListPage(items=items, total=total, page=page_n or 1, page_size=size)


@router.get("/design/documents/analysis-history", response_model=AnalysisHistoryListPage)
def api_list_analysis_history(
    project_id: str | None = Query(default=None),
    document_id: str | None = Query(default=None),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> AnalysisHistoryListPage:

    scope = design_access.resolve_list_scope(db, auth, project_id)
    pg, size = normalize_page_params(
        page=page, page_size=page_size, limit=limit, offset=offset, default_size=50
    )
    items, total = document_analysis_history_svc.list_analysis_history(
        db,
        project_ids=scope,
        document_id=document_id,
        page=pg,
        page_size=size,
    )
    return AnalysisHistoryListPage(items=items, total=total, page=pg, page_size=size)


@router.post("/design/documents/batch-delete")
def api_batch_delete_documents(
    body: DocumentBatchDeleteIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    design_access.require_design_user(auth)
    if not body.item_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="item_ids 不能为空")
    out = doc_svc.batch_delete_documents(db, body.item_ids, auth)
    audit_svc.write_audit_auth(
        db,
        auth,
        action="design.document.batch_delete",
        resource_type="document",
        detail=out.get("message") or "",
    )
    return out


@router.get("/design/documents/{document_id}/preview", response_model=DocumentPreviewOut)
def api_preview_document(
    document_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> DocumentPreviewOut:
    try:
        row = doc_svc.get_document(db, document_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    design_access.ensure_row_project_access(db, auth, row.project_id)
    return doc_svc.preview_document(db, document_id)


@router.delete("/design/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_delete_document(
    document_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> Response:
    design_access.require_design_user(auth)
    try:
        row = doc_svc.get_document(db, document_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    design_access.ensure_row_project_write(db, auth, row.project_id)
    try:
        doc_svc.delete_document(db, document_id, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db, auth, action="design.document.delete", resource_type="document", resource_id=document_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/design/documents/{document_id}/analyze")
def api_analyze_document(
    document_id: str,
    max_requirements: int = Query(default=20, ge=1, le=100),
    use_llm: bool = Query(default=True),
    analysis_type: str = Query(default="requirements"),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    design_access.require_design_user(auth)
    try:
        row = doc_svc.get_document(db, document_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    design_access.ensure_row_project_write(db, auth, row.project_id)
    try:
        out = document_analysis_svc.analyze_document(
            db,
            document_id,
            auth,
            max_requirements=max_requirements,
            use_llm=use_llm,
            analysis_type=(analysis_type or "requirements").strip() or "requirements",
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    summary = out.get("summary") or {}
    audit_svc.write_audit_auth(
        db,
        auth,
        action="design.document.analyze",
        resource_type="document",
        resource_id=document_id,
        detail=(
            f"type={out.get('analysis_type')} "
            f"req={summary.get('requirements_count', 0)} "
            f"tp={summary.get('test_points_count', 0)} "
            f"br={summary.get('business_rules_count', 0)}"
        ),
    )
    return out


@router.post("/design/documents/{document_id}/reanalyze")
def api_reanalyze_document(
    document_id: str,
    max_requirements: int = Query(default=20, ge=1, le=100),
    use_llm: bool = Query(default=True),
    analysis_type: str = Query(default="requirements"),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    """重新分析（与 analyze 等价，对齐 TestPilot reanalyze 命名）。"""
    return api_analyze_document(
        document_id=document_id,
        max_requirements=max_requirements,
        use_llm=use_llm,
        analysis_type=analysis_type,
        db=db,
        auth=auth,
    )



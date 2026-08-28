"""设计域配置 API：/design/config 读写与导入导出。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import AuthContext, require_auth, require_ops_admin
from ..core.db import get_session
from ..ops import audit as audit_svc
from ..ops.runtime_config import (
    DESIGN_CONFIG_CATEGORIES,
    DESIGN_CONFIG_KEYS,
    SECRET_KEYS,
    SECRET_MASK,
    describe_config,
    export_design_config_payload,
    import_design_config_payload,
    save_runtime_config,
    validate_design_config_values,
)
from ..services.design import access as design_access

router = APIRouter(tags=["design"])


# ── 配置中心（设计域子集）──────────────────────────────────────────


@router.get("/design/config")
def api_design_config_get(
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    """设计人员可读 AI / 向量 / RAG / 生成参数（只读）；写入统一走运维 /ops/config。"""
    _ = db
    design_access.require_design_user(auth)
    full = describe_config()
    values = {k: full["values"].get(k, "") for k in DESIGN_CONFIG_KEYS}
    sources = {k: full["sources"].get(k, "default") for k in DESIGN_CONFIG_KEYS}
    return {
        "editable_keys": list(DESIGN_CONFIG_KEYS),
        "secret_keys": [k for k in DESIGN_CONFIG_KEYS if k in SECRET_KEYS],
        "secret_mask": SECRET_MASK,
        "values": values,
        "sources": sources,
        "categories": [dict(c) for c in DESIGN_CONFIG_CATEGORIES],
        "writable": False,
        "write_via": "/api/v1/ops/config",
    }


@router.put("/design/config")
def api_design_config_put(
    body: dict,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_ops_admin),
) -> dict:
    """仅 ops_admin 可写；密钥与设计域参数统一入口为运维配置中心。"""
    raw = body.get("values") if isinstance(body.get("values"), dict) else body
    if not isinstance(raw, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="需要 values 对象")
    unknown = [k for k in raw if str(k) not in DESIGN_CONFIG_KEYS]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不允许的配置键: {unknown}",
        )
    errs = validate_design_config_values(raw)
    if errs:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="; ".join(errs))
    try:
        save_runtime_config(raw, replace=False)
    except ValueError as exc:
        # 与 /ops/config 对齐：缺 MC_CONFIG_SECRET 等 fail-closed 映 400（AUD-2026-05）
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db,
        auth,
        action="design.config_update",
        detail=",".join(sorted(str(k) for k in raw.keys())),
    )
    return api_design_config_get(db=db, auth=auth)


@router.get("/design/config/export")
def api_design_config_export(
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    _ = db
    design_access.require_design_user(auth)
    return export_design_config_payload()


@router.post("/design/config/import")
def api_design_config_import(
    body: dict,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_ops_admin),
) -> dict:
    """仅 ops_admin 可导入；与 /ops/config 密钥入口对齐。"""
    try:
        imported = import_design_config_payload(body if isinstance(body, dict) else {})
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    keys = list((imported.get("values") or {}).keys())
    audit_svc.write_audit_auth(
        db,
        auth,
        action="design.config_import",
        detail=f"imported={len(keys)}",
    )
    return api_design_config_get(db=db, auth=auth)



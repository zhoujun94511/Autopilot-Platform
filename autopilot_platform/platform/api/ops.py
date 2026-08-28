"""Audit + ops endpoints."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import AuditListPage

from ..auth import AuthContext, require_auth, require_ops_admin, require_user_manager
from ..core import api_messages as msg
from ..core.db import get_session
from ..core.list_page import normalize_page_params
from ..core.metrics import ops_summary
from ..core.settings import (
    alert_channel,
    alert_webhook_url,
    design_webhook_url,
    enforce_runtime_version,
)
from ..ops import audit as audit_svc
from ..ops.runtime_compat import ap_runtime_version
from ..ops.runtime_config import (
    DESIGN_CONFIG_KEYS,
    EDITABLE_KEYS,
    describe_config,
    export_runtime_config_payload,
    import_runtime_config_payload,
    save_runtime_config,
    validate_design_config_values,
)
from ..ai import ai_config, ai_usage
from ..design.design_schemas import EphemeralChatIn
from ..services.design import access as design_access
from ..services.observability import agentops as agentops_svc
from ..services.observability import job_quality as jq_svc
from ..tenancy.projects import is_platform_admin
from ..tenancy.rbac_response import sanitize_agentops_snapshot

router = APIRouter(tags=["ops"])

# 单请求 prompt 上限：防止一次塞入超大上下文打爆输入 token
MAX_AI_PROMPT_CHARS = 60000



@router.get("/audit", response_model=AuditListPage)
def api_list_audit(
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=500),
    limit: int | None = Query(None, ge=1, le=500),
    offset: int | None = Query(None, ge=0),
    action: str = Query(""),
    actor: str = Query(""),
    org_id: str = Query(""),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_user_manager),
) -> AuditListPage:
    oid = (org_id or "").strip() or (auth.org_id or "").strip()
    # 组织管理员强制本组织；平台 admin 可显式传 org_id 或看全量
    if not is_platform_admin(auth):
        oid = (auth.org_id or "").strip()
        if not oid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=msg.AUTH_ORG_CONTEXT_REQUIRED
            )

    pg, size = normalize_page_params(
        page=page, page_size=page_size, limit=limit, offset=offset, default_size=100
    )
    items, total = audit_svc.list_audits(
        db, page=pg, page_size=size, action=action, actor=actor, org_id=oid
    )
    return AuditListPage(items=items, total=total, page=pg, page_size=size)





@router.get("/ops/summary")

def api_ops_summary(

    db: Session = Depends(get_session),

    _auth: AuthContext = Depends(require_ops_admin),

) -> dict:

    """运维摘要：任务分布 / Runner / 设备 / 进程内计数。"""
    from ..rag import health as rag_health  # 延迟：RAG extra



    out = ops_summary(db)

    out["alert_channel"] = alert_channel()

    out["alert_configured"] = bool(alert_webhook_url())

    out["rag"] = rag_health.snapshot()

    return out





@router.get("/ops/agentops")
def api_ops_agentops(
    project_id: str | None = Query(default=None),
    limit: int = Query(80, ge=1, le=200),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    """AgentOps：近期 result.json Intent Trace 聚合 + AI token 日摘要。"""
    scope = design_access.resolve_list_scope(db, auth, project_id)
    raw = agentops_svc.agentops_snapshot(
        db, project_id=project_id, project_ids=scope, limit=limit
    )
    return sanitize_agentops_snapshot(raw, auth)


@router.get("/ops/job-quality")
def api_ops_job_quality(
    project_id: str | None = Query(default=None),
    days: int = Query(14, ge=1, le=90),
    limit: int = Query(80, ge=1, le=200),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    """Job 失败趋势与全步 fail_reason（项目作用域）。"""
    scope = design_access.resolve_list_scope(db, auth, project_id)
    return jq_svc.job_quality_snapshot(
        db,
        project_id=project_id,
        project_ids=scope,
        days=days,
        report_limit=limit,
    )


@router.get("/ops/rag-health")

def api_ops_rag_health(_auth: AuthContext = Depends(require_ops_admin)) -> dict:

    """RAG / Embedding 进程内健康快照（只读）。"""
    from ..rag import health as rag_health  # 延迟：RAG extra

    from ..rag.embedder_factory import get_embedder, rag_embedder_mode  # 延迟：RAG extra



    snap = rag_health.snapshot()

    emb = get_embedder()

    snap["configured_mode"] = rag_embedder_mode()

    snap["active_embedder"] = str(getattr(emb, "name", "") or "")

    return snap





@router.get("/ops/runtime-version")

def api_ops_runtime_version(_auth: AuthContext = Depends(require_auth)) -> dict:

    """执行核公开版本契约；仅需登录，不返回配置或秘密。"""
    root = Path(__file__).resolve().parents[3]

    pin_path = root / "contracts" / "RUNTIME_PIN"
    contract_path = root / "contracts" / "runtime_contract.json"

    pin = ""

    if pin_path.is_file():

        pin = pin_path.read_text(encoding="utf-8").strip().splitlines()[0].strip()

    actual = ap_runtime_version()
    capabilities: list[str] = []
    contract_runtime_version = ""
    if contract_path.is_file():
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        capabilities = list(contract.get("capabilities") or [])
        contract_runtime_version = str(contract.get("runtime_version") or "").strip()

    return {

        "ap_version": actual,

        "runtime_pin": pin,

        "contract_runtime_version": contract_runtime_version,

        "pin_match": (not pin) or (pin == actual) or pin.replace("-vendored", "") in actual,

        "enforce_runtime_version": enforce_runtime_version(),
        "capabilities": capabilities,

        "note": (
            "公开契约 runtime_version 为 canonical MAJOR.MINOR.PATCH（见 contracts/runtime_contract.json）；"
            "ap.__version__ / RUNTIME_PIN 可带 -vendored。兼容比较只看 major.minor。"
        ),

    }





@router.get("/ops/config")

def api_ops_config_get(_auth: AuthContext = Depends(require_ops_admin)) -> dict:

    """统一配置中心：运维 + AI/RAG/生成等全部 EDITABLE_KEYS。"""
    return describe_config()




@router.get("/ops/config/ai-providers")

def api_ops_config_ai_providers(_auth: AuthContext = Depends(require_ops_admin)) -> dict:

    """AI Provider 目录：默认 Base URL / 模型列表（单一事实来源 ai_config）。"""

    return {"providers": ai_config.list_ai_providers()}




@router.put("/ops/config")

def api_ops_config_put(

    body: dict,

    db: Session = Depends(get_session),

    auth: AuthContext = Depends(require_ops_admin),

) -> dict:

    """保存运行时覆盖（EDITABLE_KEYS）；设计域键走同一校验。"""
    raw = body.get("values") if isinstance(body.get("values"), dict) else body

    if not isinstance(raw, dict):

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg.OPS_VALUES_REQUIRED)

    unknown = [k for k in raw if str(k) not in EDITABLE_KEYS]

    if unknown:

        raise HTTPException(

            status_code=status.HTTP_400_BAD_REQUEST,

            detail=msg.OPS_UNKNOWN_KEYS.format(keys=unknown),

        )

    design_subset = {str(k): v for k, v in raw.items() if str(k) in DESIGN_CONFIG_KEYS}

    if design_subset:

        errs = validate_design_config_values(design_subset)

        if errs:

            raise HTTPException(

                status_code=status.HTTP_400_BAD_REQUEST,

                detail="; ".join(errs),

            )

    try:
        save_runtime_config(raw, replace=bool(body.get("replace")))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    audit_svc.write_audit_auth(

        db,

        auth,

        action="ops.config_update",

        detail=",".join(sorted(str(k) for k in raw.keys())),

    )

    return describe_config()





@router.get("/ops/config/export")

def api_ops_config_export(_auth: AuthContext = Depends(require_ops_admin)) -> dict:

    """导出全部可写配置（密钥掩码）。"""
    return export_runtime_config_payload()





@router.post("/ops/config/import")

def api_ops_config_import(

    body: dict,

    db: Session = Depends(get_session),

    auth: AuthContext = Depends(require_ops_admin),

) -> dict:

    """导入配置（兼容 design-config 子集）。"""
    try:

        imported = import_runtime_config_payload(body if isinstance(body, dict) else {})

    except ValueError as exc:

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    keys = list((imported.get("values") or {}).keys())

    audit_svc.write_audit_auth(

        db,

        auth,

        action="ops.config_import",

        detail=f"imported={len(keys)}",

    )

    return describe_config()





@router.post("/ops/alert-test")

def api_ops_alert_test(

    db: Session = Depends(get_session),

    auth: AuthContext = Depends(require_ops_admin),

) -> dict:

    """向告警 URL 发一条测试告警（同步）。"""
    from ..ops.notify import send_alert_sync  # 延迟：通知通道可选



    if not alert_webhook_url():

        raise HTTPException(

            status_code=status.HTTP_400_BAD_REQUEST,

            detail=msg.OPS_WEBHOOK_NOT_SET,

        )

    ok = send_alert_sync(

        "ops.alert_test",

        summary="管理台告警通道测试",

        detail={"channel": alert_channel(), "test": True},

    )

    audit_svc.write_audit_auth(

        db,

        auth,

        action="ops.alert_test",

        detail=f"ok={ok};channel={alert_channel()}",

    )

    return {"ok": ok, "channel": alert_channel()}





@router.post("/ops/design-webhook-test")

def api_ops_design_webhook_test(

    db: Session = Depends(get_session),

    auth: AuthContext = Depends(require_ops_admin),

) -> dict:

    """向 MC_DESIGN_WEBHOOK_URL 发送一条测试 APPROVED 事件（同步）。"""
    from ..ops.notify import send_design_event_sync  # 延迟：通知通道可选



    if not design_webhook_url():

        raise HTTPException(

            status_code=status.HTTP_400_BAD_REQUEST,

            detail="design webhook URL not set (MC_DESIGN_WEBHOOK_URL)",

        )

    ok = send_design_event_sync(

        "logical_case.approved",

        project_id="__test__",

        case={

            "logical_case_id": "lc-webhook-test",

            "case_key": "LC-WEBHOOK-TEST",

            "project_id": "__test__",

            "title": "设计域 webhook 测试",

            "review_status": "APPROVED",

            "intent_steps": [

                {

                    "id": "s1",

                    "action": "custom",

                    "target": "",

                    "value": "",

                    "platform_hint": "any",

                    "text": "webhook test",

                }

            ],

            "logical_steps": ["webhook test"],

            "expected_results": ["ok"],

        },

    )

    audit_svc.write_audit_auth(

        db,

        auth,

        action="ops.design_webhook_test",

        detail=f"ok={ok}",

    )

    return {"ok": ok, "url_configured": True}


def assert_ai_gateway_caller(auth: AuthContext) -> None:
    """AI 转发端点统一门禁（cap.ops.ai.codegen）。

    仅登录用户可消耗平台厂商 Key：Runner / 执行通道 / 运维令牌一律拒绝，
    避免泄露的 ``X-API-Token`` 被脚本循环调用打爆 token 配额。
    """
    if getattr(auth, "kind", "") != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI 服务仅限登录用户使用",
        )


@router.post("/ops/ai/chat")
def api_ops_ai_chat(
    body: dict,
    auth: AuthContext = Depends(require_auth),
) -> dict:
    """测试闲聊（无项目）：不落设计域会话、不注入知识库；人设仍为测试助手。"""
    from ..services.design.chat import ephemeral as chat_svc  # 延迟：闲聊走 LLM 客户端

    assert_ai_gateway_caller(auth)
    try:
        payload = EphemeralChatIn.model_validate(body or {})
        return chat_svc.ephemeral_send(payload, auth)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.post("/ops/ai/chat/stream")
def api_ops_ai_chat_stream(
    body: dict,
    auth: AuthContext = Depends(require_auth),
):
    """测试闲聊 SSE（无项目、不落库）。"""
    from ..services.design.chat import ephemeral as chat_svc  # 延迟：闲聊走 LLM 客户端

    assert_ai_gateway_caller(auth)
    try:
        payload = EphemeralChatIn.model_validate(body or {})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    def _gen():
        yield from chat_svc.iter_ephemeral_sse(payload, auth)

    return StreamingResponse(_gen(), media_type="text/event-stream")


def _codegen_llm_content(
    prompt: str,
    *,
    project_id: str,
    org_id: str,
    purpose: str = "authoring",
) -> str:
    """配额校验 + 转发厂商 LLM；失败统一转 HTTPException。"""
    from ..ai import ai_client  # 延迟：HTTP LLM 客户端

    try:
        ai_usage.check_budget_before_call(project_id=project_id, org_id=org_id)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "token_budget", "message": str(exc)[:500]},
        ) from exc
    model = ai_config.ai_model_for_purpose(purpose)
    try:
        return ai_client.chat_completions(
            [
                {"role": "system", "content": "你只输出合法 JSON，不要 Markdown。"},
                {"role": "user", "content": prompt},
            ],
            model=model,
            max_tokens=ai_config.ai_codegen_max_tokens(),
            max_attempts=ai_config.ai_codegen_max_attempts(),
            usage_source="codegen",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "ai_failed", "message": str(exc)[:500]},
        ) from exc


def _codegen_error_message(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("error") or "")[:500]
    return str(detail or "")[:500]


def _write_codegen_audit(db: Session, auth: AuthContext, purpose: str, detail: str) -> None:
    audit_svc.write_audit_auth(
        db,
        auth,
        action="ops.ai_codegen",
        resource_type="ai",
        resource_id=purpose[:128],
        detail=detail,
    )


def _ai_codegen_capabilities() -> dict:
    """返回当前生效模型的非敏感能力和链路 3 消耗边界。"""
    from ..ai.provider_profile import model_accepts_images  # 延迟：仅能力探测

    provider = ai_config.ai_provider()
    model = ai_config.ai_model()
    planning_model = ai_config.ai_model_for_purpose("planning")
    locate_model = ai_config.ai_model_for_purpose("locate")
    base_url = ai_config.ai_base_url()
    accepts_images = model_accepts_images(provider, model, base_url=base_url)
    locate_accepts_images = model_accepts_images(provider, locate_model, base_url=base_url)
    return {
        "enabled": ai_config.ai_enabled(),
        "provider": provider,
        "model": model,
        "planning_model": planning_model,
        "locate_model": locate_model,
        "accepts_images": accepts_images,
        "locate_accepts_images": locate_accepts_images,
        "image_policy": "multimodal" if accepts_images else "text_only_ui_tree",
        "codegen_max_tokens": ai_config.ai_codegen_max_tokens(),
        "codegen_max_attempts": ai_config.ai_codegen_max_attempts(),
        "token_budget": {
            "global_daily": ai_usage.daily_token_budget(),
            "project_daily": ai_usage.project_daily_token_budget(),
            "org_daily": ai_usage.org_daily_token_budget(),
            "enforced": ai_usage.enforce_token_budget(),
        },
        "budget_warnings": ai_usage.budget_config_warnings(),
    }


def _assert_codegen_text_only(prompt: str) -> None:
    """链路 3 只收文本/UI 树；禁止把截图 base64 当文本烧进 token。"""
    low = (prompt or "").lower()
    if "data:image/" in low or ";base64," in low:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "unsupported_image_payload",
                "message": "AI 编写仅接受文本与页面结构，不接受内嵌图片",
            },
        )


@router.get("/ops/ai/capabilities")
def api_ops_ai_capabilities(auth: AuthContext = Depends(require_auth)) -> dict:
    """IDE 调用前预检；不调用厂商、不消耗 token，也不返回 Key/Base URL。"""
    assert_ai_gateway_caller(auth)
    return _ai_codegen_capabilities()


@router.post("/ops/ai/codegen")
def api_ops_ai_codegen(
    body: dict,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    """链路 3 LLM 网关（cap.ops.ai.codegen）：入参 prompt，出参 content。

    平台持有厂商 Key 并转发；不持有设备定位器真源。须写入计费作用域与审计。
    """
    from ..core.models import ProjectRow  # 延迟：仅带 project_id 的 codegen

    assert_ai_gateway_caller(auth)

    prompt = str((body or {}).get("prompt") or "").strip()
    _assert_codegen_text_only(prompt)
    if len(prompt) > MAX_AI_PROMPT_CHARS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="内容过长，请缩短需求或拆成更小的步骤",
        )
    purpose = ai_config.normalize_codegen_purpose(
        str((body or {}).get("purpose") or "authoring")
    )
    project_id = str((body or {}).get("project_id") or "").strip()
    if not prompt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请输入需求内容")
    if not ai_config.ai_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "ai_unavailable", "message": "AI 尚未开通：请在运维中配置模型密钥"},
        )

    org_id = (getattr(auth, "org_id", "") or "").strip()
    if project_id:
        # 计费落到哪个项目由调用方声明，必须存在且是成员，否则可把消耗甩给别的项目
        row = db.get(ProjectRow, project_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"项目不存在：{project_id}",
            )
        design_access.ensure_project_access(db, auth, project_id)
        org_id = str(getattr(row, "org_id", "") or "").strip() or org_id
    # 禁止双空 scope 绕过 project/org 日配额记账
    if not project_id:
        project_id = "__authoring__"
    if not org_id:
        org_id = "__platform__"

    scope = ai_usage.set_ai_billing_scope(project_id=project_id, org_id=org_id)
    model_used = ai_config.ai_model_for_purpose(purpose)
    trace = (
        f"project={project_id};org={org_id};purpose={purpose};"
        f"model={model_used};prompt_chars={len(prompt)}"
    )
    try:
        content = _codegen_llm_content(
            prompt, project_id=project_id, org_id=org_id, purpose=purpose
        )
    except HTTPException as exc:
        _write_codegen_audit(db, auth, purpose, f"ok=False;{trace};err={_codegen_error_message(exc)}")
        raise
    finally:
        ai_usage.reset_ai_billing_scope(scope)
    _write_codegen_audit(db, auth, purpose, f"ok=True;{trace}")

    return {
        "ok": True,
        "purpose": purpose,
        "model": model_used,
        "content": content or "",
        "project_id": project_id,
        "org_id": org_id,
        "user": getattr(auth, "username", "") or getattr(auth, "sub", "") or "",
        "capabilities": _ai_codegen_capabilities(),
    }


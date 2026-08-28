"""FastAPI 全局异常 → 统一错误信封。"""

from __future__ import annotations

import logging
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from autopilot_platform.core.errors import (
    ErrorCode,
    fail,
    http_fail,
    resolve_http_error_code,
    resolve_http_error_type,
)
import autopilot_platform.platform.core.api_messages as msg
from .request_context import get_request_id

# noinspection SpellCheckingInspection
log = logging.getLogger("autopilot_platform.platform.errors")


def _json_safe(value: Any) -> Any:
    """Pydantic v2 error ctx 可能带 Exception 实例，不能直接 json.dumps。"""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _localize_message(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return msg.INTERNAL_ERROR
    mapped = msg.LEGACY_DETAIL_ZH.get(text)
    if mapped:
        return mapped
    # 限流等带动态后缀的英文
    if text.startswith("too many login failures"):
        return msg.LOGIN_RATE_LIMITED.format(seconds=60)
    if text.startswith("no access to project"):
        return msg.PROJECT_NO_ACCESS
    if text.startswith("no access to "):
        return msg.ACL_NO_ACCESS
    if text.startswith("username already exists"):
        return msg.AUTH_USERNAME_EXISTS.format(username=text.split(":", 1)[-1].strip())
    if text.startswith("project already exists"):
        return msg.PROJECT_ALREADY_EXISTS.format(project_id=text.split(":", 1)[-1].strip())
    if text.startswith("artifact not found"):
        aid = text.split(":", 1)[-1].strip() if ":" in text else ""
        return msg.ARTIFACT_NOT_FOUND_ID.format(artifact_id=aid) if aid else msg.ARTIFACT_NOT_FOUND
    if text.startswith("app build not found"):
        bid = text.split(":", 1)[-1].strip() if ":" in text else ""
        return msg.APP_BUILD_NOT_FOUND_ID.format(app_build_id=bid) if bid else msg.APP_BUILD_NOT_FOUND
    if text.startswith("device not found"):
        return msg.DEVICE_NOT_FOUND.format(udid=text.split(":", 1)[-1].strip())
    if text.startswith("runner not found"):
        return msg.RUNNER_NOT_FOUND.format(runner_id=text.split(":", 1)[-1].strip())
    if text.startswith("user not found:"):
        return msg.AUTH_USER_NOT_FOUND
    if text.startswith("report not found for job"):
        jid = text.split(":", 1)[-1].strip() if ":" in text else ""
        return msg.REPORT_NOT_FOUND_JOB.format(job_id=jid) if jid else msg.REPORT_NOT_FOUND
    if text.startswith("job not found:"):
        return msg.JOB_NOT_FOUND
    if text.startswith("unsupported resource_type"):
        return msg.ACL_UNSUPPORTED_RESOURCE_TYPE.format(
            resource_type=text.split(":", 1)[-1].strip()
        )
    if text.startswith("device_udids required"):
        return msg.JOB_DEVICES_REQUIRED
    if text.startswith("invalid status transition from"):
        return msg.JOB_INVALID_STATUS_TRANSITION.format(status=text.rsplit(" ", 1)[-1])
    if text.startswith("cannot cancel job in status"):
        return msg.JOB_CANNOT_CANCEL_STATUS.format(status=text.rsplit(" ", 1)[-1])
    if text.startswith("can only retry terminal job"):
        return msg.JOB_CANNOT_RETRY_STATUS.format(status=text.rsplit(" ", 1)[-1])
    if text.startswith("schedule creator unavailable"):
        return msg.SCHEDULE_CREATOR_UNAVAILABLE
    if text.startswith("unknown or non-editable keys"):
        return msg.OPS_UNKNOWN_KEYS.format(keys=text.split(":", 1)[-1].strip())
    if text.startswith("oidc failed") or text.startswith("saml failed") or text.startswith("oidc error"):
        return msg.AUTH_SSO_FAILED
    return text


def _detail_to_parts(detail: Any, status_code: int) -> tuple[str, ErrorCode, str, Any]:
    if isinstance(detail, dict):
        message = str(
            detail.get("message") or detail.get("detail") or msg.BAD_REQUEST
        )
        message = _localize_message(message)
        error_type = str(
            detail.get("error_type") or resolve_http_error_type(status_code)
        )
        details = detail.get("details")
        code_value = detail.get("code")
        if isinstance(code_value, str) and code_value.startswith("E"):
            try:
                error_code = ErrorCode(code_value)
            except ValueError:
                error_code = resolve_http_error_code(status_code)
        else:
            error_code = resolve_http_error_code(status_code)
        return message, error_code, error_type, details

    message = _localize_message(str(detail) if detail is not None else "")
    return (
        message,
        resolve_http_error_code(status_code),
        resolve_http_error_type(status_code),
        None,
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException):
        message, error_code, error_type, details = _detail_to_parts(
            exc.detail, exc.status_code
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=http_fail(
                exc.status_code,
                message,
                code=error_code,
                error_type=error_type,
                details=details,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request, exc: RequestValidationError
    ):
        errors = cast(list[dict[str, Any]], list(exc.errors()))
        first = ""
        if errors:
            first = str(errors[0].get("msg") or "")
        message = msg.VALIDATION_FAILED
        if first and first not in ("Field required", "field required"):
            # 保留具体校验信息，便于表单定位
            message = f"{msg.VALIDATION_FAILED.rstrip('。')}：{first}"
        return JSONResponse(
            status_code=422,
            content=fail(
                message,
                code=ErrorCode.VALIDATION_FAILED,
                error_type="validation_error",
                details=_json_safe(errors),
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, _exc: Exception):
        rid = get_request_id()
        if rid:
            log.exception(
                "Unhandled exception [%s]: %s %s",
                rid,
                request.method,
                request.url.path,
            )
        else:
            log.exception("Unhandled exception: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=fail(
                msg.INTERNAL_ERROR,
                code=ErrorCode.INTERNAL_ERROR,
                error_type="internal_error",
            ),
        )

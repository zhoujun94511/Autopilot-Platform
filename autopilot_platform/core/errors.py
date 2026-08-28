"""统一 API 错误码与失败信封（对齐 Scenario_Engine：后端管文案，前端展示 message）。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import uuid4


class ErrorCode(StrEnum):
    BAD_REQUEST = "E4000"
    AUTH_FAILED = "E4001"
    FORBIDDEN = "E4003"
    NOT_FOUND = "E4004"
    CONFLICT = "E4009"
    RATE_LIMITED = "E4290"
    VALIDATION_FAILED = "E4220"
    INTERNAL_ERROR = "E5000"
    BAD_GATEWAY = "E5020"
    UNAVAILABLE = "E5030"


_HTTP_STATUS_TO_ERROR_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.AUTH_FAILED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.VALIDATION_FAILED,
    429: ErrorCode.RATE_LIMITED,
    500: ErrorCode.INTERNAL_ERROR,
    502: ErrorCode.BAD_GATEWAY,
    503: ErrorCode.UNAVAILABLE,
}

_HTTP_STATUS_TO_ERROR_TYPE: dict[int, str] = {
    400: "bad_request",
    401: "auth_failed",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    502: "bad_gateway",
    503: "unavailable",
}


def resolve_http_error_code(status_code: int) -> ErrorCode:
    return _HTTP_STATUS_TO_ERROR_CODE.get(status_code, ErrorCode.INTERNAL_ERROR)


def resolve_http_error_type(status_code: int) -> str:
    return _HTTP_STATUS_TO_ERROR_TYPE.get(status_code, "internal_error")


def new_trace_id() -> str:
    return uuid4().hex[:16]


def fail(
    message: str,
    *,
    code: str | ErrorCode = ErrorCode.INTERNAL_ERROR,
    error_type: str = "internal_error",
    trace_id: str | None = None,
    details: Any | None = None,
) -> dict[str, Any]:
    """标准失败响应体。"""
    return {
        "code": str(code),
        "message": message,
        "error_type": error_type,
        "trace_id": trace_id or new_trace_id(),
        "details": details,
    }


def http_fail(
    status_code: int,
    message: str,
    *,
    code: ErrorCode | None = None,
    error_type: str | None = None,
    details: Any | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    return fail(
        message,
        code=code or resolve_http_error_code(status_code),
        error_type=error_type or resolve_http_error_type(status_code),
        trace_id=trace_id,
        details=details,
    )

"""MCP 工具描述与分发（执行仍走 Job+关键字，此处仅查询）。"""

from __future__ import annotations

import json
from typing import Any, Callable

from .client import PlatformReadonlyClient

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "list_jobs",
        "description": "List Platform jobs (status, depends_on, project). Read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20},
                "offset": {"type": "integer", "default": 0},
                "project_id": {"type": "string", "default": ""},
            },
        },
    },
    {
        "name": "get_job",
        "description": "Get one job by id (includes depends_on and error). Read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    },
    {
        "name": "list_devices",
        "description": "List registered devices and busy state. Read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 50}},
        },
    },
    {
        "name": "get_job_report",
        "description": "Get report summary for a job (passed/failed/total). Read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    },
]


def _dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def dispatch_tool(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    client: PlatformReadonlyClient | None = None,
) -> str:
    cli = client or PlatformReadonlyClient()
    args = dict(arguments or {})
    handlers: dict[str, Callable[[], Any]] = {
        "list_jobs": lambda: cli.list_jobs(
            limit=int(args.get("limit") or 20),
            offset=int(args.get("offset") or 0),
            project_id=str(args.get("project_id") or ""),
        ),
        "get_job": lambda: cli.get_job(str(args.get("job_id") or "")),
        "list_devices": lambda: cli.list_devices(limit=int(args.get("limit") or 50)),
        "get_job_report": lambda: cli.get_report(str(args.get("job_id") or "")),
    }
    if name not in handlers:
        raise ValueError(f"unknown tool: {name}")
    return _dump(handlers[name]())

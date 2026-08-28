"""E3：MCP 只读工具分发（不依赖真实 MCP SDK）。"""

from __future__ import annotations

import json
from typing import cast

from autopilot_platform.platform.mcp_readonly.client import PlatformReadonlyClient
from autopilot_platform.platform.mcp_readonly.tools import TOOL_SPECS, dispatch_tool


class _FakeClient:
    @staticmethod
    def list_jobs(*, limit=20, offset=0, project_id=""):
        _ = limit, offset, project_id
        return [{"id": "j1", "status": "pending", "depends_on": []}]

    @staticmethod
    def get_job(job_id: str):
        return {"id": job_id, "status": "succeeded", "depends_on": ["a"]}

    @staticmethod
    def list_devices(*, limit=50):
        _ = limit
        return [{"udid": "d1"}]

    @staticmethod
    def get_report(job_id: str):
        return {"job_id": job_id, "passed": 1, "failed": 0, "total": 1}


def test_tool_specs_cover_readonly_surface():
    names = {t["name"] for t in TOOL_SPECS}
    assert names == {"list_jobs", "get_job", "list_devices", "get_job_report"}


def test_dispatch_list_jobs():
    client = cast(PlatformReadonlyClient, _FakeClient())
    out = json.loads(dispatch_tool("list_jobs", {"limit": 5}, client=client))
    assert out[0]["id"] == "j1"


def test_dispatch_get_job_report():
    client = cast(PlatformReadonlyClient, _FakeClient())
    out = json.loads(
        dispatch_tool("get_job_report", {"job_id": "abc"}, client=client)
    )
    assert out["total"] == 1

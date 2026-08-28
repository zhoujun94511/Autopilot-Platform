"""可选 MCP stdio 服务（需安装 mcp 包）。"""

from __future__ import annotations

from .tools import TOOL_SPECS, dispatch_tool


def run_stdio() -> None:
    try:
        # 可选依赖：pip install 'autopilot_platform[mcp]'
        from mcp.server.fastmcp import FastMCP  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "缺少依赖 mcp。安装: pip install 'autopilot_platform[mcp]'\n"
            "或仅用: python -m autopilot_platform.platform.mcp_readonly list-tools"
        ) from exc

    mcp = FastMCP("autopilot-platform-readonly")

    @mcp.tool()
    def list_jobs(limit: int = 20, offset: int = 0, project_id: str = "") -> str:
        """List Platform jobs. Read-only."""
        return dispatch_tool(
            "list_jobs",
            {"limit": limit, "offset": offset, "project_id": project_id},
        )

    @mcp.tool()
    def get_job(job_id: str) -> str:
        """Get one job by id. Read-only."""
        return dispatch_tool("get_job", {"job_id": job_id})

    @mcp.tool()
    def list_devices(limit: int = 50) -> str:
        """List devices. Read-only."""
        return dispatch_tool("list_devices", {"limit": limit})

    @mcp.tool()
    def get_job_report(job_id: str) -> str:
        """Get job report summary. Read-only."""
        return dispatch_tool("get_job_report", {"job_id": job_id})

    # 保留 TOOL_SPECS 供文档/自检；FastMCP 以装饰器注册为准
    _ = TOOL_SPECS
    mcp.run(transport="stdio")

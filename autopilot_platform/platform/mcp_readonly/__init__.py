"""E3：Platform MCP 只读薄适配（查 Job / 设备 / 报告；不执行用例）。"""

from .client import PlatformReadonlyClient
from .tools import TOOL_SPECS, dispatch_tool

__all__ = ["PlatformReadonlyClient", "TOOL_SPECS", "dispatch_tool"]

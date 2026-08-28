"""安全 ZIP 解压：转发到 ``autopilot_platform.core.safe_zip``（AUD-2026-19）。"""

from autopilot_platform.core.safe_zip import (
    DEFAULT_MAX_ENTRIES,
    DEFAULT_MAX_RATIO,
    DEFAULT_MAX_TOTAL_UNCOMPRESSED,
    safe_extractall,
)

__all__ = [
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_MAX_RATIO",
    "DEFAULT_MAX_TOTAL_UNCOMPRESSED",
    "safe_extractall",
]

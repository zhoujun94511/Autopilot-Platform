"""移动端设备层：adb / iOS 引导 / 策略（装包解析见 ``autopilot_platform.appparse``）。

与 ``autopilot_platform.ap.keywords.mobile``（用例关键字）分离。
"""

from autopilot_platform.appparse import PackageError

__all__ = [
    "PackageError",
]

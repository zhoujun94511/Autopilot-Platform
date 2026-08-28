"""WebUI 关键字（Selenium 4）。导入子模块以触发 @keyword 注册。"""

from . import browser   # noqa: F401
from . import element   # noqa: F401
from . import verify    # noqa: F401  校验类关键字（Verify + Common）
from . import image     # noqa: F401  图像识别（opencv 模板匹配）

__all__ = ["browser", "element", "verify", "image"]

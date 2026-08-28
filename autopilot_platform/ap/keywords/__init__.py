"""关键字库：注册表 + 各分类关键字实现（插件化）。"""

from .registry import keyword, REGISTRY, KeywordDef, KeywordError, NotImplementedKeyword
from .context import ExecutionContext

# 导入各关键字模块以触发注册（装饰器在 import 时登记到 REGISTRY）
from . import builtin  # noqa: F401  内置/逻辑/校验关键字（无外部依赖）
from . import web      # noqa: F401  WebUI 关键字（Selenium）
from . import http     # noqa: F401  Http/协议 关键字（httpx/JSON/XML）
from . import mobile   # noqa: F401  Mobile 关键字（Appium，appium 懒加载）
from . import data     # noqa: F401  数据类关键字（DB/Redis/SSH/FTP）
from . import public   # noqa: F401  Public 通用工具关键字（CommonKeyword）
from ..intent import keyword as _intent_keyword  # noqa: F401  intent_act

__all__ = [
    "keyword",
    "REGISTRY",
    "KeywordDef",
    "KeywordError",
    "NotImplementedKeyword",
    "ExecutionContext",
]

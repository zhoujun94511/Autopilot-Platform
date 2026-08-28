"""Http / 协议关键字（httpx + jsonpath-ng + lxml）。导入子模块触发注册。"""

from . import client         # noqa: F401  http_get/post/put/delete/patch + 扩展
from . import session        # noqa: F401  http_session_begin/end
from . import auth           # noqa: F401  Basic/Bearer/API-Key
from . import assert_kw      # noqa: F401  status/time/schema 断言
from . import env            # noqa: F401  api_env_use
from . import json_keywords  # noqa: F401  JSON jsonpath / xpath 关键字
from . import xml_keywords   # noqa: F401  XML xpath 关键字

__all__ = [
    "client",
    "session",
    "auth",
    "assert_kw",
    "env",
    "json_keywords",
    "xml_keywords",
]

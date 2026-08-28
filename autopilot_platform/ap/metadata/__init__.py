"""关键字元数据：读取关键字定义 XML（中文名/参数/说明/下拉值），驱动 UI 参数表单。"""

from .keyword_meta import (
    ParamMeta,
    KeywordMeta,
    KeywordCatalog,
    load_catalog,
)

__all__ = ["ParamMeta", "KeywordMeta", "KeywordCatalog", "load_catalog"]

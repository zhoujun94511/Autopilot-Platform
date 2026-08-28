"""加载关键字元数据 XML（config/*.xml）。

结构（见 config/01 keyword WebUI.xml）：
  <root> → <group name> (可嵌套) → <keyword id> → name/comment/implement/show + <param id>*
每个 param 含 name/default/values(下拉,\\r\\n分隔)/required(T/F)/comment。

不重新录入关键字签名，直接读关键字定义 XML 驱动参数表单。
不需要打包的分类（如 SAP/Service RSF/内部 Mock）在加载时可通过 exclude 过滤掉。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

# noinspection PyUnresolvedReferences
from lxml import etree
from lxml.etree import ElementBase


@dataclass
class ParamMeta:
    param_id: str
    name: str = ""
    default: str = ""
    values: list[str] = field(default_factory=list)  # 下拉候选
    required: bool = False
    comment: str = ""
    is_output: bool = False  # 名称含 [OUT] 视为输出变量


@dataclass
class KeywordMeta:
    keyword_id: str
    name: str = ""
    comment: str = ""
    implement: str = ""            # 实现绑定「类:方法」
    category: str = ""             # 来源文件标识（WebUI/Http/...）
    group_path: list[str] = field(default_factory=list)  # 分组层级（中文）
    params: list[ParamMeta] = field(default_factory=list)
    unsupported: bool = False           # 平台专有能力，纯 Python 不支持实现
    unsupported_reason: str = ""        # 不支持的原因（UI 悬停提示）
    platforms: list[str] = field(default_factory=list)   # XML 声明：android / ios / web
    target_platforms: frozenset[str] = field(default_factory=frozenset)  # 空=任意平台
    risk_level: str = ""  # read | write | irreversible（可选 XML 属性）


# 按 implement 类名判定「平台专有-不支持」。这些绑定 COM/桌面控件/私有平台/私有协议，
# 不在纯 Python 可实现范围（详见 docs/provenance/source-mapping.md）。
_UNSUPPORTED_CLASS_REASON = {
    "SAPKeyword": "SAP GUI 桌面控件自动化（COM / SAP GUI Scripting），平台专有，纯 Python 不可实现",
    "MockKeyword": "内部 Mock/RSF 埋桩平台专有；通用打桩请改用 http_setMock 等中性 Mock 关键字",
    "MqKeyword": "IBM MQ 私有队列中间件；消息队列测试请改用 Kafka 关键字",
    "WindqKeyword": "WindQ 私有队列中间件；消息队列测试请改用 Kafka 关键字",
    "HessianKeyword": "Hessian 私有 RPC，平台专有，不支持",
}


def classify_unsupported(implement: str) -> tuple[bool, str]:
    klass = (implement or "").split(":", 1)[0].strip()
    reason = _UNSUPPORTED_CLASS_REASON.get(klass, "")
    return bool(reason), reason


class KeywordCatalog:
    """全部关键字元数据的目录，按 id 索引，保留分组树用于 UI 展示。"""

    def __init__(self) -> None:
        self.by_id: dict[str, KeywordMeta] = {}

    def add(self, meta: KeywordMeta) -> None:
        self.by_id[meta.keyword_id] = meta

    def get(self, keyword_id: str) -> Optional[KeywordMeta]:
        return self.by_id.get(keyword_id)

    def __len__(self) -> int:
        return len(self.by_id)

    def categories(self) -> dict[str, int]:
        c: dict[str, int] = {}
        for m in self.by_id.values():
            c[m.category] = c.get(m.category, 0) + 1
        return c

    def unsupported_count(self) -> int:
        """平台专有-不支持的关键字数（覆盖率口径中应从分母剔除）。"""
        return sum(1 for m in self.by_id.values() if m.unsupported)

    def supported_total(self) -> int:
        """可实现范围的关键字总数（= 全部 - 平台专有不支持）。"""
        return len(self.by_id) - self.unsupported_count()


def _split_values(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    # 下拉项以字面 \r\n 分隔
    parts = raw.replace("\r\n", "\n").replace("\\r\\n", "\n").split("\n")
    return [p.strip() for p in parts if p.strip()]


def _parse_keyword_platforms(el: ElementBase) -> list[str]:
    """解析 keyword 的 platforms 属性或 <platforms> 子节点。"""
    raw = (el.get("platforms") or "").strip()
    if not raw:
        child = el.find("platforms")
        if child is not None and (child.text or "").strip():
            raw = child.text.strip()
    if not raw:
        return []
    items: list[str] = []
    for part in raw.replace(";", ",").replace("\n", ",").split(","):
        p = part.strip().lower()
        if p and p not in items:
            items.append(p)
    return items


def _parse_param(el: ElementBase) -> ParamMeta:
    def t(tag: str) -> str:
        c = el.find(tag)
        return (c.text or "").strip() if c is not None and c.text else ""

    name = t("name")
    return ParamMeta(
        param_id=el.get("id", ""),
        name=name,
        default=t("default"),
        values=_split_values(t("values")),
        required=t("required").upper() == "T",
        comment=t("comment"),
        is_output="[OUT]" in name.upper(),
    )


def _walk_group(
    group: ElementBase,
    catalog: KeywordCatalog,
    category: str,
    path: list[str],
) -> None:
    gname = group.get("name", "")
    cur_path = path + [gname] if gname else path
    for child in group:
        if child.tag == "group":
            _walk_group(child, catalog, category, cur_path)
        elif child.tag == "keyword":
            kid = child.get("id", "")

            def t(tag: str) -> str:
                c = child.find(tag)
                return (c.text or "").strip() if c is not None and c.text else ""

            implement = t("implement")
            unsupported, reason = classify_unsupported(implement)
            raw_risk = (child.get("risk_level") or "").strip().lower()
            if raw_risk not in ("", "read", "write", "irreversible"):
                raw_risk = ""
            meta = KeywordMeta(
                keyword_id=kid,
                name=t("name"),
                comment=t("comment"),
                implement=implement,
                category=category,
                group_path=cur_path,
                params=[_parse_param(p) for p in child.findall("param")],
                unsupported=unsupported,
                unsupported_reason=reason,
                platforms=_parse_keyword_platforms(child),
                risk_level=raw_risk,
            )
            catalog.add(meta)


# 关键字定义资源目录：作为应用数据随包发布，与加载方 keyword_meta.py 同处 metadata 包内
BUNDLED_KEYWORD_DEFS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keyword_defs")

# 剥离后的文件名 → 分类标识（Service 整类不打包）
_FILE_CATEGORY = {
    "webui.xml": "WebUI",
    "http.xml": "Http",
    "public.xml": "Public",
    "mobile.xml": "Mobile",
}

# 预留：若将来接回 referencedata 全量，可在此声明默认排除分类
DEFAULT_EXCLUDE: set[str] = set()


def load_catalog(
    config_dir: Optional[str] = None,
    exclude_categories: Optional[set[str]] = None,
) -> KeywordCatalog:
    """加载关键字定义 xml。config_dir 为 None 时用项目内剥离的资源目录。

    exclude_categories 控制运行时再砍掉的分类（默认无，因 Service 已不打包）。
    """
    config_dir = config_dir or BUNDLED_KEYWORD_DEFS
    exclude = DEFAULT_EXCLUDE if exclude_categories is None else exclude_categories
    catalog = KeywordCatalog()
    for fname, category in _FILE_CATEGORY.items():
        if category in exclude:
            continue
        path = os.path.join(config_dir, fname)
        if not os.path.exists(path):
            continue
        root = etree.parse(path).getroot()
        for group in root.findall("group"):
            _walk_group(group, catalog, category, [])
    # 已实现并注册的关键字，即便历史 implement 类名属"不支持"族，也视为支持(不灰显)——
    # 补齐某保留占位的实现后，它会自动脱离灰显。
    # noinspection PyBroadException
    try:
        import autopilot_platform.ap.keywords  # noqa: F401  触发关键字注册（幂等）
        from autopilot_platform.ap.keywords.registry import REGISTRY, apply_risk_levels

        for m in catalog.by_id.values():
            if m.unsupported and m.keyword_id in REGISTRY:
                m.unsupported = False
                m.unsupported_reason = ""
        apply_risk_levels(
            {m.keyword_id: m.risk_level for m in catalog.by_id.values() if m.risk_level}
        )
    except Exception:
        pass
    from .keyword_platforms import apply_platform_metadata
    apply_platform_metadata(catalog)
    return catalog

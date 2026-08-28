"""执行上下文：变量池 + 参数值解析 + 运行期资源（对象库、driver 等）。

负责把 step 里的原始参数文本解析成实际值：
  - 变量引用      ${var} 或 $var$
  - 数据池列绑定  COLUMN(列名,默认值)   —— MVP 暂取默认值
  - 对象库引用    map::文件::元素        —— 解析为 Locator
  - 直接定位      xpath::.. / id::.. ..  —— 解析为 Locator
  - 字面量        原样返回
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ..model.mapfile import Locator, MapFile


_VAR_BRACE = re.compile(r"\$\{([^}]+)}")
_VAR_DOLLAR = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)\$")
# 整串恰为单个变量引用（用于保留对象类型，如 header/cookie 对象、列表）
_WHOLE_BRACE = re.compile(r"^\$\{([^}]+)}$")
_WHOLE_DOLLAR = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)\$$")
_COLUMN = re.compile(r"^COLUMN\(([^,]*),?(.*)\)$", re.IGNORECASE)

# 直接定位前缀（不走对象库），见 file-format-spec §5
_DIRECT_LOCATOR_PREFIXES = {
    "id": "ID",
    "name": "NAME",
    "xpath": "XPATH",
    "css": "CSS",
    "predicate": "PREDICATE",
    "classname": "CLASS",
    "class-chain": "CLASS_CHAIN",
    "linktext": "TEXT",
    "commonid": "ID",
}


class ExecutionContext:
    def __init__(self) -> None:
        self.variables: dict[str, Any] = {}
        self.maps: dict[str, MapFile] = {}   # 文件名(去后缀) -> MapFile
        self.driver: Any = None              # 运行期注入（selenium/appium）
        self.data_row: dict[str, Any] = {}   # 数据驱动当前行（COLUMN 解析来源）
        self.logs: list[str] = []
        # HTTP 会话（keywords.http.session.HttpSessionState | None）
        self.http_session: Any = None
        # 最近一次 HTTP 响应摘要（供 assert 关键字）
        self.last_http: dict[str, Any] = {}

    def load_dataconfig(self, cfg: Any) -> None:
        """把 DataConfig（或 dict）的键值载入变量池作为基线变量。"""
        items = cfg.as_dict().items() if hasattr(cfg, "as_dict") else dict(cfg).items()
        for k, v in items:
            self.variables.setdefault(k, v)

    # ---- 变量 ----
    def set_var(self, name: str, value: Any) -> None:
        self.variables[name] = value

    def get_var(self, name: str, default: Any = "") -> Any:
        return self.variables.get(name, default)

    def expand_vars(self, text: str) -> str:
        """把字符串里的 ${x} / $x$ 替换为变量值。"""

        def brace(m: re.Match) -> str:
            return str(self.variables.get(m.group(1), m.group(0)))

        def dollar(m: re.Match) -> str:
            return str(self.variables.get(m.group(1), m.group(0)))

        text = _VAR_BRACE.sub(brace, text)
        text = _VAR_DOLLAR.sub(dollar, text)
        return text

    # ---- 对象库 ----
    def register_map(self, mapfile: MapFile) -> None:
        self.maps[mapfile.name] = mapfile

    def resolve_locator(self, ref: str) -> Optional[Locator]:
        """把 map::文件::元素 或 xpath::.. 解析为 Locator。非定位串返回 None。"""
        parts = ref.split("::")
        if len(parts) >= 3 and parts[0] == "map":
            map_name = parts[1]
            if map_name.endswith(".map"):
                map_name = map_name[:-4]
            el_name = parts[2]
            mf = self.maps.get(map_name)
            if mf is None:
                raise KeyError(f"对象库未加载: {map_name}")
            el = mf.find(el_name)
            # 按当前设备平台选定位符(对标 Appium @AndroidFindBy/@iOSXCUITFindBy)：
            # 平台从移动会话管理器 duck-typed 读取(context 不依赖 mobile 模块)，无会话则用通用。
            mgr = getattr(self, "appium", None)
            plat = getattr(mgr, "platform", "")
            backend = getattr(mgr, "backend", "")
            loc = el.locator_for_target(plat, backend) if el is not None else None
            if el is None or loc is None:
                raise KeyError(f"对象库元素未找到: {map_name}::{el_name}")
            return loc
        if len(parts) == 2 and parts[0] in _DIRECT_LOCATOR_PREFIXES:
            return Locator(type=_DIRECT_LOCATOR_PREFIXES[parts[0]], value=parts[1])
        return None

    # ---- 参数值解析 ----
    def resolve(self, raw: Optional[str]) -> Any:
        """解析一个参数原始文本为实际值（变量展开 + 列绑定 + 对象库）。"""
        if raw is None:
            return None
        stripped = raw.strip()
        # 容错值列表 a||b||c：从左到右解析，取首个「非空」结果；全空则返回最后一段解析值。
        # 每段递归解析（可含 ${}/COLUMN(...)/map::），段内不再含 ||，无递归风险。
        if "||" in stripped:
            last: Any = None
            for part in stripped.split("||"):
                last = self.resolve(part.strip())
                if last is not None and str(last).strip() != "":
                    return last
            return last
        # 整串恰为单个变量引用 → 保留对象类型（header/cookie 对象、dict、list 等）
        whole = _WHOLE_BRACE.match(stripped) or _WHOLE_DOLLAR.match(stripped)
        if whole and whole.group(1) in self.variables:
            return self.variables[whole.group(1)]
        # 数据池列绑定：优先取当前数据行的该列值，无则用默认值
        m = _COLUMN.match(stripped)
        if m:
            col = m.group(1).strip()
            default = m.group(2)
            if col in self.data_row:
                return self.data_row[col]
            return self.expand_vars(default)
        # 对象库 / 直接定位
        if "::" in raw:
            loc = self.resolve_locator(raw)
            if loc is not None:
                return loc
        return self.expand_vars(raw)

    def log(self, msg: str) -> None:
        self.logs.append(msg)

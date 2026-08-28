"""自定义关键字(.ks)的内存模型。

.ks 把一段步骤序列封装成可复用的「组合关键字」，在用例里通过 <stepverbs id> 调用。
结构（见 file-format-spec §5）：
  <root ver db_id tag> → <id> + <steps>(<step>*，结构同 .tc 的 step)
局部参数（local param）可选地为该关键字声明形参元数据（名称/默认值/必填等），
用于调用处的参数表单与缺省值填充。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .testcase import StepNode


@dataclass
class LocalParam:
    """自定义关键字的一个形参定义（局部参数）。"""

    param_id: str
    name: str = ""
    default: str = ""
    values: list[str] = field(default_factory=list)
    required: bool = False
    datapool: str = ""
    comment: str = ""
    visible_on_platforms: list[str] = field(default_factory=list)


@dataclass
class KeywordDef:
    """一个 .ks 自定义/组合关键字定义。"""

    ks_id: str = ""                 # <id> 文本：调用处 stepverbs.id 据此匹配
    data_id: str = ""               # db_id 短 UUID（调用处也可能用它匹配）
    tag: str = ""
    params: list[LocalParam] = field(default_factory=list)
    steps: list[StepNode] = field(default_factory=list)
    source_path: str = ""

    def param(self, param_id: str) -> LocalParam | None:
        for p in self.params:
            if p.param_id == param_id:
                return p
        return None

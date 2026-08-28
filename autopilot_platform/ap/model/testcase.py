"""测试用例 / 测试套的内存模型。

解析 .tc/.ts 工程文件格式：
  root → shell(before/case/after/fault) → step / stepset / stepverbs / stepinnercase
每个 step 携带若干 <param id>值</param>。条件步骤（exec_control_if_*）可嵌套子步骤。

设计取舍：采用 shell + 步骤树语义，但用干净的 dataclass 表达，
不绑定任何 XML 序列化细节——导入器负责把 XML 翻译成这些对象。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union


# 条件控制关键字 id（用于把普通 step 识别为可嵌套子步骤的条件块）
CONDITION_KEYWORD_IDS = {
    "exec_control_if_else_end",
    "exec_control_if_end",
    "else",
    "end",
}


@dataclass
class ParamValue:
    """关键字调用的单个参数：<param id="...">value</param>。

    value 是原始文本，可能含变量引用 ${x}、对象库引用 map::file::el、
    数据池列绑定 COLUMN(列,默认值) 等——这些在执行期由 context 解析，模型层只存原文。
    """

    param_id: str
    value: str = ""


@dataclass
class Step:
    """关键字调用步骤：<step id=keyword_id comment remark isrun>。"""

    keyword_id: str
    comment: str = ""              # 关键字通用说明快照（插入时写入，供离线/无目录时回退）
    remark: str = ""               # 用例维护备注：本步骤在用例中的具体意图
    is_run: bool = True
    params: list[ParamValue] = field(default_factory=list)
    # 条件步骤（keyword_id ∈ CONDITION_KEYWORD_IDS）可携带子步骤（if/else 块体）
    children: list["StepNode"] = field(default_factory=list)

    @property
    def is_condition(self) -> bool:
        return self.keyword_id in CONDITION_KEYWORD_IDS

    def param(self, param_id: str) -> Optional[str]:
        for p in self.params:
            if p.param_id == param_id:
                return p.value
        return None


# 条件步骤是 Step 的一种用法，这里给个别名让导入器/引擎语义更清晰。
ConditionStep = Step


@dataclass
class StepVerbs:
    """调用用户自定义关键字(.ks)：<stepverbs id=ks_id comment isrun>。"""

    ks_id: str
    comment: str = ""
    remark: str = ""
    is_run: bool = True
    params: list[ParamValue] = field(default_factory=list)

    def param(self, param_id: str) -> Optional[str]:
        for p in self.params:
            if p.param_id == param_id:
                return p.value
        return None


@dataclass
class StepSet:
    """步骤组：<stepset name comment datapool isrun>，可绑定数据池循环。"""

    name: str = ""
    comment: str = ""
    remark: str = ""
    datapool: str = ""
    is_run: bool = True
    children: list["StepNode"] = field(default_factory=list)


@dataclass
class StepInnerCase:
    """内嵌引用另一个 .tc：<stepinnercase relativepath comment isrun>。"""

    relative_path: str = ""
    comment: str = ""
    remark: str = ""
    is_run: bool = True


# 步骤树里允许出现的节点类型
StepNode = Union[Step, StepVerbs, StepSet, StepInnerCase]


@dataclass
class Shell:
    """before/case/after/fault 之一，承载一段步骤序列。"""

    name: str  # "before" | "case" | "after" | "fault"
    steps: list[StepNode] = field(default_factory=list)


@dataclass
class Desc:
    author: str = ""
    create_time: str = ""
    last_modify_author: str = ""
    last_modify_time: str = ""
    versions: str = ""
    description: str = ""
    precondition: str = ""  # 逻辑用例导入等扩展字段


@dataclass
class TestCase:
    """.tc 用例。"""

    name: str = ""
    data_id: str = ""           # db_id 短 UUID
    tag: str = ""               # 步骤类型标签汇总（WEB/HTTP/MOBILE...）
    platform: str = ""          # 目标平台标记：""=通用/未指定 / "android" / "ios"；执行前据此校验设备
    is_execute: bool = True
    able_invoked: bool = False
    datapool: str = "DATATABLE(NONE,false)"
    desc: Desc = field(default_factory=Desc)

    before: Shell = field(default_factory=lambda: Shell("before"))
    case: Shell = field(default_factory=lambda: Shell("case"))
    after: Shell = field(default_factory=lambda: Shell("after"))
    fault: Shell = field(default_factory=lambda: Shell("fault"))

    # schema 2.0：与 Platform 逻辑用例 / 制品追踪对齐（空=纯本地用例）
    schema_version: str = ""
    project_id: str = ""
    logical_case_id: str = ""
    automation_case_id: str = ""
    revision_id: str = ""
    case_key: str = ""

    # 来源信息（导入时记录），方便回溯
    source_path: str = ""

    @property
    def shells(self) -> list[Shell]:
        return [self.before, self.case, self.after, self.fault]


@dataclass
class TestSuite:
    """.ts 测试套（无 case shell，不支持 stepinnercase）。"""

    name: str = ""
    data_id: str = ""
    tag: str = ""
    datapool: str = "DATATABLE(NONE,true)"

    before: Shell = field(default_factory=lambda: Shell("before"))
    after: Shell = field(default_factory=lambda: Shell("after"))
    fault: Shell = field(default_factory=lambda: Shell("fault"))

    source_path: str = ""

    @property
    def shells(self) -> list[Shell]:
        return [self.before, self.after, self.fault]

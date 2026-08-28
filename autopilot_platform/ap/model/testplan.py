"""测试计划(.tp)的内存模型。

测试计划描述一次本地执行的配置：用哪个数据配置、失败重试次数、计划起止时间，
以及计划包含的成员（用例/套件的相对路径）。
（远程执行/平台相关字段属平台专有能力，不在实现范围，见 docs/provenance。）
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TestPlan:
    name: str = ""
    dataconfig: str = ""        # 关联的数据配置文件名
    fault_times: int = 0        # 失败重试次数
    start_time: str = ""
    end_time: str = ""
    members: list[str] = field(default_factory=list)  # 成员用例/套件的相对路径
    source_path: str = ""

"""执行引擎：遍历用例步骤树，派发关键字，处理条件/循环/容错；批量执行聚合。"""

from .executor import Executor, StepResult, RunResult, FaultStrategy
from .suite import (
    SuiteResult,
    run_cases,
    run_directory,
    discover_cases,
    load_entry_cases,
    run_testplan,
    expand_testplan_members,
    load_case,
    load_map,
)
from .run import RunConfig, run_suite, run_project_directory

__all__ = [
    "Executor",
    "StepResult",
    "RunResult",
    "FaultStrategy",
    "SuiteResult",
    "run_cases",
    "run_directory",
    "discover_cases",
    "load_entry_cases",
    "run_testplan",
    "expand_testplan_members",
    "load_case",
    "load_map",
    "RunConfig",
    "run_suite",
    "run_project_directory",
]

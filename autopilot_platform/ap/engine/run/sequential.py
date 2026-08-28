"""串行策略：包装现有 run_cases，默认行为不变。"""

from __future__ import annotations

from .config import RunConfig
from ..suite import run_cases, SuiteResult
from ...model.testcase import TestCase


def run_sequential(testcases: list[TestCase], config: RunConfig) -> SuiteResult:
    return run_cases(
        testcases,
        name=config.name,
        fault_strategy=config.fault_strategy,
        base_vars=config.base_vars,
        maps=config.maps,
        keyword_store=config.keyword_store,
        cancel_event=config.cancel_event,
        pause_event=config.pause_event,
        on_step=config.on_step,
        on_case=config.on_case,
        on_context=config.on_context,
        fault_times=int(getattr(config, "fault_times", 0) or 0),
    )

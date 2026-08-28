"""统一运行入口：按 RunConfig.mode 选择策略。"""

from __future__ import annotations

import os
from typing import Optional

from .config import RunConfig
from .registry import get, register
from .sequential import run_sequential
from .parallel import run_parallel_device
from ..executor import FaultStrategy
from ..suite import (
    SuiteResult,
    discover_cases,
    discover_maps,
    load_entry_cases,
    _load_case,
    _load_map,
)
from ..keyword_store import discover_keywords
from ...model.testcase import TestCase
from ...runtime.device_pool import build_sessions

# 注册内置策略
register("sequential", run_sequential)
register("parallel_device", run_parallel_device)


def run_suite(
    testcases: list[TestCase],
    *,
    name: str = "Suite",
    mode: str = "sequential",
    platform: str = "",
    parallel_workers: int = 0,
    device_udids: Optional[list[str]] = None,
    wda_bundle: str = "",
    backend_mode: str = "auto",
    fault_strategy: FaultStrategy = FaultStrategy.CONTINUE,
    base_vars: Optional[dict] = None,
    maps=None,
    keyword_store=None,
    cancel_event=None,
    pause_event=None,
    on_step=None,
    on_case=None,
    on_context=None,
    parallel_fault_isolation: bool = True,
    fault_times: int = 0,
) -> SuiteResult:
    """无头 / IDE 共用入口。"""
    from ...runtime.device_runtime import DeviceRuntimeLease

    vars_ = dict(base_vars or {})
    sessions = []
    with DeviceRuntimeLease() as lease:
        if mode == "parallel_device":
            if not device_udids:
                raise RuntimeError("parallel_device 模式需要 device_udids")
            sessions = build_sessions(
                platform, device_udids, workers=parallel_workers, wda_bundle=wda_bundle,
                backend_mode=backend_mode, lease=lease)
            vars_["__parallel_device_udids__"] = [s.udid for s in sessions]
            vars_["__parallel_platform__"] = platform
            vars_.pop("__device_udid__", None)
            vars_.pop("__appium_caps__", None)
            vars_.pop("__appium_server__", None)
        else:
            udid = str(vars_.get("__device_udid__") or "").strip()
            if not udid and device_udids:
                udid = str(device_udids[0]).strip()
            plat = (platform or "").strip().lower()
            if udid and (plat.startswith("android") or plat.startswith("ios") or not plat):
                from ...runtime.device_session import DeviceSession

                bind_plat = plat if plat.startswith(("android", "ios")) else "android"
                sess = DeviceSession.for_device(
                    bind_plat, udid, wda_bundle=wda_bundle, backend_mode=backend_mode,
                )
                lease.hold([udid])
                vars_.update(sess.to_ctx_vars())
            elif plat == "ios" and udid:
                from ...mobile import ios_bootstrap as ib
                ib.merge_appium_ios_caps(vars_, udid, wda_bundle, backend_mode)

        run_config = RunConfig(
            name=name,
            mode=mode,
            platform=platform,
            parallel_workers=parallel_workers,
            fault_strategy=fault_strategy,
            base_vars=vars_,
            maps=list(maps or []),
            keyword_store=keyword_store,
            device_sessions=sessions,
            cancel_event=cancel_event,
            pause_event=pause_event,
            on_step=on_step,
            on_case=on_case,
            on_context=on_context,
            parallel_fault_isolation=parallel_fault_isolation,
            fault_times=int(fault_times or 0),
        )
        return get(mode)(testcases, run_config)


def run_project_directory(
    directory: str,
    *,
    mode: str = "sequential",
    platform: str = "",
    parallel_workers: int = 0,
    device_udids: Optional[list[str]] = None,
    wda_bundle: str = "",
    backend_mode: str = "auto",
    fault_strategy: FaultStrategy = FaultStrategy.CONTINUE,
    base_vars: Optional[dict] = None,
    cancel_event=None,
    pause_event=None,
    on_step=None,
    on_case=None,
    parallel_fault_isolation: bool = True,
    entry_paths: Optional[list[str]] = None,
) -> SuiteResult:
    paths = [p for p in (entry_paths or []) if (p or "").strip()]
    if paths:
        cases = load_entry_cases(directory, paths)
    else:
        cases = [_load_case(p) for p in discover_cases(directory)]
    maps = [_load_map(p) for p in discover_maps(directory)]
    store = discover_keywords(directory)
    name = os.path.basename(directory.rstrip("/\\")) or "Suite"
    vars_ = dict(base_vars or {})
    vars_.setdefault("__project_path__", directory)
    return run_suite(
        cases,
        name=name,
        mode=mode,
        platform=platform,
        parallel_workers=parallel_workers,
        device_udids=device_udids,
        wda_bundle=wda_bundle,
        backend_mode=backend_mode,
        fault_strategy=fault_strategy,
        base_vars=vars_,
        maps=maps,
        keyword_store=store,
        cancel_event=cancel_event,
        pause_event=pause_event,
        on_step=on_step,
        on_case=on_case,
        parallel_fault_isolation=parallel_fault_isolation,
    )

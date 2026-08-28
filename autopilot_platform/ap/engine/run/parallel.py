"""同平台多设备并行：每台设备完整跑同一批用例 + ThreadPoolExecutor。

批量并行语义：勾选 N 条用例、启用 M 台设备 → 每台各跑 N 条（共 N×M 次），
不是把用例拆开分给不同设备。
"""

from __future__ import annotations

import copy
import logging
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed, Future, wait, FIRST_COMPLETED

from .config import RunConfig
from ..executor import RunResult, StepResult
from ..suite import run_cases, SuiteResult
from ...model.testcase import TestCase
from ...runtime.job_log import get_job_log_id, reset_job_log_id, set_job_log_id

log = logging.getLogger("autopilot.engine.parallel")

# 停止后等待各设备协作退出并交出结果的最长秒数
STOP_DRAIN_TIMEOUT_SEC = 30.0


def _merge_results(ordered: list[tuple[int, SuiteResult]]) -> list:
    """按设备 slot 序号合并，保持各设备内用例顺序。"""
    ordered.sort(key=lambda x: x[0])
    out = []
    for _idx, suite in ordered:
        out.extend(suite.results)
    return out


def _fail_suite_for_slot(
    slot_idx: int, udid: str, cases: list[TestCase], exc: BaseException,
) -> tuple[int, SuiteResult]:
    """Worker 崩溃时合成可见 FAIL，避免该设备结果静默消失。"""
    msg = f"并行 worker 异常（slot={slot_idx} udid={udid}）：{exc}"
    log.error("%s\n%s", msg, traceback.format_exc())
    results = []
    for tc in cases or [TestCase(name="(worker)")]:
        results.append(RunResult(
            case_name=getattr(tc, "name", "") or "(worker)",
            source_path=getattr(tc, "source_path", "") or "",
            platform=(getattr(tc, "platform", "") or "").strip(),
            tag=(getattr(tc, "tag", "") or "").strip(),
            device_udid=udid or "",
            worker_slot=slot_idx,
            results=[StepResult(
                keyword_id="parallel_worker",
                comment="并行设备执行异常",
                status="FAIL",
                message=msg,
            )],
        ))
    return slot_idx, SuiteResult(name=f"slot{slot_idx}", results=results)


def _collect_done(
    futures: dict[Future, int],
    results: list[tuple[int, SuiteResult]],
    seen: set[Future],
    sessions,
    testcases: list[TestCase],
) -> None:
    """把已完成且尚未收录的 future 结果并入 results（含异常合成 FAIL）。"""
    for fut in futures:
        if fut in seen or not fut.done() or fut.cancelled():
            continue
        seen.add(fut)
        slot_idx = futures[fut]
        udid = sessions[slot_idx].udid if sessions and slot_idx < len(sessions) else ""
        # noinspection PyBroadException
        try:
            results.append(fut.result())
        except Exception as e:  # noqa: BLE001
            results.append(_fail_suite_for_slot(slot_idx, udid, testcases, e))


def _drain_after_cancel(
    pool: ThreadPoolExecutor,
    futures: dict[Future, int],
    results: list[tuple[int, SuiteResult]],
    seen: set[Future],
    sessions,
    testcases: list[TestCase],
    timeout_sec: float = STOP_DRAIN_TIMEOUT_SEC,
) -> None:
    """cancel 后限时等待未完成 future，尽量合并结果再强制 shutdown。"""
    _collect_done(futures, results, seen, sessions, testcases)
    pending = [f for f in futures if f not in seen and not f.cancelled()]
    if not pending:
        pool.shutdown(wait=False, cancel_futures=True)
        return
    deadline = time.monotonic() + max(0.0, timeout_sec)
    while pending and time.monotonic() < deadline:
        remain = max(0.01, deadline - time.monotonic())
        done, _not_done = wait(pending, timeout=min(0.5, remain), return_when=FIRST_COMPLETED)
        if not done:
            pending = [f for f in pending if not f.done()]
            continue
        for fut in done:
            if fut in seen:
                continue
            seen.add(fut)
            slot_idx = futures[fut]
            udid = sessions[slot_idx].udid if sessions and slot_idx < len(sessions) else ""
            # noinspection PyBroadException
            try:
                results.append(fut.result())
            except Exception as e:  # noqa: BLE001
                results.append(_fail_suite_for_slot(slot_idx, udid, testcases, e))
        pending = [f for f in futures if f not in seen and not f.cancelled()]
    # 超时仍未完成：强制取消，已收录的结果保留
    pool.shutdown(wait=False, cancel_futures=True)
    _collect_done(futures, results, seen, sessions, testcases)


def run_parallel_device(testcases: list[TestCase], config: RunConfig) -> SuiteResult:
    if not testcases:
        return SuiteResult(name=config.name, duration_ms=0)

    sessions = config.device_sessions
    if not sessions:
        raise RuntimeError("并行执行需要 device_sessions（由 run_suite 或 UI 构建）")

    n = len(sessions)
    start = time.time()
    lock = threading.Lock()
    step_cb = config.on_step
    case_cb = config.on_case
    isolate = bool(getattr(config, "parallel_fault_isolation", True))
    drain_timeout = float(getattr(config, "parallel_stop_drain_sec", STOP_DRAIN_TIMEOUT_SEC))
    parent_log_id = get_job_log_id()

    def wrap_step(sr, slot: int, device_udid: str):
        if step_cb is None:
            return
        prefix = f"[slot:{slot} udid:{device_udid}] "
        if hasattr(sr, "message") and sr.message:
            sr.message = prefix + str(sr.message)
        with lock:
            step_cb(sr)

    def worker(worker_slot: int, batch: list[TestCase]) -> tuple[int, SuiteResult]:
        prev = set_job_log_id(parent_log_id)
        try:
            sess = sessions[worker_slot]
            # deepcopy base_vars，避免嵌套 dict/list 跨设备串台；再覆盖本 slot 设备注入
            vars_ = {**copy.deepcopy(config.base_vars or {}), **sess.to_ctx_vars()}
            vars_.pop("__parallel_device_udids__", None)
            return worker_slot, run_cases(
                batch,
                name=f"{config.name}/slot{worker_slot}",
                fault_strategy=config.fault_strategy,
                base_vars=vars_,
                maps=config.maps,  # 只读约定：勿在关键字内就地改对象库
                keyword_store=config.keyword_store,
                cancel_event=config.cancel_event,
                pause_event=config.pause_event,
                on_step=(lambda sr, s=sess: wrap_step(sr, s.slot, s.udid)) if step_cb else None,
                on_case=case_cb,
                on_context=config.on_context,
                fault_times=int(getattr(config, "fault_times", 0) or 0),
            )
        finally:
            reset_job_log_id(prev)

    results: list[tuple[int, SuiteResult]] = []
    seen: set[Future] = set()
    pool = ThreadPoolExecutor(max_workers=n)
    try:
        futures: dict[Future, int] = {
            pool.submit(worker, i, copy.deepcopy(testcases)): i
            for i in range(n)
        }
        aborted = False
        for fut in as_completed(futures):
            if fut in seen:
                continue
            seen.add(fut)
            slot_idx = futures[fut]
            udid = sessions[slot_idx].udid
            # noinspection PyBroadException
            try:
                slot_result = fut.result()
                results.append(slot_result)
                if not isolate and config.cancel_event is not None:
                    _suite = slot_result[1]
                    cc = _suite.case_counts() if hasattr(_suite, "case_counts") else {}
                    if cc.get("failed", 0) > 0:
                        config.cancel_event.set()
            except Exception as e:  # noqa: BLE001
                results.append(_fail_suite_for_slot(slot_idx, udid, testcases, e))
                if not isolate and config.cancel_event is not None:
                    config.cancel_event.set()
            if config.cancel_event is not None and config.cancel_event.is_set():
                aborted = True
                break
        if aborted:
            _drain_after_cancel(
                pool, futures, results, seen, sessions, testcases, drain_timeout)
        else:
            pool.shutdown(wait=True)
            _collect_done(futures, results, seen, sessions, testcases)
    except Exception:
        pool.shutdown(wait=False, cancel_futures=True)
        raise

    suite = SuiteResult(name=config.name)
    suite.results = _merge_results(results)
    suite.duration_ms = int((time.time() - start) * 1000)
    return suite

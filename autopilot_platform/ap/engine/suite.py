"""批量执行：跑多个用例 / 一个目录下的用例，聚合结果。

TestSuite 按目录结构组织成员；这里提供两种入口：
- run_cases(testcases)：跑给定的一组 TestCase。
- run_directory(dir)：发现目录下所有 .tc/.tc.yaml 并运行。
每个用例用独立 ExecutionContext（相互隔离）。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .executor import Executor, RunResult, FaultStrategy
from .keyword_store import KeywordStore, discover_keywords
from ..keywords.context import ExecutionContext
from ..model.testcase import Shell, TestCase, TestSuite
from ..model.mapfile import MapFile
from ..model.loader import load_testcase, load_mapfile, load_testplan, load_testsuite
from ..model import serializer
from ..model.testplan import TestPlan
from .run_control import checkpoint


@dataclass
class SuiteResult:
    name: str
    results: list[RunResult] = field(default_factory=list)
    duration_ms: int = 0

    def case_counts(self) -> dict[str, int]:
        """按用例聚合 通过/失败 数（含 NOIMPL/FAIL 视为不通过）。"""
        passed = sum(1 for r in self.results if r.passed)
        return {"total": len(self.results), "passed": passed,
                "failed": len(self.results) - passed}

    def step_counts(self) -> dict[str, int]:
        agg: dict[str, int] = {}
        for r in self.results:
            for k, v in r.counts().items():
                agg[k] = agg.get(k, 0) + v
        return agg

    def pass_rate(self) -> float:
        c = self.case_counts()
        return (c["passed"] / c["total"] * 100) if c["total"] else 0.0


def _load_case(path: str) -> TestCase:
    if path.endswith((".tc.yaml", ".tc.yml")):
        return serializer.load(path)
    return load_testcase(path)


def load_case(path: str) -> TestCase:
    """加载 .tc / .tc.yaml 用例（工具 / CLI 公开入口）。"""
    return _load_case(path)


def discover_cases(directory: str) -> list[str]:
    """递归发现目录下的用例文件（.tc / .tc.yaml）。"""
    found: list[str] = []
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if f.endswith(".tc") or f.endswith(".tc.yaml") or f.endswith(".tc.yml"):
                found.append(os.path.join(root, f))
    return sorted(found)


def _safe_under_root(root: str, rel: str) -> str:
    """将相对路径解析到 root 下；拒绝越界。"""
    rel_n = (rel or "").strip().replace("\\", "/").lstrip("/")
    if not rel_n or ".." in rel_n.split("/"):
        raise ValueError(f"invalid entry path: {rel!r}")
    root_abs = os.path.abspath(root)
    path = os.path.normpath(os.path.join(root_abs, rel_n.replace("/", os.sep)))
    if path != root_abs and not path.startswith(root_abs + os.sep):
        raise ValueError(f"entry path escapes project: {rel!r}")
    return path


def load_entry_cases(project_dir: str, entry_paths: list[str]) -> list[TestCase]:
    """按相对路径加载用例/套件/计划（计划会展开成员）。"""
    root = os.path.abspath(project_dir)
    cases: list[TestCase] = []
    for rel in entry_paths or []:
        path = _safe_under_root(root, rel)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"entry not found: {rel}")
        low = path.lower()
        if low.endswith((".tc", ".tc.yaml", ".tc.yml")):
            tc = _load_case(path)
            if not getattr(tc, "source_path", ""):
                tc.source_path = path
            cases.append(tc)
        elif low.endswith((".ts", ".ts.yaml", ".ts.yml")):
            tc = _load_suite_as_case(path)
            if not getattr(tc, "source_path", ""):
                tc.source_path = path
            cases.append(tc)
        elif low.endswith((".tp", ".tp.yaml", ".tp.yml")):
            if low.endswith((".tp.yaml", ".tp.yml")):
                tp = serializer.load(path)
            else:
                tp = load_testplan(path)
            if not isinstance(tp, TestPlan):
                raise TypeError(f"不是测试计划: {rel}")
            if not getattr(tp, "source_path", ""):
                tp.source_path = path
            cases.extend(expand_testplan_members(tp, root))
        else:
            raise ValueError(f"unsupported entry type: {rel}")
    return cases


def discover_maps(directory: str) -> list[str]:
    found: list[str] = []
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if f.endswith(".map") or f.endswith(".map.yaml") or f.endswith(".map.yml"):
                found.append(os.path.join(root, f))
    return sorted(found)


def _load_map(path: str) -> MapFile:
    if path.endswith((".map.yaml", ".map.yml")):
        return serializer.load(path)
    return load_mapfile(path)


def load_map(path: str) -> MapFile:
    """加载 .map / .map.yaml 对象库（工具 / UI 公开入口）。"""
    return _load_map(path)


def _case_platform(tc: TestCase, base_vars: dict | None = None) -> str:
    """Return the intended mobile platform for a testcase, if it can be known."""
    base_vars = base_vars or {}
    case_platform = (getattr(tc, "platform", "") or "").lower()
    if case_platform in ("android", "ios"):
        return case_platform
    case_platforms = base_vars.get("__case_platforms__")
    if isinstance(case_platforms, dict):
        mapped = (case_platforms.get(getattr(tc, "source_path", "")) or
                  case_platforms.get(getattr(tc, "name", "")) or "")
        if str(mapped).lower() in ("android", "ios"):
            return str(mapped).lower()
    inferred = _infer_case_platform(tc)
    if inferred:
        return inferred
    default = str(base_vars.get("__default_platform__") or "").lower()
    return default if default in ("android", "ios") else ""


def _infer_case_platform(tc: TestCase) -> str:
    """Infer a single mobile platform from step params such as type/appFile."""
    found: set[str] = set()

    def visit(nodes) -> None:
        for node in nodes or []:
            params = {getattr(p, "param_id", ""): str(getattr(p, "value", "") or "")
                      for p in getattr(node, "params", [])}
            typ = (params.get("type") or params.get("platform") or "").strip().lower()
            app_file = (params.get("appFile") or params.get("app") or "").strip().lower()
            keyword_id = getattr(node, "keyword_id", "")
            if typ in ("android", "ios"):
                found.add(typ)
            elif app_file.endswith((".apk", ".apex", ".xapk")):
                found.add("android")
            elif app_file.endswith(".ipa"):
                found.add("ios")
            elif keyword_id == "mobile_browser_open":
                found.add("android")
            visit(getattr(node, "children", []))

    for shell in (getattr(tc, "before", None), getattr(tc, "case", None),
                  getattr(tc, "after", None), getattr(tc, "fault", None)):
        visit(getattr(shell, "steps", []))
    return next(iter(found)) if len(found) == 1 else ""


def _apply_case_device_vars(ctx: ExecutionContext, tc: TestCase,
                            base_vars: dict | None) -> None:
    platform = _case_platform(tc, base_vars)
    if platform:
        ctx.variables["__current_platform__"] = platform
    by_platform = (base_vars or {}).get("__device_udid_by_platform__")
    if isinstance(by_platform, dict):
        udid = by_platform.get(platform)
        if udid:
            ctx.variables["__device_udid__"] = udid


def run_cases(testcases: list[TestCase], name: str = "Suite",
              fault_strategy: FaultStrategy = FaultStrategy.CONTINUE,
              base_vars: dict | None = None,
              maps: list[MapFile] | None = None,
              keyword_store: KeywordStore | None = None,
              cancel_event=None,
              pause_event=None,
              on_step=None,
              on_case=None,
              on_context=None,
              fault_times: int = 0) -> SuiteResult:
    """批量跑用例。

    fault_times：单用例失败后再试次数（总尝试 ≤ 1+N）；成功即停；写入 suite 的是最后一次结果。
    """
    retries = max(0, int(fault_times or 0))
    suite = SuiteResult(name=name)
    start = time.time()
    for tc in testcases:
        if cancel_event is not None and cancel_event.is_set():
            break
        if pause_event is not None:
            if checkpoint(cancel_event, pause_event):
                break
        rr = None
        for attempt in range(retries + 1):
            if attempt > 0 and cancel_event is not None and cancel_event.is_set():
                break
            ctx = ExecutionContext()
            if on_context is not None:
                on_context(ctx)
            if base_vars:
                ctx.variables.update(base_vars)
                _apply_case_device_vars(ctx, tc, base_vars)
            for mf in (maps or []):
                ctx.register_map(mf)
            rr = Executor(ctx, fault_strategy, keyword_store=keyword_store,
                          cancel_event=cancel_event, pause_event=pause_event,
                          on_step=on_step).run_testcase(tc)
            # noinspection PyBroadException
            try:
                from ..keywords.mobile.driver import get_manager  # 延迟：可选 Appium 会话清理
                get_manager(ctx).close()
            except Exception:
                pass
            # noinspection PyBroadException
            try:
                web_mgr = getattr(ctx, "web", None)
                if web_mgr is not None:
                    web_mgr.quit_all()
            except Exception:
                pass
            if rr.passed or attempt >= retries:
                break
            if cancel_event is not None and cancel_event.is_set():
                break
        if rr is not None:
            suite.results.append(rr)
            if on_case is not None:
                on_case(rr)
    suite.duration_ms = int((time.time() - start) * 1000)
    _teardown_suite_appium(base_vars)
    return suite


def _teardown_suite_appium(base_vars: dict | None) -> None:
    """Suite 结束只停本趟设备绑定的 Appium 端口。

    ``AUTOPILOT_RUNNER_KEEP_APPIUM=1`` 时保留进程供下一 Job 热复用。
    无设备上下文时不调用无端口的全量 stop，避免误杀同进程其它 Job 的 Appium。
    """
    keep = os.environ.get("AUTOPILOT_RUNNER_KEEP_APPIUM", "").strip().lower()
    if keep in ("1", "true", "yes", "on"):
        return
    bv = base_vars or {}
    # noinspection PyBroadException
    try:
        from ..keywords.mobile.appium_server import stop_local_appium  # 延迟：可选 Appium
        from ..runtime.device_runtime import runtimes_for_vars  # 延迟：仅套件收尾需要端口

        runtimes = runtimes_for_vars(bv)
        if runtimes:
            for rt in runtimes:
                stop_local_appium("127.0.0.1", rt.ports.appium_port)
            return
        server = str(bv.get("__appium_server__") or "").strip()
        if server:
            parsed = urlparse(server)
            stop_local_appium(parsed.hostname or "127.0.0.1", parsed.port or 4723)
    except Exception:
        pass


def _load_suite_as_case(path: str) -> TestCase:
    """把 .ts 套件映射为可执行 TestCase（before/after/fault 保留，主体为空）。"""
    if path.endswith((".ts.yaml", ".ts.yml")):
        ts = serializer.load(path)
    else:
        ts = load_testsuite(path)
    if not isinstance(ts, TestSuite):
        raise TypeError(f"不是测试套件: {path}")
    return TestCase(
        name=ts.name or os.path.splitext(os.path.basename(path))[0],
        before=ts.before,
        case=Shell("case"),
        after=ts.after,
        fault=ts.fault,
        source_path=getattr(ts, "source_path", "") or path,
        datapool=getattr(ts, "datapool", "") or "",
    )


def expand_testplan_members(tp, project_dir: str) -> list[TestCase]:
    """把测试计划成员相对路径展开为 TestCase 列表（支持 .tc / .ts）。"""
    if not isinstance(tp, TestPlan):
        raise TypeError("expand_testplan_members 需要 TestPlan")
    root = os.path.normpath(project_dir or "")
    cases: list[TestCase] = []
    for rel in tp.members or []:
        rel = (rel or "").strip().replace("\\", "/")
        if not rel:
            continue
        path = os.path.normpath(os.path.join(root, rel)) if root else os.path.normpath(rel)
        low = path.lower()
        if low.endswith((".tc", ".tc.yaml", ".tc.yml")):
            cases.append(_load_case(path))
        elif low.endswith((".ts", ".ts.yaml", ".ts.yml")):
            cases.append(_load_suite_as_case(path))
        else:
            raise FileNotFoundError(f"测试计划成员类型不支持: {rel}")
        if not getattr(cases[-1], "source_path", ""):
            cases[-1].source_path = path
    return cases


def _merge_dataconfig_vars(project_dir: str, dataconfig: str, base: dict) -> dict:
    """把计划关联的 DataConfig.properties 合入 base_vars（不覆盖已有键）。"""
    name = (dataconfig or "").strip()
    if not name or not project_dir:
        return base
    # 相对工程根；兼容已写 config/ 前缀
    candidates = [
        os.path.join(project_dir, name),
        os.path.join(project_dir, "config", name),
        os.path.join(project_dir, "config", os.path.basename(name)),
    ]
    path = next((p for p in candidates if os.path.isfile(p)), "")
    if not path:
        return base
    # noinspection PyBroadException
    try:
        from ..model import dataconfig as dc_mod  # 延迟：仅计划关联 DataConfig 时加载
        cfg = dc_mod.load(path)
        out = dict(base)
        for k, v in cfg.as_dict().items():
            out.setdefault(str(k), str(v) if v is not None else "")
        return out
    except Exception:
        return base


def run_testplan(tp, project_dir: str,
                 fault_strategy: FaultStrategy = FaultStrategy.CONTINUE,
                 base_vars: dict | None = None,
                 maps: list[MapFile] | None = None,
                 keyword_store: KeywordStore | None = None,
                 cancel_event=None,
                 pause_event=None,
                 on_step=None,
                 on_case=None) -> SuiteResult:
    """执行测试计划：展开成员 + 按 fault_times 做用例级失败重试。"""
    if not isinstance(tp, TestPlan):
        raise TypeError("run_testplan 需要 TestPlan")
    cases = expand_testplan_members(tp, project_dir)
    vars_ = dict(base_vars or {})
    vars_.setdefault("__project_path__", project_dir)
    vars_ = _merge_dataconfig_vars(project_dir, tp.dataconfig, vars_)
    if maps is None and project_dir and os.path.isdir(project_dir):
        maps = [_load_map(p) for p in discover_maps(project_dir)]
    if keyword_store is None and project_dir and os.path.isdir(project_dir):
        keyword_store = discover_keywords(project_dir)
    name = tp.name or os.path.splitext(os.path.basename(tp.source_path or "plan"))[0] or "TestPlan"
    return run_cases(
        cases,
        name=name,
        fault_strategy=fault_strategy,
        base_vars=vars_,
        maps=maps,
        keyword_store=keyword_store,
        cancel_event=cancel_event,
        pause_event=pause_event,
        on_step=on_step,
        on_case=on_case,
        fault_times=int(tp.fault_times or 0),
    )


def run_directory(directory: str,
                  fault_strategy: FaultStrategy = FaultStrategy.CONTINUE,
                  base_vars: dict | None = None,
                  cancel_event=None,
                  pause_event=None,
                  on_step=None,
                  on_case=None) -> SuiteResult:
    cases = [_load_case(p) for p in discover_cases(directory)]
    maps = [_load_map(p) for p in discover_maps(directory)]
    store = discover_keywords(directory)   # 工程内的自定义关键字(.ks)
    return run_cases(cases, name=os.path.basename(directory.rstrip("/\\")) or "Suite",
                     fault_strategy=fault_strategy, base_vars=base_vars, maps=maps,
                     keyword_store=store, cancel_event=cancel_event,
                     pause_event=pause_event,
                     on_step=on_step, on_case=on_case)

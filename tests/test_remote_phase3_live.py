"""真机远控 live：委托 ``tests/live/remote_live_smoke.py``。

门禁：``AUTOPILOT_REMOTE_LIVE=1``；可选 ``AUTOPILOT_LIVE_ANDROID_UDID`` /
``AUTOPILOT_LIVE_IOS_UDID``。
"""

from __future__ import annotations

import os
import runpy
from pathlib import Path
from typing import Callable, cast

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("AUTOPILOT_REMOTE_LIVE", "").strip() not in {"1", "true", "yes"},
    reason="set AUTOPILOT_REMOTE_LIVE=1 with real devices to run",
)


def test_remote_live_smoke_script():
    script = Path(__file__).resolve().parents[1] / "tests" / "live" / "remote_live_smoke.py"
    assert script.is_file(), script
    # 以 __main__ 执行会 sys.exit；改用 run_path 取 main
    ns = runpy.run_path(str(script), run_name="remote_live_smoke_mod")
    main = cast(Callable[[], int], ns.get("main"))
    assert callable(main)
    code = main()
    if code != 0:
        pytest.fail(f"remote_live_smoke exited {code}")

"""类型检查闸门：默认只查 platform 业务包。

``ap/`` 与 ``runner/`` 是执行核/Agent，存在与本次 services 拆包无关的历史告警，
不纳入默认闸门。需要时加 ``--runtime`` 单独看（退出码仍报告，但不替代默认闸门）。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / "autopilot_platform" / "platform"
RUNTIME_PATHS = [
    ROOT / "autopilot_platform" / "ap",
    ROOT / "autopilot_platform" / "runner",
]


def _module_exists(name: str) -> bool:
    r = subprocess.run(
        [sys.executable, "-c", f"import {name}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return r.returncode == 0


def _pyright() -> list[str]:
    for exe_name in ("basedpyright", "pyright"):
        exe = shutil.which(exe_name)
        if exe:
            return [exe]
    for mod in ("basedpyright", "pyright"):
        if _module_exists(mod):
            return [sys.executable, "-m", mod]
    npx = shutil.which("npx")
    if npx:
        return [npx, "--no-install", "pyright"]
    sys.stderr.write(
        "未找到 pyright / basedpyright。安装其一后重试，例如：\n"
        "  pip install basedpyright\n"
        "闸门范围是 autopilot_platform/platform（见 pyproject.toml include）。\n"
    )
    raise SystemExit(2)


def _run(paths: list[Path]) -> int:
    cmd = [*_pyright(), *[str(p) for p in paths]]
    print(" ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=ROOT)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="额外检查 ap/ 与 runner/（历史债，非 platform 闸门）",
    )
    args = parser.parse_args(argv)
    code = _run([PLATFORM])
    if code != 0 or not args.runtime:
        return code
    print("platform 闸门已通过；开始 runtime 检查（ap/ runner）", flush=True)
    return _run(RUNTIME_PATHS)


if __name__ == "__main__":
    raise SystemExit(main())

"""Monkey 报告目录路径。"""

from __future__ import annotations

import os
from datetime import datetime


def allocate_report_dir(base_dir: str, *, udid: str = "") -> str:
    """分配 ``logs/ios_monkey/<timestamp>[_udid]/`` 并创建目录。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = ""
    if udid:
        suffix = f"_{udid.replace('-', '')[-6:]}"
    root = os.path.join(base_dir or ".", "logs", "ios_monkey", f"{ts}{suffix}")
    os.makedirs(root, exist_ok=True)
    return root

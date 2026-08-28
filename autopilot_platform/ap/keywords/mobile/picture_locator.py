"""Mobile ``picture::`` 图像定位：白名单关键字与匹配精度约定。

仅点击/存在校验（及「判断并点击」）运行时消费模板图；
UI 按同一白名单露出选图入口。
"""

from __future__ import annotations

import os

from ...runtime.paths import join_project, to_native, to_posix

# 运行时已实现 picture:: 分支，且应对用户透出选图/框选填入的关键字
PICTURE_LOCATOR_KEYWORDS: frozenset[str] = frozenset({
    "mobile_element_click",
    "mobile_verify_element_existed",
    "elementClick",
})

# 精确 / 模糊 → OpenCV 模板匹配阈值
_THRESHOLD_EXACT = 0.85
_THRESHOLD_FUZZY = 0.65
_THRESHOLD_DEFAULT = 0.80


def supports_picture_locator(keyword_id: str) -> bool:
    return (keyword_id or "").strip() in PICTURE_LOCATOR_KEYWORDS


def is_picture_locator(value: str) -> bool:
    return "picture::" in str(value or "")


def accuracy_to_threshold(accuracy: str | None = None) -> float:
    """元数据「精确匹配 / 模糊匹配」→ find_template 阈值。"""
    s = str(accuracy or "").strip()
    if not s:
        return _THRESHOLD_DEFAULT
    if "模糊" in s or s.lower() in ("fuzzy", "loose", "low"):
        return _THRESHOLD_FUZZY
    if "精确" in s or s.lower() in ("exact", "strict", "high"):
        return _THRESHOLD_EXACT
    # noinspection PyBroadException
    try:
        v = float(s)
        if 0.0 < v <= 1.0:
            return v
    except Exception:
        pass
    return _THRESHOLD_DEFAULT


def picture_fill_hint(keyword_id: str) -> str:
    """框选填入被拒时的提示文案。"""
    kid = (keyword_id or "").strip() or "（未知）"
    return (
        f"当前步骤「{kid}」不支持图像定位（picture::）。"
        "请改用「控件点击」「校验控件是否存在」或「判断并控件点击」后再填入。"
    )


def picture_locator_for_path(project_dir: str, abs_path: str) -> str:
    """把保存路径编成 picture:: 定位：工程内用相对路径（POSIX），否则用绝对路径。

    相对路径一律用 ``/`` 写入用例，保证 Win/Linux/macOS 工程可互换。
    """
    abs_path = to_native(abs_path)
    proj = to_native(project_dir or "")
    if proj and os.path.isdir(proj):
        # noinspection PyBroadException
        try:
            rel = os.path.relpath(abs_path, proj)
        except ValueError:
            # 不同盘符等无法做相对路径（主要见于 Windows）
            rel = abs_path
        rel_native = to_native(rel)
        # 逃出工程根、或仍是绝对路径 → 退回绝对路径编码
        if (rel_native
                and not rel_native.startswith(".." + os.sep)
                and rel_native != ".."
                and not os.path.isabs(rel_native)):
            return "picture::" + to_posix(rel_native)
    return "picture::" + to_posix(abs_path)


def resolve_picture_path(project_dir: str, locator_or_path: str) -> str:
    """解析 picture:: 或裸路径到本机绝对/相对文件系统路径。"""
    raw = str(locator_or_path or "")
    name = raw.split("picture::")[-1] if "picture::" in raw else raw
    return join_project(project_dir, name)

"""图像匹配核心（opencv 模板匹配）。Web/Mobile 图像识别关键字共用。

用 cv2.matchTemplate 做模板匹配，支持多尺度，
返回匹配中心坐标（截图像素坐标系）与置信度。截图字节由各端（selenium/appium）提供。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# noinspection PyUnresolvedReferences,PyPackageRequirements
import numpy as np
# noinspection PyUnresolvedReferences,PyPackageRequirements
import cv2


@dataclass
class MatchResult:
    cx: int          # 中心 x（截图像素坐标）
    cy: int          # 中心 y
    w: int
    h: int
    score: float


def _decode(png_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解码截图字节为图像")
    return img


def png_size(png_bytes: bytes) -> tuple[int, int]:
    """PNG 截图宽高（像素）。"""
    img = _decode(png_bytes)
    h, w = img.shape[:2]
    return w, h


def find_template(
    screenshot_png: bytes,
    template_path: str,
    threshold: float = 0.8,
    multi_scale: bool = False,
) -> Optional[MatchResult]:
    """在 screenshot 中找 template_path 模板图。命中返回 MatchResult，否则 None。

    默认按原尺寸精确匹配（截图与模板同分辨率时最稳）。
    multi_scale=True 时在 0.75~1.3 收窄区间缩放搜索，缓解 DPR/分辨率差异，
    （区间收窄是为避免过小模板在大片同色区域产生退化伪匹配）。
    """
    scene = _decode(screenshot_png)
    tmpl = cv2.imread(template_path, cv2.IMREAD_COLOR)
    if tmpl is None:
        raise FileNotFoundError(f"模板图不存在或无法读取: {template_path}")

    scales = [1.0]
    if multi_scale:
        scales = [round(s, 2) for s in np.arange(0.75, 1.31, 0.05)]

    best: Optional[MatchResult] = None
    sh, sw = scene.shape[:2]
    for s in scales:
        th, tw = int(tmpl.shape[0] * s), int(tmpl.shape[1] * s)
        if th < 8 or tw < 8 or th > sh or tw > sw:
            continue
        resized = cv2.resize(tmpl, (tw, th), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(scene, resized, cv2.TM_CCOEFF_NORMED)
        _minv, maxv, _minl, maxl = cv2.minMaxLoc(res)
        if best is None or maxv > best.score:
            best = MatchResult(cx=maxl[0] + tw // 2, cy=maxl[1] + th // 2,
                               w=tw, h=th, score=float(maxv))

    if best is not None and best.score >= threshold:
        return best
    return None

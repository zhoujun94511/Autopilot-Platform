"""报告内嵌缩略图：磁盘仍走原图路径，HTML 只嵌小图。"""

from __future__ import annotations

import base64


def thumbnail_b64(
    raw_b64: str,
    *,
    max_side: int = 480,
    jpeg_quality: int = 72,
) -> str:
    """把 PNG/JPEG base64 压成小 JPEG；失败则原样返回。"""
    data = (raw_b64 or "").strip()
    if not data:
        return ""
    if data.startswith("data:image/") and "," in data:
        data = data.split(",", 1)[1]
    try:
        raw = base64.b64decode(data, validate=False)
    except (ValueError, TypeError):
        return raw_b64
    if len(raw) < 32:
        return raw_b64
    try:
        import cv2
        import numpy as np
    except ImportError:
        return raw_b64
    try:
        arr = np.frombuffer(raw, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            return raw_b64
        h, w = image.shape[:2]
        long_side = max(w, h)
        if long_side > max_side:
            scale = max_side / float(long_side)
            image = cv2.resize(
                image,
                (max(1, int(w * scale)), max(1, int(h * scale))),
                interpolation=cv2.INTER_AREA,
            )
        quality = max(1, min(95, int(jpeg_quality)))
        ok, buf = cv2.imencode(
            ".jpg",
            image,
            [int(cv2.IMWRITE_JPEG_QUALITY), quality],
        )
        if not ok:
            return raw_b64
        return base64.b64encode(bytes(buf)).decode("ascii")
    except (OSError, ValueError, TypeError, cv2.error):
        return raw_b64

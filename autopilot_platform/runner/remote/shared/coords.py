"""显示坐标 → 设备坐标（含 object-fit: contain letterbox）。"""

from __future__ import annotations


def map_display_to_device(
    x: float,
    y: float,
    *,
    display_w: float,
    display_h: float,
    device_w: float,
    device_h: float,
    content_fit: str = "contain",
) -> tuple[int, int]:
    """将面板上的点映射到设备逻辑像素。

    ``content_fit=contain``：按等比缩放居中后剔除 letterbox（对齐 WebAppFlaskauto-iOS）。
    ``content_fit=fill``：简单线性拉伸。
    """
    if display_w <= 0 or display_h <= 0 or device_w <= 0 or device_h <= 0:
        return int(round(x)), int(round(y))

    if (content_fit or "contain").strip().lower() != "contain":
        dx = (float(x) / float(display_w)) * float(device_w)
        dy = (float(y) / float(display_h)) * float(device_h)
        return int(round(dx)), int(round(dy))

    scale = min(float(display_w) / float(device_w), float(display_h) / float(device_h))
    drawn_w = float(device_w) * scale
    drawn_h = float(device_h) * scale
    offset_x = (float(display_w) - drawn_w) / 2.0
    offset_y = (float(display_h) - drawn_h) / 2.0
    local_x = float(x) - offset_x
    local_y = float(y) - offset_y
    if local_x < 0 or local_y < 0 or local_x > drawn_w or local_y > drawn_h:
        # 点在黑边上：钳到内容区边缘，避免乱点
        local_x = min(max(local_x, 0.0), drawn_w)
        local_y = min(max(local_y, 0.0), drawn_h)
    if drawn_w <= 0 or drawn_h <= 0:
        return 0, 0
    dx = (local_x / drawn_w) * float(device_w)
    dy = (local_y / drawn_h) * float(device_h)
    return int(round(dx)), int(round(dy))

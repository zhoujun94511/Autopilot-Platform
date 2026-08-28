"""iPhone ProductType → 市场型号。

Console Runner 是独立部署包，不能 import IDE 的 ``autopilot.mobile``，因此在
Runner 包内保留同一份静态参考数据。未知新机型原样返回，避免映射滞后丢信息。
"""

from __future__ import annotations

MARKETING_NAMES: dict[str, str] = {
    # iPhone 17 series (2025) — provisional / verify on real devices
    "iPhone18,1": "iPhone 17 Pro",
    "iPhone18,2": "iPhone 17 Pro Max",
    "iPhone18,3": "iPhone 17",
    "iPhone18,4": "iPhone Air",
    "iPhone18,5": "iPhone 17e",
    # iPhone 16 series (2024)
    "iPhone17,1": "iPhone 16 Pro",
    "iPhone17,2": "iPhone 16 Pro Max",
    "iPhone17,3": "iPhone 16",
    "iPhone17,4": "iPhone 16 Plus",
    "iPhone17,5": "iPhone 16e",
    # iPhone 15 series (2023)
    "iPhone15,4": "iPhone 15",
    "iPhone15,5": "iPhone 15 Plus",
    "iPhone16,1": "iPhone 15 Pro",
    "iPhone16,2": "iPhone 15 Pro Max",
    # iPhone 14 series (2022)
    "iPhone14,7": "iPhone 14",
    "iPhone14,8": "iPhone 14 Plus",
    "iPhone15,2": "iPhone 14 Pro",
    "iPhone15,3": "iPhone 14 Pro Max",
    "iPhone14,6": "iPhone SE (3rd generation)",
    # iPhone 13 series (2021)
    "iPhone14,2": "iPhone 13 Pro",
    "iPhone14,3": "iPhone 13 Pro Max",
    "iPhone14,4": "iPhone 13 mini",
    "iPhone14,5": "iPhone 13",
    # iPhone 12 series (2020)
    "iPhone13,1": "iPhone 12 mini",
    "iPhone13,2": "iPhone 12",
    "iPhone13,3": "iPhone 12 Pro",
    "iPhone13,4": "iPhone 12 Pro Max",
    "iPhone12,8": "iPhone SE (2nd generation)",
    # iPhone 11 series (2019)
    "iPhone12,1": "iPhone 11",
    "iPhone12,3": "iPhone 11 Pro",
    "iPhone12,5": "iPhone 11 Pro Max",
    # iPhone XS / XR / X / 8
    "iPhone11,2": "iPhone XS",
    "iPhone11,4": "iPhone XS Max",
    "iPhone11,6": "iPhone XS Max",
    "iPhone11,8": "iPhone XR",
    "iPhone10,1": "iPhone 8",
    "iPhone10,2": "iPhone 8 Plus",
    "iPhone10,3": "iPhone X",
    "iPhone10,4": "iPhone 8",
    "iPhone10,5": "iPhone 8 Plus",
    "iPhone10,6": "iPhone X",
    # iPhone 7 / SE / 6s / 6
    "iPhone9,1": "iPhone 7",
    "iPhone9,2": "iPhone 7 Plus",
    "iPhone9,3": "iPhone 7",
    "iPhone9,4": "iPhone 7 Plus",
    "iPhone8,4": "iPhone SE (1st generation)",
    "iPhone8,1": "iPhone 6s",
    "iPhone8,2": "iPhone 6s Plus",
    "iPhone7,1": "iPhone 6 Plus",
    "iPhone7,2": "iPhone 6",
    # iPhone 5 / 4 / 3
    "iPhone5,1": "iPhone 5",
    "iPhone5,2": "iPhone 5",
    "iPhone5,3": "iPhone 5c",
    "iPhone5,4": "iPhone 5c",
    "iPhone6,1": "iPhone 5s",
    "iPhone6,2": "iPhone 5s",
    "iPhone3,1": "iPhone 4",
    "iPhone3,2": "iPhone 4",
    "iPhone3,3": "iPhone 4",
    "iPhone4,1": "iPhone 4S",
    "iPhone1,1": "iPhone",
    "iPhone1,2": "iPhone 3G",
    "iPhone2,1": "iPhone 3GS",
}


def marketing_name(product_type: str) -> str:
    """ProductType → 市场型号；空值仍为空，未知值原样返回。"""
    key = str(product_type or "").strip()
    if not key:
        return ""
    return MARKETING_NAMES.get(key, key)

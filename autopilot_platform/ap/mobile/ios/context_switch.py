"""iOS 原生 / WebView 上下文切换。"""

from __future__ import annotations

from typing import Any

from .runtime import is_wda_backend


def list_contexts(driver: Any, backend: str = "") -> list[str]:
    if is_wda_backend(backend, driver):
        return list(driver.contexts)
    return list(getattr(driver, "contexts", []) or [])


def switch_context(driver: Any, backend: str, target: str) -> str:
    """target: NATIVE / WEB / CHROMIUM（大小写不敏感）。"""
    want = (target or "NATIVE").strip().upper()
    contexts = list_contexts(driver, backend)
    chosen = None
    if want == "NATIVE":
        for c in contexts:
            if "NATIVE" in c.upper():
                chosen = c
                break
    else:
        for c in contexts:
            if want in c.upper():
                chosen = c
                break
        if chosen is None:
            for c in contexts:
                if "WEBVIEW" in c.upper() or "CHROMIUM" in c.upper():
                    chosen = c
                    break
    if chosen is None:
        raise ValueError(f"未找到匹配上下文 {want}，当前: {contexts}")
    if is_wda_backend(backend, driver):
        driver.set_context(chosen)
    else:
        driver.switch_to.context(chosen)
    return chosen

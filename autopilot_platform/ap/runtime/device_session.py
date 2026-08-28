"""单台设备的运行时会话绑定（注入 ExecutionContext 变量）。"""

from __future__ import annotations

from dataclasses import dataclass

from .port_allocator import PortAllocator, PortSet

DEFAULT_APPIUM_URL = "http://127.0.0.1:4723"


@dataclass(frozen=True)
class DeviceSession:
    platform: str
    udid: str
    appium_url: str = DEFAULT_APPIUM_URL
    wda_port: int = 8100
    tunnel_port: int = 28100
    mjpeg_port: int = 9100
    system_port: int = 8200
    chromedriver_port: int = 9515
    uia2_mjpeg_port: int = 7810
    wda_bundle: str = ""
    backend_mode: str = "auto"
    slot: int = 0

    @classmethod
    def from_ports(
        cls,
        platform: str,
        udid: str,
        ps: PortSet,
        *,
        wda_bundle: str = "",
        backend_mode: str = "auto",
        appium_url: str | None = None,
    ) -> DeviceSession:
        url = (appium_url or "").strip() or f"http://127.0.0.1:{ps.appium_port}"
        return cls(
            platform=platform,
            udid=udid,
            appium_url=url,
            wda_port=ps.wda_port,
            tunnel_port=ps.tunnel_port,
            mjpeg_port=ps.mjpeg_port,
            system_port=ps.system_port,
            chromedriver_port=ps.chromedriver_port,
            uia2_mjpeg_port=ps.uia2_mjpeg_port,
            wda_bundle=wda_bundle,
            backend_mode=backend_mode,
            slot=ps.slot,
        )

    @classmethod
    def from_slot(
        cls,
        platform: str,
        udid: str,
        slot: int = 0,
        *,
        wda_bundle: str = "",
        appium_url: str | None = None,
        backend_mode: str = "auto",
    ) -> DeviceSession:
        """按 slot 计算端口（不写入粘滞表）。测试/显式槽位用。"""
        ps: PortSet = PortAllocator().ports_for_slot(slot)
        return cls.from_ports(
            platform,
            udid,
            ps,
            wda_bundle=wda_bundle,
            backend_mode=backend_mode,
            appium_url=appium_url,
        )

    @classmethod
    def for_device(
        cls,
        platform: str,
        udid: str,
        *,
        wda_bundle: str = "",
        backend_mode: str = "auto",
    ) -> DeviceSession:
        """按 UDID 粘滞分配隔离端口（机房/并行真源）。"""
        from .device_runtime import acquire_device_runtime

        rt = acquire_device_runtime(udid, platform)
        return cls.from_ports(
            platform,
            udid,
            rt.ports,
            wda_bundle=wda_bundle,
            backend_mode=backend_mode,
            appium_url=rt.appium_url,
        )

    def to_ctx_vars(self) -> dict:
        """写入 ExecutionContext.variables 的键（关键字层只读 ctx）。

        每台设备独立 ``__appium_server__`` + UIA2/WDA caps，禁止多机共用 4723。
        """
        out: dict = {
            "__device_udid__": self.udid,
            "__current_platform__": self.platform,
            "__wda_local_port__": self.wda_port,
            "__tunnel_info_port__": self.tunnel_port,
            "__mjpeg_local_port__": self.mjpeg_port,
            "__appium_server__": self.appium_url,
            "__mobile_backend_mode__": self.backend_mode,
            "__worker_slot__": self.slot,
            "__uia2_system_port__": self.system_port,
            "__chromedriver_port__": self.chromedriver_port,
            "__uia2_mjpeg_port__": self.uia2_mjpeg_port,
        }
        caps: dict = {}
        android_caps = self._android_appium_caps()
        if android_caps:
            caps.update(android_caps)
        ios_caps = self._ios_appium_caps()
        if ios_caps:
            caps.update(ios_caps)
        elif self.wda_bundle and not caps:
            caps = {"wdaBundleId": self.wda_bundle}
        if caps:
            out["__appium_caps__"] = caps
        return out

    def _android_appium_caps(self) -> dict | None:
        plat = (self.platform or "").strip().lower()
        if not plat.startswith("android"):
            return None
        return {
            "appium:systemPort": int(self.system_port),
            "appium:chromedriverPort": int(self.chromedriver_port),
            "appium:mjpegServerPort": int(self.uia2_mjpeg_port),
        }

    def _ios_appium_caps(self) -> dict | None:
        """为本 slot 构造 iOS Appium caps；非 iOS / 非 Appium 路径返回 None。"""
        plat = (self.platform or "").strip().lower()
        if not plat.startswith("ios"):
            return None
        mode = (self.backend_mode or "").strip().lower()
        if mode not in ("appium", "auto"):
            return None
        import platform as _plat
        if mode == "auto" and _plat.system() != "Darwin":
            return None
        from typing import Any
        from ..mobile import ios_bootstrap as ib
        defaults: dict[Any, Any] = {
            "appium:noReset": True,
            "appium:wdaLaunchTimeout": 180000,
            "appium:wdaConnectionTimeout": 180000,
            "appium:wdaLocalPort": int(self.wda_port),
        }
        if self.wda_bundle:
            defaults["wdaBundleId"] = self.wda_bundle
        if ib.prefer_appium_managed(self.udid):
            return ib.build_ios_caps_managed(self.udid, self.wda_bundle, extra=defaults)
        return ib.build_ios_caps(self.udid, self.wda_port, extra=defaults)

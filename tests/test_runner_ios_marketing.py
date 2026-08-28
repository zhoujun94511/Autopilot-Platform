"""Console Runner 的 iOS 市场型号映射与设备上报。"""

from __future__ import annotations

import json
import subprocess

from autopilot_platform.runner import local_devices
from autopilot_platform.runner.ios_marketing import marketing_name


def test_ios_marketing_known_and_unknown_models():
    assert marketing_name("iPhone16,2") == "iPhone 15 Pro Max"
    assert marketing_name("iPhone99,9") == "iPhone99,9"
    assert marketing_name("") == ""


def test_console_runner_reports_marketing_model(monkeypatch):
    payload = json.dumps(
        [
            {
                "UniqueDeviceID": "UDID-15PM",
                "DeviceName": "iPhone",
                "ProductType": "iPhone16,2",
                "ProductVersion": "18.6.2",
            }
        ]
    )

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess([], 0, payload, "")

    monkeypatch.setattr(local_devices.subprocess, "run", fake_run)

    device = local_devices._list_ios_via_pymobiledevice3()[0]
    assert device.name == "iPhone"
    assert device.model == "iPhone 15 Pro Max"


def test_parse_goios_jsonl_device_list():
    text = (
        '{"level":"warning","msg":"go-ios agent is not running.","time":"t"}\n'
        '{"deviceList":["00008140-0010000000000001","00008130-0010000000000002"]}\n'
    )
    assert [d.udid for d in local_devices._parse_goios_list(text)] == [
        "00008140-0010000000000001",
        "00008130-0010000000000002",
    ]


def test_parse_pmd3_stdout_strips_ansi_and_log_noise():
    payload = (
        "WARN boot\n\x1b[32m"
        + json.dumps(
            [
                {
                    "UniqueDeviceID": "00008140-0010000000000001",
                    "Identifier": "00008140-0010000000000001",
                    "DeviceName": "iPhone",
                    "ProductType": "iPhone17,5",
                    "ProductVersion": "26.6",
                }
            ]
        )
        + "\x1b[0m\n"
    )
    devices = local_devices._parse_pmd3_stdout(payload)
    assert [d.udid for d in devices] == ["00008140-0010000000000001"]
    assert devices[0].model == "iPhone 16e"


def test_enrich_ios_device_maps_product_type(monkeypatch):
    local_devices.reset_ios_identity_cache()
    monkeypatch.setattr(
        local_devices,
        "_ios_identity_via_lockdown",
        lambda _udid: ("工作室机", "iPhone16,2", "18.6.2"),
    )
    monkeypatch.setattr(local_devices, "_ios_identity_via_goios", lambda _udid: None)
    raw = local_devices.LocalDevice(
        udid="00008140-0010000000000001",
        platform="ios",
        name="iPhone",
    )
    filled = local_devices.enrich_ios_device(raw)
    assert filled.model == "iPhone 15 Pro Max"
    assert filled.name == "工作室机"
    assert filled.os_version == "18.6.2"


def test_list_ios_devices_enriches_goios_fallback(monkeypatch):
    local_devices.reset_ios_identity_cache()
    monkeypatch.setattr(local_devices, "_list_ios_via_pymobiledevice3", lambda: [])
    monkeypatch.setattr(local_devices, "_list_ios_via_usbmux_inproc", lambda: [])
    monkeypatch.setattr(
        local_devices,
        "_list_ios_via_goios",
        lambda: [
            local_devices.LocalDevice(
                udid="00008140-0010000000000001", platform="ios", name="iPhone"
            ),
        ],
    )
    monkeypatch.setattr(local_devices, "_host_backends", lambda: ["ios-wda"])
    monkeypatch.setattr(
        local_devices,
        "_ios_identity_via_lockdown",
        lambda _udid: ("iPhone", "iPhone16,2", "18.6.2"),
    )
    devices = local_devices.list_ios_devices()
    assert devices[0].model == "iPhone 15 Pro Max"


def test_list_ios_devices_falls_back_to_goios(monkeypatch):
    monkeypatch.setattr(local_devices, "_list_ios_via_pymobiledevice3", lambda: [])
    monkeypatch.setattr(local_devices, "_list_ios_via_usbmux_inproc", lambda: [])
    monkeypatch.setattr(
        local_devices,
        "_list_ios_via_goios",
        lambda: [
            local_devices.LocalDevice(udid="00008140-0010000000000001", platform="ios", name="iPhone"),
            local_devices.LocalDevice(udid="00008130-0010000000000002", platform="ios", name="iPhone"),
        ],
    )
    monkeypatch.setattr(local_devices, "_host_backends", lambda: ["ios-wda"])
    devices = local_devices.list_ios_devices()
    assert [d.udid for d in devices] == [
        "00008140-0010000000000001",
        "00008130-0010000000000002",
    ]
    assert all(d.state == "ready" and "ios-wda" in d.backends for d in devices)


def test_android_friendly_name_skips_internal_codename():
    assert (
        local_devices.android_friendly_name("samsung", "SM-G9860", "", "y2qzcx")
        == "samsung SM-G9860"
    )
    assert (
        local_devices.android_friendly_name("samsung", "SM-G9860", "Galaxy S20+ 5G", "y2qzcx")
        == "Galaxy S20+ 5G"
    )
    assert local_devices.android_friendly_name("Google", "Pixel 8", "", "shiba") == "Google Pixel 8"
    assert (
        local_devices.android_friendly_name("Xiaomi", "2304FPN6DC", "Xiaomi 13", "fuxi")
        == "Xiaomi 13"
    )

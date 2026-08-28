from __future__ import annotations

from autopilot_platform.runner.remote.android import device_info as android_info
from autopilot_platform.runner.remote.android.device_info import parse_probe_output
from autopilot_platform.runner.remote.ios.device_info import parse_lockdown_info


def test_android_probe_skips_wifi_dump_and_parses_core_fields():
    assert "dumpsys wifi" not in android_info._PROBE_SCRIPT
    assert "dumpsys battery" not in android_info._PROBE_SCRIPT
    assert "/sys/class/power_supply" in android_info._PROBE_SCRIPT
    raw = """
[ro.product.manufacturer]: [Google]
[ro.product.model]: [Pixel 7]
[ro.build.version.release]: [14]
[ro.build.version.sdk]: [34]
[ro.product.cpu.abi]: [arm64-v8a]
[ro.serialno]: [serial-1]
###=====AP_INFO_BREAK=====###
  level: 87
  status: 2
  temperature: 291
###=====AP_INFO_BREAK=====###
/dev/block 120000000 37400000 80000000 32% /data
###=====AP_INFO_BREAK=====###
MemTotal:        8000000 kB
MemAvailable:    3000000 kB
###=====AP_INFO_BREAK=====###
inet 192.168.1.20/24
###=====AP_INFO_BREAK=====###
Physical size: 1080x2400
###=====AP_INFO_BREAK=====###
Physical density: 420
###=====AP_INFO_BREAK=====###
12345.67 888.0
"""
    info = parse_probe_output(raw, "serial-1")
    assert info["model"] == "Pixel 7"
    assert info["android_version"] == "14"
    assert info["sdk"] == 34
    assert info["battery_level"] == 87
    assert info["battery_status"] == "Charging"
    assert info["ip_address"] == "192.168.1.20"
    assert "wifi_ssid" not in info
    assert info["resolution_width"] == 1080
    assert info["density_dpi"] == 420
    assert info["uptime_seconds"] == 12345
    assert info["connection_type"] == "usb"


def test_android_probe_parses_sysfs_battery():
    raw = """
[ro.product.model]: [SM-G]
###=====AP_INFO_BREAK=====###
CAP:64
ST:Charging
TMP:312
###=====AP_INFO_BREAK=====###
###=====AP_INFO_BREAK=====###
###=====AP_INFO_BREAK=====###
###=====AP_INFO_BREAK=====###
###=====AP_INFO_BREAK=====###
###=====AP_INFO_BREAK=====###
1.0 0.0
"""
    info = parse_probe_output(raw, "serial-wifi:5555")
    assert info["battery_level"] == 64
    assert info["battery_status"] == "Charging"
    assert info["battery_temp_c"] == 31.2
    assert info["connection_type"] == "wifi"


def test_ios_lockdown_maps_marketing_and_identity():
    info = parse_lockdown_info(
        {
            "DeviceName": "QA iPhone",
            "ProductType": "iPhone16,2",
            "ProductVersion": "17.5",
            "BuildVersion": "21F90",
            "CPUArchitecture": "arm64e",
            "SerialNumber": "SN123",
            "UniqueDeviceID": "UDID-1",
            "ActivationState": "Activated",
        },
        "UDID-1",
    )
    assert info["marketing"] == "iPhone 15 Pro Max"
    assert info["name"] == "QA iPhone"
    assert info["ios_version"] == "17.5"
    assert info["cpu_arch"] == "arm64e"
    assert info["device_id"] == "UDID-1"

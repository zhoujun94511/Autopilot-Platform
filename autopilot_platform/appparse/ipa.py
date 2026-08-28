"""IPA 信息解析（纯 Python，零额外依赖）。

.ipa 本质是 zip：解析 `Payload/*.app/Info.plist`（应用元信息）与
`Payload/*.app/embedded.mobileprovision`（描述文件/签名信息）。

- Info.plist 二进制或 XML 格式均可——用标准库 `plistlib` 直接解析；
- mobileprovision 是 CMS(PKCS#7) 签名 blob，内嵌一段 XML plist，
  从 `<?xml … </plist>` 截出后再 `plistlib.loads`（与业界工具一致做法）；
- 文件 MD5/大小用 `hashlib`/`os.stat`。

对标 apk.py::parse_apk，供 iOS 真机装包前的预校验（bundle id / 最低系统 /
描述文件是否过期 / 目标设备是否在授权列表）与「查看安装包信息」UI。
"""

from __future__ import annotations

import hashlib
import os
import plistlib
import zipfile
from dataclasses import dataclass, field


@dataclass
class IpaInfo:
    bundle_id: str = ""                 # CFBundleIdentifier
    app_name: str = ""                  # CFBundleDisplayName / CFBundleName
    version_name: str = ""              # CFBundleShortVersionString
    version_code: str = ""              # CFBundleVersion
    minimum_os: str = ""                # MinimumOSVersion
    device_family: str = ""             # UIDeviceFamily → iPhone/iPad/通用
    url_schemes: list = field(default_factory=list)   # CFBundleURLTypes 的 URL Scheme
    permissions: list = field(default_factory=list)   # NS*UsageDescription（隐私权限用途）
    # 描述文件（embedded.mobileprovision）
    signing_type: str = ""              # 分发类型：App Store / 企业(In-House) / Ad Hoc / 开发 / 未知
    provision_name: str = ""            # Name
    app_id_name: str = ""               # AppIDName
    team_name: str = ""                 # TeamName
    team_identifier: str = ""           # Entitlements.com.apple.developer.team-identifier
    aps_environment: str = ""           # Entitlements.aps-environment（推送环境）
    uuid: str = ""                      # UUID
    expiration_date: str = ""           # ExpirationDate（ISO 文本）
    provisioned_devices: list = field(default_factory=list)  # ProvisionedDevices（UDID 列表）
    # 文件层
    file_md5: str = ""
    file_size_byte: int = 0

    @property
    def file_size_mb(self) -> float:
        return round(self.file_size_byte / (1024 * 1024), 2)

    @property
    def expires_in_days(self):
        """距描述文件过期的天数（无过期信息返回 None；已过期为负数）。"""
        if not self.expiration_date:
            return None
        from datetime import datetime
        # noinspection PyBroadException
        try:
            dt = datetime.fromisoformat(self.expiration_date.strip().replace("Z", "+00:00"))
            now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
            return (dt - now).days
        except Exception:
            return None

    @staticmethod
    def display(value, empty: str = "—") -> str:
        """友好取值：空/None → 占位符（默认「—」），列表 → 逗号拼接。"""
        if value is None or value == "" or value == []:
            return empty
        if isinstance(value, (list, tuple)):
            return "，".join(str(x) for x in value)
        return str(value)


def _first(d: dict, *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return str(v)
    return ""


def _device_family(v) -> str:
    """UIDeviceFamily（[1]=iPhone/iPod，[2]=iPad）→ 友好中文。"""
    fam = set(v) if isinstance(v, (list, tuple)) else ({v} if v else set())
    has_phone, has_pad = 1 in fam, 2 in fam
    if has_phone and has_pad:
        return "通用（iPhone/iPad）"
    if has_pad:
        return "iPad"
    if has_phone:
        return "iPhone"
    return ""


def _url_schemes(url_types) -> list:
    """CFBundleURLTypes → 扁平化的 URL Scheme 列表（去重保序）。"""
    out: list = []
    if isinstance(url_types, list):
        for t in url_types:
            for s in (t.get("CFBundleURLSchemes") or []) if isinstance(t, dict) else []:
                if s and s not in out:
                    out.append(str(s))
    return out


def _signing_type(has_provision: bool, prov: dict) -> str:
    """按描述文件推断分发类型（App Store / 企业 / Ad Hoc / 开发）。"""
    if not has_provision:
        return "App Store（无内嵌描述文件）"
    ent = prov.get("Entitlements") or {}
    if prov.get("ProvisionsAllDevices"):
        return "企业（In-House）"
    devices = prov.get("ProvisionedDevices")
    if isinstance(devices, list) and devices:
        return "开发（Development）" if ent.get("get-task-allow") else "Ad Hoc"
    return "App Store"


def _find_app_child(names: list, suffix: str) -> str:
    """在 zip 名单里找 `Payload/<x>.app/<suffix>`，返回第一个匹配的完整名（无则空）。"""
    lower = suffix.lower()
    for n in names:
        parts = n.replace("\\", "/").split("/")
        if (len(parts) == 3 and parts[0] == "Payload"
                and parts[1].lower().endswith(".app") and parts[2].lower() == lower):
            return n
    return ""


def _extract_provision_plist(raw: bytes) -> dict:
    """从 mobileprovision 的 CMS blob 里截出内嵌 XML plist 并解析；失败返回 {}。"""
    start = raw.find(b"<?xml")
    end = raw.find(b"</plist>")
    if start == -1 or end == -1:
        return {}
    segment = raw[start:end + len(b"</plist>")]
    # noinspection PyBroadException
    try:
        data = plistlib.loads(segment)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def parse_ipa(ipa_path: str) -> IpaInfo:
    """解析 .ipa，返回 IpaInfo。文件不存在/非 zip/缺 Info.plist 抛 PackageError。"""
    if not os.path.exists(ipa_path):
        from .errors import PackageError
        raise PackageError(f"IPA 文件不存在: {ipa_path}")
    if not zipfile.is_zipfile(ipa_path):
        from .errors import PackageError
        raise PackageError(f"不是有效的 .ipa（zip）文件: {ipa_path}")

    info = IpaInfo()
    with zipfile.ZipFile(ipa_path) as zf:
        names = zf.namelist()
        plist_name = _find_app_child(names, "Info.plist")
        if not plist_name:
            from .errors import PackageError
            raise PackageError(
                f"IPA 内未找到 Payload/*.app/Info.plist（可能不是 iOS 应用包）: {ipa_path}")
        # noinspection PyBroadException
        try:
            plist = plistlib.loads(zf.read(plist_name))
        except Exception as e:
            from .errors import PackageError
            raise PackageError(f"解析 Info.plist 失败: {e}")
        if isinstance(plist, dict):
            info.bundle_id = _first(plist, "CFBundleIdentifier")
            info.app_name = _first(plist, "CFBundleDisplayName", "CFBundleName")
            info.version_name = _first(plist, "CFBundleShortVersionString")
            info.version_code = _first(plist, "CFBundleVersion")
            info.minimum_os = _first(plist, "MinimumOSVersion")
            info.device_family = _device_family(plist.get("UIDeviceFamily"))
            info.url_schemes = _url_schemes(plist.get("CFBundleURLTypes"))
            info.permissions = sorted(k for k in plist if k.endswith("UsageDescription"))

        prov_name = _find_app_child(names, "embedded.mobileprovision")
        prov = _extract_provision_plist(zf.read(prov_name)) if prov_name else {}
        if prov:
            ent = prov.get("Entitlements") or {}
            info.provision_name = _first(prov, "Name")
            info.app_id_name = _first(prov, "AppIDName")
            info.team_name = _first(prov, "TeamName")
            info.team_identifier = _first(ent, "com.apple.developer.team-identifier")
            info.aps_environment = _first(ent, "aps-environment")
            info.uuid = _first(prov, "UUID")
            exp = prov.get("ExpirationDate")
            info.expiration_date = exp.isoformat() if hasattr(exp, "isoformat") else str(exp or "")
            devices = prov.get("ProvisionedDevices")
            if isinstance(devices, list):
                info.provisioned_devices = [str(d) for d in devices]
        info.signing_type = _signing_type(bool(prov_name), prov)

    st = os.stat(ipa_path)
    info.file_size_byte = st.st_size
    h = hashlib.md5()
    with open(ipa_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    info.file_md5 = h.hexdigest()
    return info


def ipa_precheck(info: IpaInfo, udid: str = "") -> list:
    """装包前预检，返回问题描述列表（空=无阻塞项）。纯函数，便于测试。

    - bundle id 缺失 → 包异常；
    - 描述文件已过期 → 装上也无法运行；
    - 指定了 udid 且描述文件带 ProvisionedDevices（开发/AdHoc 包）但不含该设备 → 装不上。
      （企业/App Store 分发包无 ProvisionedDevices，跳过此项。）
    """
    problems: list = []
    if not info.bundle_id:
        problems.append("未解析到 bundle id（CFBundleIdentifier），IPA 可能损坏或非法")
    if info.expiration_date and _is_past(info.expiration_date):
        problems.append(f"描述文件已过期（ExpirationDate={info.expiration_date}），需重新签名")
    if udid and info.provisioned_devices and udid not in info.provisioned_devices:
        problems.append(
            f"目标设备 UDID 不在描述文件授权列表中（共 {len(info.provisioned_devices)} 台），"
            "该开发/AdHoc 包装不到此设备，请把设备加入 Provisioning Profile 后重签")
    return problems


def _is_past(iso_text: str) -> bool:
    """ISO 时间文本是否早于现在（解析失败按未过期处理，不误报）。"""
    from datetime import datetime
    # noinspection PyBroadException
    try:
        s = iso_text.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        return dt < now
    except Exception:
        return False

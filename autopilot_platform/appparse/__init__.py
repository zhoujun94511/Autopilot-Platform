"""安装包解析（Platform + Runner 共用唯一入口）。"""

from .apk import ApkInfo, parse_apk
from .errors import PackageError
from .ipa import IpaInfo, ipa_precheck, parse_ipa

__all__ = [
    "ApkInfo",
    "IpaInfo",
    "PackageError",
    "ipa_precheck",
    "parse_apk",
    "parse_ipa",
]

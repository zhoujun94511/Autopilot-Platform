"""Runner 设备选择策略的本地持久化缓存。

``exclude_udids`` 由 IDE 检视/镜像写入同一状态文件。心跳响应没有这个字段，
刷新 allowlist 时必须保留，否则平台远控会把 IDE 正在占用的手机重新上报。
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _norm_udids(values) -> set[str]:
    return {str(x).strip() for x in (values or []) if str(x).strip()}


@dataclass
class DevicePolicy:
    mode: str = "all"
    selected_udids: set[str] = field(default_factory=set)
    revision: int = 0
    exclude_udids: set[str] = field(default_factory=set)

    def filter(self, devices: list):
        if self.mode != "include":
            out = list(devices)
        else:
            out = [
                d
                for d in devices
                if str(getattr(d, "udid", "") or "") in self.selected_udids
            ]
        if self.exclude_udids:
            out = [
                d
                for d in out
                if str(getattr(d, "udid", "") or "") not in self.exclude_udids
            ]
        return out


def _path(runner_id: str) -> Path:
    root = Path(
        os.environ.get("MC_RUNNER_STATE_DIR")
        or (Path.home() / ".autopilot" / "runner")
    )
    suffix = hashlib.sha256(runner_id.encode("utf-8")).hexdigest()[:16]
    return root / f"device-policy-{suffix}.json"


def load_device_policy(runner_id: str) -> DevicePolicy:
    try:
        raw = json.loads(_path(runner_id).read_text(encoding="utf-8"))
        return DevicePolicy(
            mode=str(raw.get("mode") or "all"),
            selected_udids=_norm_udids(raw.get("selected_udids", [])),
            revision=int(raw.get("revision") or 0),
            exclude_udids=_norm_udids(raw.get("exclude_udids", [])),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return DevicePolicy()


def save_device_policy(runner_id: str, policy: DevicePolicy) -> None:
    path = _path(runner_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(
            {
                "mode": policy.mode,
                "selected_udids": sorted(policy.selected_udids),
                "revision": policy.revision,
                "exclude_udids": sorted(policy.exclude_udids),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def sync_exclude_udids(runner_id: str, current: DevicePolicy) -> DevicePolicy:
    """心跳前从磁盘合并 exclude，IDE 改文件后下一拍即可摘除。"""
    current.exclude_udids = set(load_device_policy(runner_id).exclude_udids)
    return current


def update_device_policy(
    runner_id: str, current: DevicePolicy, response: dict
) -> DevicePolicy:
    revision = int(response.get("device_policy_revision") or 0)
    disk_exclude = set(load_device_policy(runner_id).exclude_udids)
    exclude = disk_exclude | set(current.exclude_udids)
    if revision < current.revision:
        current.exclude_udids = exclude
        return current
    policy = DevicePolicy(
        mode=str(response.get("device_selection_mode") or "all"),
        selected_udids=_norm_udids(response.get("selected_device_udids", [])),
        revision=revision,
        exclude_udids=exclude,
    )
    save_device_policy(runner_id, policy)
    return policy

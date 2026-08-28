"""Runner 设备选择策略的本地持久化缓存。"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DevicePolicy:
    mode: str = "all"
    selected_udids: set[str] = field(default_factory=set)
    revision: int = 0

    def filter(self, devices: list):
        if self.mode != "include":
            return list(devices)
        return [d for d in devices if str(getattr(d, "udid", "") or "") in self.selected_udids]


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
            selected_udids={
                str(x).strip() for x in raw.get("selected_udids", []) if str(x).strip()
            },
            revision=int(raw.get("revision") or 0),
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
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def update_device_policy(
    runner_id: str, current: DevicePolicy, response: dict
) -> DevicePolicy:
    revision = int(response.get("device_policy_revision") or 0)
    if revision < current.revision:
        return current
    policy = DevicePolicy(
        mode=str(response.get("device_selection_mode") or "all"),
        selected_udids={
            str(x).strip()
            for x in response.get("selected_device_udids", [])
            if str(x).strip()
        },
        revision=revision,
    )
    save_device_policy(runner_id, policy)
    return policy

#!/usr/bin/env python3
"""本机 Managed Runner + 远控联调冒烟（配合 start_dev.py）。

用法（Platform 已起在 :8000）::
    python scripts/live_managed_remote_smoke.py
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

BASE = "http://127.0.0.1:8000"
CLIENT = "http://127.0.0.1:5173"
USER = "admin"
PASS = "admin"


def _req(
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any]:
    url = f"{BASE}{path}"
    data = None
    hdrs = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {"detail": exc.reason}
        except json.JSONDecodeError:
            parsed = {"detail": raw or str(exc)}
        return exc.code, parsed


def _step(name: str) -> None:
    print(f"\n==> {name}", flush=True)


def main() -> int:
    _step("health / platform_boot_id")
    st, h = _req("GET", "/health")
    if st != 200:
        print(f"FAIL health {st}: {h}")
        return 1
    print(f"OK boot_id={h.get('platform_boot_id', '?')[:12]}…")

    _step("login")
    st, tok = _req("POST", "/api/v1/auth/login", body={"username": USER, "password": PASS})
    if st != 200:
        print(f"FAIL login {st}: {tok}")
        return 1
    auth = {"Authorization": f"Bearer {tok['access_token']}"}
    print("OK admin")

    _step("managed runner status")
    st, mg = _req("GET", "/api/v1/runners/managed?log_lines=20", headers=auth)
    if st != 200:
        print(f"FAIL managed status {st}: {mg}")
        return 1
    print(f"enabled={mg.get('enabled')} running={mg.get('running')} pid={mg.get('pid')}")

    if not mg.get("running"):
        _step("start managed runner")
        st, started = _req("POST", "/api/v1/runners/managed/start", headers=auth, body={})
        if st not in (200, 201):
            print(f"FAIL managed start {st}: {started}")
            return 1
        print(f"OK pid={started.get('pid')}")
        for _ in range(30):
            time.sleep(1)
            st, mg = _req("GET", "/api/v1/runners/managed", headers=auth)
            if st == 200 and mg.get("running"):
                break
        else:
            print("FAIL managed runner did not become running in 30s")
            return 1

    _step("device probe (inventory only)")
    st, probe = _req("POST", "/api/v1/runners/managed/device-probe", headers=auth)
    if st != 200:
        print(f"FAIL probe {st}: {probe}")
        return 1
    runner_id = str(probe.get("runner_id") or "managed-local")
    devices = probe.get("devices") or []
    udids = [str(d.get("udid")) for d in devices if d.get("udid")]
    print(f"OK runner_id={runner_id} discovered={len(udids)}")
    if not udids:
        print("WARN 未发现 USB 设备；后续占用/远控跳过。请连接 Android 真机后重试。")
        return 0

    android_udids = [
        str(d.get("udid"))
        for d in devices
        if str(d.get("platform") or "").lower() == "android" and d.get("udid")
    ]
    if not android_udids:
        print("WARN 无 Android 设备，跳过远控。iOS 远控需 MJPEG 路径。")
        return 0

    _step("register devices into allowlist")
    st, reg = _req(
        "PATCH",
        f"/api/v1/runners/{runner_id}/device-selection",
        headers=auth,
        body={"action": "register", "udids": android_udids[:3]},
    )
    if st != 200:
        print(f"FAIL register {st}: {reg}")
        return 1
    print(f"OK registered={reg.get('registered')}")

    _step("wait runner heartbeat → device pool")
    device_id = ""
    for i in range(45):
        time.sleep(1)
        st, listed = _req("GET", "/api/v1/devices?page=1&page_size=50", headers=auth)
        if st != 200:
            continue
        items = listed.get("items") or []
        for it in items:
            if str(it.get("udid")) in android_udids and str(it.get("platform")).lower() == "android":
                device_id = str(it.get("id") or "")
                label = it.get("name") or it.get("model") or it.get("udid")
                print(f"  pool hit: {label} id={device_id[:8]}…")
                break
        if device_id:
            break
        if i % 5 == 4:
            print(f"  waiting… ({i + 1}s)")
    if not device_id:
        print("FAIL 设备未入池（Runner 心跳/注册名单）")
        return 1

    _step("list runners (online check)")
    st, runners = _req("GET", "/api/v1/runners?page=1&page_size=20", headers=auth)
    if st == 200:
        for r in (runners.get("items") or []):
            if r.get("runner_id") == runner_id:
                print(f"OK online={r.get('online')} last_seen={r.get('last_seen')}")
                break

    _step("reserve device (release stale reservation if any)")
    st, listed = _req("GET", "/api/v1/devices?page=1&page_size=50", headers=auth)
    dev = next(
        (x for x in (listed.get("items") or []) if str(x.get("id")) == device_id),
        None,
    )
    old_res = str((dev or {}).get("reservation_id") or "")
    if old_res:
        st, _rel = _req("DELETE", f"/api/v1/device-reservations/{old_res}", headers=auth)
        print(f"released stale reservation {old_res[:8]}… status={st}")
    st, res = _req(
        "POST",
        f"/api/v1/devices/{device_id}/reservations",
        headers=auth,
        body={"duration_minutes": 30, "reason": "[联调冒烟]"},
    )
    if st not in (200, 201):
        print(f"FAIL reserve {st}: {res}")
        return 1
    print(f"OK reservation={str(res.get('id', ''))[:8]}…")

    _step("open remote session")
    st, session = _req(
        "POST",
        f"/api/v1/devices/{device_id}/remote-sessions",
        headers=auth,
        body={"duration_minutes": 30},
    )
    if st not in (200, 201):
        print(f"FAIL remote session {st}: {session}")
        return 1
    sid = str(session.get("id") or "")
    print(f"OK session={sid[:12]}… status={session.get('status')}")

    _step("poll session until ready/connected/failed")
    final = "pending"
    for i in range(90):
        time.sleep(1)
        st, info = _req("GET", f"/api/v1/device-remote-sessions/{sid}", headers=auth)
        if st != 200:
            continue
        final = str(info.get("status") or "unknown")
        err = str(info.get("error_message") or "")
        if final in ("ready", "connected"):
            print(f"OK session-status={final} (+{i + 1}s)")
            break
        if final in ("failed", "closed"):
            print(f"FAIL session-status={final} err={err}")
            return 1
        if i % 10 == 9:
            print(f"  … {final} (+{i + 1}s)")
    else:
        print(f"FAIL timeout last={final}")
        return 1

    _step("managed runner log tail")
    st, mg2 = _req("GET", "/api/v1/runners/managed?log_lines=12", headers=auth)
    if st == 200:
        for line in (mg2.get("log_tail") or [])[-5:]:
            print(f"  | {line[:100]}")

    print("\n" + "=" * 60)
    print("联调冒烟通过。请在浏览器打开:")
    print(f"  {CLIENT}")
    print("路径: 设备 → 占用设备 → 远程调试")
    print(f"或直接验证 session {sid[:12]}…")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Exercise the deployed frontend's device page using browser-only mock data."""

from __future__ import annotations

import base64
import json
import struct
import time
import zlib
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from frontend_perf_probe import ORG, PROJECT, ROOT, USER, fixture, serve

OUTPUT = ROOT / "logs/frontend-remote-ui-mock"
ANDROID = {
    "id": "pixel", "udid": "mock-pixel", "runner_id": "mock-node",
    "platform": "android", "model": "Pixel 8", "online": True,
    "busy": True, "busy_kind": "reservation", "reservation_user_id": USER["id"],
    "reservation_username": USER["username"],
}
IOS = {
    **ANDROID, "id": "iphone", "udid": "mock-iphone", "platform": "ios", "model": "iPhone 15",
    "reservation_user_id": "mock-owner", "reservation_username": "设备占用人",
    "can_manage": True, "remote_session_active": True,
}


def test_frame(width: int, height: int) -> dict:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    shades = [(24, 50, 82), (35, 76, 110), (43, 98, 120)]
    pixels = b"".join(b"\x00" + bytes(shades[min(y * 3 // height, 2)]) * width for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")
    return {"type": "frame", "mime": "image/png", "width": width, "height": height,
            "data_b64": base64.b64encode(png).decode("ascii")}


def run(base: str) -> dict:
    claims = base64.urlsafe_b64encode(
        json.dumps({"exp": int(time.time()) + 3600, "typ": "access"}).encode()
    ).decode().rstrip("=")
    token = f"mock.{claims}.mock"
    data = fixture(token, 1)
    data["/api/v1/devices"] = {"items": [ANDROID, IOS], "total": 2, "page": 1, "page_size": 50}
    data["/api/v1/devices/board"] = {
        "devices": [ANDROID, IOS], "summary": {"online": 2, "busy": 2, "free": 0,
                                             "by_platform": {}, "by_runner": {}},
    }
    state = {"media": False, "failed": False, "expired": False, "frame": test_frame(320, 680)}
    requests = []
    inputs = []
    unexpected_origins = []
    errors = []
    sessions = {
        name: {"id": name, "device_id": device["id"], "runner_id": device["runner_id"],
               "platform": device["platform"], "status": "ready", "capabilities": ["mjpeg"],
               "participant_role": name, "participant_id": f"mock-{name}"}
        for name, device in (("controller", ANDROID), ("viewer", IOS))
    }
    remote_prefix = "/api/v1/device-remote-sessions"

    def handle(route):
        url = urlsplit(route.request.url)
        method = route.request.method
        path = url.path
        if url.netloc != urlsplit(base).netloc:
            unexpected_origins.append(url.netloc)
            route.abort()
            return
        if path == "/api/v1/devices/pixel/remote-sessions":
            requests.append((method, path))
            if state["failed"]:
                route.fulfill(status=503, json={"detail": "模拟连接失败"})
            else:
                route.fulfill(status=201, json=sessions["controller"])
        elif path == "/api/v1/devices/iphone/remote-sessions/join":
            requests.append((method, path))
            route.fulfill(json=sessions["viewer"])
        elif path.startswith(f"{remote_prefix}/"):
            name, _, endpoint = path[len(remote_prefix) + 1:].partition("/")
            if method != "GET":
                requests.append((method, path))
            if method == "DELETE":
                route.fulfill(status=204)
            elif endpoint == "media-poll":
                route.fulfill(json={"session_status": "ready", "messages": [state["frame"]] if state["media"] else []})
            elif endpoint == "signaling-poll":
                route.fulfill(json={"session_status": "ready", "messages": []})
            elif endpoint == "media" and method == "POST":
                if route.request.post_data_json["type"] == "input":
                    inputs.append((name, route.request.post_data_json["payload"]))
                route.fulfill(json={})
            elif not endpoint and method == "GET":
                if state["expired"]:
                    route.fulfill(status=401, json={"detail": "模拟会话失效"})
                else:
                    route.fulfill(json=sessions[name])
            else:
                route.fulfill(json={})
        elif path == "/api/v1/auth/refresh" and state["expired"]:
            route.fulfill(status=401, json={"detail": "模拟刷新令牌失效"})
        elif path.startswith("/api/") or path == "/health":
            route.fulfill(json=data.get(path, {"items": [], "total": 0, "page": 1, "page_size": 50}))
        elif path == "/infra/devices" and route.request.is_navigation_request():
            route.fulfill(path=ROOT / "autopilot_platform/frontend/dist/index.html", content_type="text/html")
        else:
            route.continue_()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        try:
            context = browser.new_context(
                viewport={"width": 1440, "height": 900}, locale="zh-CN",
                reduced_motion="reduce", service_workers="block",
            )
            context.route("**/*", handle)
            context.add_init_script(
                "Object.entries(" + json.dumps({
                    "mc_jwt": token, "mc_session": "1", "mc_user": json.dumps(USER), "mc_filter_org_id": ORG["id"],
                    "mc_filter_project_id": PROJECT["id"], "autopilot-mc-theme": "light",
                }) + ").forEach(([key, value]) => localStorage.setItem(key, value));"
            )
            page = context.new_page()
            page.set_default_timeout(7000)
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(base + "/infra/devices")
            expect(page.get_by_role("heading", name="设备", exact=True)).to_be_visible()
            page.get_by_role("button", name="卡片", exact=True).click()
            expect(page.locator(".device-card").filter(has_text="Pixel 8")).to_be_visible()
            page.get_by_role("button", name="列表", exact=True).click()
            controller = page.get_by_role("row").filter(has_text="Pixel 8").get_by_role("button", name="远程调试")
            viewer = page.get_by_role("row").filter(has_text="iPhone 15").get_by_role("button", name="旁观")
            expect(viewer).to_be_visible()
            page.screenshot(path=OUTPUT / "devices-light.png")

            controller.click()
            dialog = page.get_by_role("dialog")
            expect(dialog).to_be_visible()
            expect(dialog.get_by_role("status")).to_contain_text("首帧")
            expect(dialog.get_by_role("button", name="Home", exact=True)).to_be_disabled()
            page.screenshot(path=OUTPUT / "remote-connecting.png")
            state["media"] = True
            expect(dialog.get_by_role("status")).to_have_text("已连接 · MJPEG")
            canvas = dialog.locator("canvas.remote-video")
            expect(canvas).to_have_js_property("width", 320)
            expect(canvas).to_have_js_property("height", 680)
            def is_release(request):
                return (request.method == "POST" and request.url.endswith("/controller/media")
                        and request.post_data_json.get("payload", {}).get("action") == 1)

            with page.expect_response(lambda response: is_release(response.request)):
                canvas.click()
            more = dialog.get_by_role("button", name="更多", exact=True)
            more.click()
            drawer = dialog.locator("#remote-tools")
            expect(drawer).to_be_visible()
            expect(more).to_have_attribute("aria-expanded", "true")
            expect(drawer.get_by_role("button", name="流质量")).to_be_visible()
            drawer.get_by_role("button", name="流质量").click()
            expect(drawer.get_by_role("button", name="流质量")).to_have_attribute("aria-pressed", "true")
            with page.expect_response(lambda response: is_release(response.request)):
                canvas.click()
            assert drawer.bounding_box()["x"] >= canvas.bounding_box()["x"] + canvas.bounding_box()["width"]
            page.screenshot(path=OUTPUT / "remote-controller-light.png")
            drawer.get_by_role("button", name="关闭侧栏").click()
            expect(more).to_be_focused()
            state["frame"] = test_frame(680, 320)
            expect(canvas).to_have_js_property("width", 680)
            expect(canvas).to_have_js_property("height", 320)
            with page.expect_response(lambda response: is_release(response.request)):
                canvas.click()
            down_events = [payload for _, payload in inputs
                           if payload.get("t") == "touch" and payload.get("action") == 0]
            assert len(down_events) == 3, inputs
            for payload in down_events[:2]:
                assert abs(payload["x"] - 160) <= 2 and abs(payload["y"] - 340) <= 2, payload
            rotated = down_events[-1]
            assert abs(rotated["x"] - 340) <= 2 and abs(rotated["y"] - 160) <= 2, rotated
            bounds = canvas.bounding_box()
            y = bounds["y"] + bounds["height"] / 2
            x0 = bounds["x"] + bounds["width"] * 0.35
            x1 = bounds["x"] + bounds["width"] * 0.65
            with page.expect_response(lambda response: is_release(response.request)):
                page.mouse.move(x0, y)
                page.mouse.down()
                page.mouse.move(x1, y, steps=5)
                page.mouse.up()
            drag = [payload for _, payload in inputs if payload.get("t") == "touch"][-3:]
            assert any(item["action"] == 2 for item in drag), drag
            assert drag[-1]["action"] == 1 and abs(drag[-1]["x"] - 442) <= 2, drag
            page.keyboard.press("Escape")
            expect(dialog).to_be_hidden()
            expect(controller).to_be_focused()

            page.locator(".theme-toggle").click()
            expect(page.locator("html")).to_have_attribute("data-theme", "dark")
            viewer.click()
            expect(dialog.get_by_text("旁观模式 · 只读")).to_be_visible()
            expect(dialog.get_by_role("button", name="Home", exact=True)).to_be_disabled()
            expect(dialog.get_by_role("status")).to_have_text("已连接 · MJPEG")
            viewer_inputs = len(inputs)
            dialog.locator("canvas.remote-video").click()
            dialog.get_by_role("button", name="更多", exact=True).click()
            expect(drawer).to_be_visible()
            page.screenshot(path=OUTPUT / "remote-viewer-dark.png")
            page.set_viewport_size({"width": 390, "height": 844})
            assert dialog.evaluate("(el) => el.scrollWidth <= el.clientWidth + 1")
            assert page.evaluate("document.documentElement.scrollWidth === document.documentElement.clientWidth")
            expect(drawer.get_by_role("button", name="流质量")).to_be_in_viewport(ratio=1)
            page.screenshot(path=OUTPUT / "remote-viewer-narrow.png")
            drawer.get_by_role("button", name="关闭侧栏").click()
            expect(dialog.get_by_role("button", name="更多", exact=True)).to_be_focused()
            page.keyboard.press("Escape")
            expect(dialog).to_be_hidden()
            assert len(inputs) == viewer_inputs, inputs

            page.set_viewport_size({"width": 1440, "height": 900})
            state["failed"] = True
            controller.click()
            expect(dialog.get_by_role("alert")).to_contain_text("模拟连接失败")
            expect(dialog.get_by_text("画面暂不可用")).to_be_visible()
            page.screenshot(path=OUTPUT / "remote-error.png")
            page.keyboard.press("Escape")
            expect(dialog).to_be_hidden()
            assert ("DELETE", f"{remote_prefix}/controller") in requests, requests
            assert ("DELETE", f"{remote_prefix}/viewer/participants/mock-viewer") in requests, requests
            assert ("DELETE", f"{remote_prefix}/viewer") not in requests, requests

            state["failed"] = False
            controller.click()
            expect(dialog.get_by_role("status")).to_have_text("已连接 · MJPEG")
            with page.expect_response(lambda response: response.request.method == "DELETE"
                                      and response.url.endswith(f"{remote_prefix}/controller")):
                state["expired"] = True
                expect(dialog).to_be_hidden()
            expect(page.get_by_role("button", name="登录", exact=True)).to_be_visible()

            assert not errors and not unexpected_origins, (errors, unexpected_origins)
            return {"device_views": ["list", "cards"], "themes": ["light", "dark"],
                    "viewports": [[1440, 900], [390, 844]], "remote_states": ["connecting", "controller",
                    "readonly viewer", "failure"], "touch_centers": [[160, 340], [340, 160]], "drag_mapped": True,
                    "exit_verified": ["controller close", "viewer leave", "focus restored",
                                      "active remote removed on browser session expiry"],
                    "page_errors": errors, "external_http_requests": unexpected_origins}
        finally:
            browser.close()


if __name__ == "__main__":
    OUTPUT.mkdir(parents=True, exist_ok=True)
    dist = ROOT / "autopilot_platform/frontend/dist"
    if not (dist / "index.html").is_file():
        raise SystemExit("Build autopilot_platform/frontend before running this check.")
    with serve(dist, {}, 0) as base:
        result = run(base)
    report = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    (OUTPUT / "result.json").write_text(report, encoding="utf-8")
    print(report)

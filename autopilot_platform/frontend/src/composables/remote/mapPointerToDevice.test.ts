import { describe, expect, it } from "vitest";
import { letterboxRect, mapPointerToDevice } from "./mapPointerToDevice";

describe("mapPointerToDevice", () => {
  it("点在画面中心时落到设备中心，侧栏把画面右移也不变", () => {
    const device = { w: 1080, h: 1920 };
    for (const left of [240, 64]) {
      const box = { left, top: 80, width: 400, height: 800 };
      const surface = letterboxRect(box, device.w, device.h);
      const hit = mapPointerToDevice(
        surface.left + surface.width / 2,
        surface.top + surface.height / 2,
        surface,
        device.w,
        device.h,
      );
      expect(hit).toEqual({ x: 540, y: 960 });
    }
  });

  it("点在上下黑边上会被夹到画面边缘", () => {
    const box = { left: 240, top: 80, width: 400, height: 800 };
    const surface = letterboxRect(box, 1080, 1920);
    expect(surface.top).toBeGreaterThan(box.top);
    const hit = mapPointerToDevice(surface.left + 10, box.top + 1, surface, 1080, 1920);
    expect(hit?.y).toBe(0);
    expect(hit?.x).toBeGreaterThan(0);
  });

  it("旋转后仍按新的宽高比对准画面中心", () => {
    const box = { left: 240, top: 80, width: 400, height: 800 };
    const surface = letterboxRect(box, 1920, 1080);
    const hit = mapPointerToDevice(
      surface.left + surface.width / 2,
      surface.top + surface.height / 2,
      surface,
      1920,
      1080,
    );
    expect(hit).toEqual({ x: 960, y: 540 });
    expect(surface.height).toBeLessThan(box.height);
  });
});

import { describe, expect, it } from "vitest";
import { activationLabel, batteryStatusLabel, formatUptime } from "./useRemoteDeviceInfo";

describe("remote device info labels", () => {
  it("formats uptime in chinese units", () => {
    expect(formatUptime(90)).toBe("1 分钟");
    expect(formatUptime(3661)).toBe("1 小时 1 分钟");
    expect(formatUptime(90000)).toBe("1 天 1 小时");
  });

  it("maps battery and activation states", () => {
    expect(batteryStatusLabel("Charging")).toBe("充电中");
    expect(activationLabel("Activated")).toBe("已激活");
  });
});

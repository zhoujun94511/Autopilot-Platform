import { describe, expect, it } from "vitest";
import {
  deviceCardSummary,
  deviceNickname,
  deviceOsLabel,
  displayName,
  occupyLabel,
  remainingLabel,
  reservationExtraNote,
  runnerDetailHeartbeatLabel,
  runnerHeartbeatHint,
  runnerOnlineBadgeLabel,
} from "./deviceDisplay";

describe("device card labels", () => {
  it("does not stitch Android SKU with an internal codename", () => {
    expect(displayName({ name: "y2qzcx", model: "SM-G9860" })).toBe("SM-G9860");
    expect(displayName({ name: "samsung SM-G9860", model: "SM-G9860" })).toBe("samsung SM-G9860");
    expect(displayName({ name: "Galaxy S20+ 5G", model: "SM-G9860" })).toBe("Galaxy S20+ 5G");
  });

  it("prefers iOS marketing model over generic DeviceName", () => {
    expect(displayName({ name: "iPhone", model: "iPhone 15 Pro Max" })).toBe("iPhone 15 Pro Max");
    expect(deviceNickname({ name: "工作室机", model: "iPhone 15 Pro Max" })).toBe("工作室机");
    expect(deviceNickname({ name: "iPhone", model: "iPhone 15 Pro Max" })).toBe("");
  });

  it("prefixes OS with the platform", () => {
    expect(deviceOsLabel({ platform: "android", os_version: "13" })).toBe("Android 13");
    expect(deviceOsLabel({ platform: "ios", os_version: "18.6.2" })).toBe("iOS 18.6.2");
    expect(deviceOsLabel({ platform: "ios", os_version: "iOS 18.6.2" })).toBe("iOS 18.6.2");
    expect(
      deviceCardSummary({
        udid: "x",
        platform: "android",
        name: "y2qzcx",
        model: "SM-G9860",
        runner_id: "managed-local",
        os_version: "13",
        registration_source: "managed",
      }),
    ).toBe("Android 13 · 平台托管");
  });
});

describe("occupied card labels", () => {
  it("drops trailing zero minutes", () => {
    expect(remainingLabel(3600)).toBe("1小时");
    expect(remainingLabel(3660)).toBe("1小时1分");
    expect(remainingLabel(120)).toBe("2分钟");
    expect(remainingLabel(30)).toBe("不足 1 分钟");
  });

  it("hides reservation reason that is only the purpose tag", () => {
    expect(
      reservationExtraNote({
        udid: "x",
        platform: "android",
        name: "n",
        model: "m",
        runner_id: "r",
        reservation_purpose: "手工调试",
        reservation_reason: "[手工调试]",
      }),
    ).toBe("");
    expect(
      reservationExtraNote({
        udid: "x",
        platform: "ios",
        name: "n",
        model: "m",
        runner_id: "r",
        reservation_purpose: "远控预留",
        reservation_reason: "[远控预留]联调机房",
      }),
    ).toBe("联调机房");
  });

  it("adds remaining time to the table occupy summary", () => {
    expect(
      occupyLabel({
        udid: "x",
        platform: "android",
        name: "n",
        model: "m",
        runner_id: "r",
        busy: true,
        busy_kind: "reservation",
        occupy_summary: "人工预占 · admin · 手工调试",
        reservation_remaining_seconds: 3600,
      }),
    ).toBe("人工预占 · admin · 手工调试 · 剩余 1小时");
  });
});

describe("runner presence labels", () => {
  it("managed-local not running shows 未运行 instead of offline+never reported", () => {
    const row = {
      online: false,
      last_heartbeat_at: null,
      registration_source: "managed",
      has_token: true,
    };
    const ctx = { isManagedRow: true, managedRunning: false };
    expect(runnerOnlineBadgeLabel(row, ctx)).toBe("未运行");
    expect(runnerHeartbeatHint(row, ctx)).toContain("Platform 同机托管");
  });

  it("provisioned remote runner without heartbeat shows 待连接", () => {
    const row = {
      online: false,
      last_heartbeat_at: null,
      registration_source: "platform",
      has_token: true,
    };
    expect(runnerOnlineBadgeLabel(row)).toBe("待连接");
    expect(runnerHeartbeatHint(row)).toContain("已登记");
  });

  it("stale heartbeat shows relative last seen", () => {
    const past = new Date(Date.now() - 2 * 3600 * 1000).toISOString();
    const row = {
      online: false,
      last_heartbeat_at: past,
      registration_source: "platform",
      has_token: true,
    };
    expect(runnerOnlineBadgeLabel(row)).toBe("离线");
    expect(runnerHeartbeatHint(row)).toMatch(/末次心跳/);
    expect(runnerDetailHeartbeatLabel(row)).not.toBe("-");
  });
});

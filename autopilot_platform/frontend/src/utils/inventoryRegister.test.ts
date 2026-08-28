import { describe, expect, it } from "vitest";
import {
  filterInventoryByStatus,
  isInventoryDeviceRegistered,
  partitionCheckedUdids,
} from "./inventoryRegister";

const android = { udid: "abcd1234", registered: false };
const ios15 = { udid: "00008130-0010000000000002", registered: false };
const ios16 = { udid: "00008140-0010000000000001", registered: true };

const includeInventory = {
  selection_mode: "include" as const,
  selected_udids: [android.udid, ios15.udid],
  devices: [android, ios15, ios16],
};

describe("isInventoryDeviceRegistered", () => {
  it("include 模式以 allowlist 为准，忽略滞后的 registered 布尔", () => {
    expect(isInventoryDeviceRegistered(includeInventory, android)).toBe(true);
    expect(isInventoryDeviceRegistered(includeInventory, ios15)).toBe(true);
    expect(isInventoryDeviceRegistered(includeInventory, ios16)).toBe(false);
  });

  it("all 模式仍看设备自身 registered", () => {
    const allInventory = { selection_mode: "all", selected_udids: [], devices: [android, ios16] };
    expect(isInventoryDeviceRegistered(allInventory, android)).toBe(false);
    expect(isInventoryDeviceRegistered(allInventory, ios16)).toBe(true);
  });
});

describe("partitionCheckedUdids", () => {
  it("提交注册只拆出未在名单里的 UDID", () => {
    const { pending, registered } = partitionCheckedUdids(includeInventory, [
      android.udid,
      ios15.udid,
      ios16.udid,
    ]);
    expect(pending).toEqual([ios16.udid]);
    expect(registered).toEqual([android.udid, ios15.udid]);
  });
});

describe("filterInventoryByStatus", () => {
  it("待注册列表不展示已在名单中的设备", () => {
    const pending = filterInventoryByStatus(
      includeInventory.devices,
      includeInventory,
      "pending",
    );
    expect(pending.map((d) => d.udid)).toEqual([ios16.udid]);
    const registered = filterInventoryByStatus(
      includeInventory.devices,
      includeInventory,
      "registered",
    );
    expect(registered.map((d) => d.udid)).toEqual([android.udid, ios15.udid]);
  });
});

/** 管理测试设备弹层：注册状态以 allowlist 为准，避免库存布尔滞后导致重复提交。 */

export type InventoryStatusFilter = "pending" | "registered" | "all";

export type InventoryRegisterDevice = {
  udid: string;
  registered?: boolean;
};

export type InventoryRegisterContext = {
  selection_mode?: string;
  selected_udids?: string[];
  devices?: InventoryRegisterDevice[];
};

export function isInventoryDeviceRegistered(
  inventory: InventoryRegisterContext | null | undefined,
  device: InventoryRegisterDevice,
): boolean {
  const mode = (inventory?.selection_mode || "all").trim();
  if (mode === "include") {
    return (inventory?.selected_udids || []).includes(device.udid);
  }
  return Boolean(device.registered);
}

export function partitionCheckedUdids(
  inventory: InventoryRegisterContext | null | undefined,
  checked: string[],
): { pending: string[]; registered: string[] } {
  const byUdid = new Map((inventory?.devices || []).map((d) => [d.udid, d]));
  const pending: string[] = [];
  const registered: string[] = [];
  for (const udid of checked) {
    const device = byUdid.get(udid);
    if (!device) continue;
    if (isInventoryDeviceRegistered(inventory, device)) registered.push(udid);
    else pending.push(udid);
  }
  return { pending, registered };
}

export function filterInventoryByStatus<T extends InventoryRegisterDevice>(
  devices: T[],
  inventory: InventoryRegisterContext | null | undefined,
  status: InventoryStatusFilter,
): T[] {
  if (status === "all") return devices;
  const wantRegistered = status === "registered";
  return devices.filter(
    (device) => isInventoryDeviceRegistered(inventory, device) === wantRegistered,
  );
}

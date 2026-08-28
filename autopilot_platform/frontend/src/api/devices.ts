/** TR 设备池 API（面板分页 vs 下拉/选机全量）。 */

import { api, type Device } from "../api";
import {
  DEFAULT_PAGE_SIZE,
  normalizePagedResult,
  type PagedResult,
} from "../utils/pagination";

export type DeviceBoardSummary = {
  online: number;
  busy: number;
  free: number;
  by_platform: Record<string, { total: number; busy: number; free: number }>;
  by_runner: Record<string, { total: number; busy: number; free: number }>;
};

export type DeviceBoard = {
  summary: DeviceBoardSummary;
  devices: Device[];
};

export type DeviceListFilters = {
  page?: number;
  pageSize?: number;
  q?: string;
  platform?: string;
  busy?: "" | "free" | "busy";
  summary_only?: boolean;
};

const PAGE_SIZE = DEFAULT_PAGE_SIZE;
const MAX_PAGES = 20;

function deviceQuery(projectId?: string, opts?: DeviceListFilters): string {
  const q = new URLSearchParams();
  if (projectId?.trim()) q.set("project_id", projectId.trim());
  if (opts?.page != null) q.set("page", String(opts.page));
  if (opts?.pageSize != null) q.set("page_size", String(opts.pageSize));
  if (opts?.q?.trim()) q.set("q", opts.q.trim());
  if (opts?.platform?.trim()) q.set("platform", opts.platform.trim());
  if (opts?.busy) q.set("busy", opts.busy);
  if (opts?.summary_only) q.set("summary_only", "true");
  const qs = q.toString();
  return qs ? `?${qs}` : "";
}

export async function listDevicesPage(
  projectId?: string,
  opts?: DeviceListFilters,
): Promise<PagedResult<Device>> {
  const raw = await api<PagedResult<Device>>(`/api/v1/devices${deviceQuery(projectId, opts)}`);
  return normalizePagedResult(raw, opts?.page ?? 1, opts?.pageSize ?? PAGE_SIZE);
}

/** @deprecated 请用 listDevicesPage */
export async function listDevices(
  projectId?: string,
  opts?: DeviceListFilters,
): Promise<Device[]> {
  return (await listDevicesPage(projectId, opts)).items;
}

/** DevicePicker / 计划表单：自动翻页拉全量（上限 MAX_PAGES 页）。 */
export async function fetchAllDevices(projectId?: string): Promise<Device[]> {
  const all: Device[] = [];
  for (let page = 1; page <= MAX_PAGES; page += 1) {
    const res = await listDevicesPage(projectId, { page, pageSize: PAGE_SIZE });
    all.push(...res.items);
    if (res.items.length < res.page_size || all.length >= res.total) break;
  }
  return all;
}

export async function fetchDeviceBoard(
  projectId?: string,
  opts?: DeviceListFilters,
): Promise<DeviceBoard | null> {
  try {
    return await api<DeviceBoard>(`/api/v1/devices/board${deviceQuery(projectId, opts)}`);
  } catch {
    return null;
  }
}

export const DEVICE_LIST_PAGE_SIZE = PAGE_SIZE;

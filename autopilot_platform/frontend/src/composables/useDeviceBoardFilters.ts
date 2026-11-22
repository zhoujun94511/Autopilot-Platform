/**
 * 设备面板筛选 / 分页 / 分组（AUD-2026-12 Wave 4）。
 */
import { computed, onScopeDispose, ref, watch, type Ref } from "vue";
import type { Device } from "../api";
import { DEVICE_LIST_PAGE_SIZE, listDevicesPage } from "../api/devices";
import { usePagedList } from "./usePagedList";
import {
  groupDevicesByPlatform,
  normalizePlatform,
  type PlatformBucket,
} from "../utils/deviceDisplay";

export type DeviceBusyFilter = "" | "free" | "busy";
export type DevicePlatformFilter = "all" | PlatformBucket;

const DEVICE_VIEW_KEY = "ap-mc-device-view";

function preferredView(): "cards" | "list" {
  try {
    return localStorage.getItem(DEVICE_VIEW_KEY) === "cards" ? "cards" : "list";
  } catch {
    return "list";
  }
}

export function useDeviceBoardFilters(opts: {
  deviceBoard: Ref<{ summary?: { online?: number; by_platform?: Record<string, unknown> } } | null | undefined>;
  devicesVersion: Ref<unknown>;
}) {
  const { deviceBoard, devicesVersion } = opts;

  const search = ref("");
  const busyFilter = ref<DeviceBusyFilter>("");
  const platformFilter = ref<DevicePlatformFilter>("all");
  const viewMode = ref(preferredView());
  const expandedMeta = ref<Record<string, boolean>>({});

  watch(viewMode, (mode) => {
    try {
      localStorage.setItem(DEVICE_VIEW_KEY, mode);
    } catch {
      // The switch remains usable when browser storage is disabled.
    }
  });

  const list = usePagedList<Device>({
    immediate: false,
    pageSize: DEVICE_LIST_PAGE_SIZE,
    fetchPage: ({ page, pageSize }) =>
      listDevicesPage(undefined, {
        page,
        pageSize,
        q: search.value.trim() || undefined,
        platform: platformFilter.value === "all" ? undefined : platformFilter.value,
        busy: busyFilter.value || undefined,
      }),
    filterSources: [busyFilter, platformFilter],
    isUnfiltered: () =>
      !busyFilter.value && platformFilter.value === "all" && !search.value.trim(),
  });

  const {
    items,
    total,
    page,
    pageSize,
    loading,
    hasLoaded,
    error,
    refreshing,
    universeEmpty,
    reload,
    setPage,
    setPageSize,
  } = list;

  const onlineTotal = computed(() => deviceBoard.value?.summary?.online ?? 0);

  /** 已确认没有设备时，切筛选不必再打接口，避免空状态被 loading 拆掉重挂。 */
  function skipEmptyFilterReload() {
    return (
      hasLoaded.value &&
      items.value.length === 0 &&
      universeEmpty.value
    );
  }

  async function reloadBoard(resetPage = false) {
    await reload(resetPage);
  }

  const platformChipCounts = computed(() => {
    const counts: Record<"all" | PlatformBucket, number> = {
      all: onlineTotal.value,
      android: 0,
      ios: 0,
      web: 0,
      other: 0,
    };
    const byPlat = deviceBoard.value?.summary?.by_platform ?? {};
    for (const [plat, s] of Object.entries(byPlat)) {
      const row = s as { total?: number };
      counts[normalizePlatform(plat)] += Number(row.total || 0);
    }
    return counts;
  });

  const groupedDevices = computed(() => groupDevicesByPlatform(items.value));

  const showPlatformSections = computed(
    () => platformFilter.value === "all" && groupedDevices.value.length > 1,
  );

  function toggleMeta(key: string) {
    expandedMeta.value = { ...expandedMeta.value, [key]: !expandedMeta.value[key] };
  }

  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  watch(search, () => {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      if (skipEmptyFilterReload()) return;
      void reloadBoard(true);
    }, 280);
  });
  onScopeDispose(() => clearTimeout(searchTimer));

  watch(devicesVersion, () => void reloadBoard(false));

  void reloadBoard(true);

  return {
    search,
    busyFilter,
    platformFilter,
    viewMode,
    expandedMeta,
    items,
    total,
    page,
    pageSize,
    loading,
    hasLoaded,
    error,
    refreshing,
    reload: reloadBoard,
    setPage,
    setPageSize,
    onlineTotal,
    platformChipCounts,
    groupedDevices,
    showPlatformSections,
    toggleMeta,
  };
}

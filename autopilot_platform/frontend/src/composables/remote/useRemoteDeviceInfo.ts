import { computed, ref } from "vue";
import {
  remoteCommandReady,
  remoteStreamControlReady,
  sendRemoteCommand,
  waitForRemoteStreamControl,
} from "./useRemoteCommands";

export type RemoteDeviceInfo = Record<string, unknown> & {
  platform?: string;
  device_id?: string;
};

const BATTERY_STATUS: Record<string, string> = {
  Charging: "充电中",
  Discharging: "放电中",
  "Not charging": "未充电",
  Full: "已充满",
  Unknown: "未知",
};

const ACTIVATION: Record<string, string> = {
  Activated: "已激活",
  Unactivated: "未激活",
};

const INFO_TIMEOUT_MS = 25_000;
const CONTROL_READY_WAIT_MS = 120_000;

const info = ref<RemoteDeviceInfo>({});
const loading = ref(false);
const error = ref("");
const updatedAt = ref(0);
let inFlight: Promise<void> | null = null;

function applyPayload(result: Record<string, unknown>): void {
  const next: RemoteDeviceInfo = { ...result };
  delete next.t;
  delete next.request_id;
  delete next.wifi_ssid;
  info.value = next;
  updatedAt.value = Date.now();
}

export function formatUptime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const parts: string[] = [];
  if (days) parts.push(`${days} 天`);
  if (hours) parts.push(`${hours} 小时`);
  if (minutes || !parts.length) parts.push(`${minutes} 分钟`);
  return parts.join(" ");
}

export function batteryStatusLabel(status: string): string {
  return BATTERY_STATUS[status] || status;
}

export function activationLabel(state: string): string {
  return ACTIVATION[state] || state;
}

export function resetRemoteDeviceInfo(): void {
  info.value = {};
  loading.value = false;
  error.value = "";
  updatedAt.value = 0;
  inFlight = null;
}

export function useRemoteDeviceInfo() {
  const loaded = computed(() => Object.keys(info.value).length > 0);

  async function load(options: { force?: boolean; silent?: boolean } = {}): Promise<void> {
    const force = Boolean(options.force);
    const silent = Boolean(options.silent);
    if (inFlight && !force) return inFlight;
    if (!remoteCommandReady.value) {
      if (!silent) error.value = "可靠命令通道尚未就绪，请稍候再试";
      return;
    }
    loading.value = true;
    if (!silent) error.value = "";
    const run = (async () => {
      try {
        const controlReady = await waitForRemoteStreamControl(CONTROL_READY_WAIT_MS);
        if (!controlReady) {
          if (!silent) error.value = "等待视频流与控制通道就绪超时，请稍后再试";
          return;
        }
        const result = await sendRemoteCommand({ t: "device.info" }, INFO_TIMEOUT_MS);
        applyPayload(result);
        error.value = "";
      } catch (cause) {
        if (!silent) {
          error.value = cause instanceof Error ? cause.message : String(cause);
        }
      } finally {
        loading.value = false;
        inFlight = null;
      }
    })();
    inFlight = run;
    return run;
  }

  async function refresh(force = false): Promise<void> {
    return load({ force, silent: false });
  }

  async function prefetch(): Promise<void> {
    if (!remoteCommandReady.value || !remoteStreamControlReady.value) return;
    if (loaded.value || loading.value || inFlight) return;
    await load({ silent: true });
  }

  return { info, loading, error, loaded, updatedAt, refresh, prefetch };
}

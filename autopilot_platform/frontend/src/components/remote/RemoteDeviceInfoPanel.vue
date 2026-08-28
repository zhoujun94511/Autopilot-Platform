<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { formatFileSize } from "../../composables/remote/files/formatFileSize";
import { notify } from "../../composables/useNotify";
import {
  activationLabel,
  batteryStatusLabel,
  formatUptime,
  useRemoteDeviceInfo,
} from "../../composables/remote/useRemoteDeviceInfo";

type InfoRow = { label: string; value: string; mono?: boolean; copy?: boolean };
type InfoGroup = { id: string; title: string; rows: InfoRow[] };
type MeterTone = "ok" | "warn" | "danger";

const { info, loading, error, loaded, updatedAt, refresh, prefetch } = useRemoteDeviceInfo();
const copiedKey = ref("");
let copiedTimer = 0;

onMounted(() => {
  if (!loaded.value) void prefetch();
});

function text(key: string): string {
  const value = info.value[key];
  if (value == null || value === "") return "";
  return String(value);
}

function num(key: string): number | null {
  const value = info.value[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

const title = computed(
  () =>
    text("market_name") ||
    text("marketing") ||
    text("model") ||
    text("name") ||
    text("device_id") ||
    "设备",
);

const osLine = computed(() => {
  if (text("android_version")) {
    const sdk = num("sdk");
    return sdk ? `Android ${text("android_version")} · API ${sdk}` : `Android ${text("android_version")}`;
  }
  if (text("ios_version")) {
    return `iOS ${text("ios_version")}${text("build") ? ` · ${text("build")}` : ""}`;
  }
  return "";
});

const brandLine = computed(() => {
  if (text("manufacturer")) return text("manufacturer");
  if (text("brand")) return text("brand");
  if (text("device_class")) return text("device_class");
  return "";
});

const connectionLabel = computed(() => {
  const kind = text("connection_type");
  if (kind === "wifi") return "Wi-Fi";
  if (kind === "usb") return "USB";
  return kind;
});

const battery = computed(() => num("battery_level"));
const storageUsed = computed(() => num("storage_used_bytes"));
const storageTotal = computed(() => num("storage_total_bytes"));
const memoryUsed = computed(() => num("memory_used_bytes"));
const memoryTotal = computed(() => num("memory_total_bytes"));
const storagePct = computed(() =>
  storageUsed.value != null && storageTotal.value
    ? Math.round((storageUsed.value / storageTotal.value) * 100)
    : null,
);
const memoryPct = computed(() =>
  memoryUsed.value != null && memoryTotal.value
    ? Math.round((memoryUsed.value / memoryTotal.value) * 100)
    : null,
);

function toneFor(pct: number | null, invert = false): MeterTone {
  if (pct == null) return "ok";
  if (invert) {
    if (pct >= 90) return "danger";
    if (pct >= 75) return "warn";
    return "ok";
  }
  if (pct <= 15) return "danger";
  if (pct <= 30) return "warn";
  return "ok";
}

const meters = computed(() => {
  const items: {
    id: string;
    label: string;
    pct: number;
    primary: string;
    sub: string;
    tone: MeterTone;
  }[] = [];
  if (battery.value != null) {
    const temp = num("battery_temp_c");
    const status = batteryStatusLabel(text("battery_status"));
    items.push({
      id: "battery",
      label: "电量",
      pct: battery.value,
      primary: `${battery.value}%`,
      sub: [status, temp != null ? `${temp.toFixed(1)}°C` : ""].filter(Boolean).join(" · "),
      tone: toneFor(battery.value),
    });
  }
  if (storagePct.value != null && storageUsed.value != null && storageTotal.value != null) {
    items.push({
      id: "storage",
      label: "存储",
      pct: storagePct.value,
      primary: `${storagePct.value}%`,
      sub: `${formatFileSize(storageUsed.value)} / ${formatFileSize(storageTotal.value)}`,
      tone: toneFor(storagePct.value, true),
    });
  }
  if (memoryPct.value != null && memoryUsed.value != null && memoryTotal.value != null) {
    items.push({
      id: "memory",
      label: "内存",
      pct: memoryPct.value,
      primary: `${memoryPct.value}%`,
      sub: `${formatFileSize(memoryUsed.value)} / ${formatFileSize(memoryTotal.value)}`,
      tone: toneFor(memoryPct.value, true),
    });
  }
  return items;
});

const groups = computed<InfoGroup[]>(() => {
  const add = (rows: InfoRow[], label: string, value: string, extra?: Partial<InfoRow>) => {
    if (value) rows.push({ label, value, ...extra });
  };
  const hardware: InfoRow[] = [];
  add(hardware, "芯片", [text("soc_manufacturer"), text("soc_model")].filter(Boolean).join(" · "));
  add(hardware, "架构", text("abi") || text("cpu_arch"), { mono: true });
  const width = num("resolution_width");
  const height = num("resolution_height");
  if (width && height) {
    add(
      hardware,
      "分辨率",
      `${width} × ${height}${num("density_dpi") != null ? ` · ${num("density_dpi")} dpi` : ""}`,
      { mono: true },
    );
  }

  const network: InfoRow[] = [];
  add(network, "IP", text("ip_address"), { mono: true, copy: true });
  add(network, "运行时间", formatUptime(num("uptime_seconds") ?? -1));

  const system: InfoRow[] = [];
  add(system, "系统", osLine.value);
  if (text("android_version")) add(system, "构建", text("build_id"), { mono: true });
  else add(system, "构建", text("build"), { mono: true });
  add(system, "产品标识", text("product_type"), { mono: true });
  add(system, "内部型号", text("hardware_model") || text("model_number"), { mono: true });
  add(system, "激活", activationLabel(text("activation_state")));
  add(system, "区域", text("region"));
  add(system, "时区", text("timezone"));

  const identity: InfoRow[] = [];
  const serial = text("serial");
  const udid = text("device_id");
  add(identity, "序列号", serial, { mono: true, copy: true });
  if (udid && udid !== serial) add(identity, "UDID", udid, { mono: true, copy: true });
  add(identity, "IMEI", text("imei"), { mono: true, copy: true });
  add(identity, "IMEI ②", text("imei2") && text("imei2") !== text("imei") ? text("imei2") : "", {
    mono: true,
    copy: true,
  });
  add(identity, "WDA", text("wda_version"));

  return [
    { id: "hardware", title: "硬件", rows: hardware },
    { id: "network", title: "连接", rows: network },
    { id: "system", title: "系统", rows: system },
    { id: "identity", title: "标识", rows: identity },
  ].filter((group) => group.rows.length);
});

const syncedLabel = computed(() => {
  if (!updatedAt.value) return "";
  const delta = Date.now() - updatedAt.value;
  if (delta < 15_000) return "刚刚同步";
  if (delta < 60_000) return `${Math.max(1, Math.round(delta / 1000))} 秒前`;
  return `${Math.max(1, Math.round(delta / 60_000))} 分钟前`;
});

async function copyValue(row: InfoRow) {
  try {
    await navigator.clipboard.writeText(row.value);
    copiedKey.value = row.label;
    window.clearTimeout(copiedTimer);
    copiedTimer = window.setTimeout(() => {
      copiedKey.value = "";
    }, 1600);
  } catch {
    copiedKey.value = "";
    notify("复制失败，请检查浏览器剪贴板权限", "error");
  }
}
</script>

<template>
  <section class="remote-tool-panel remote-device-info-panel">
    <header class="rdi-head">
      <div class="rdi-identity">
        <p class="rdi-kicker">{{ brandLine || "远程设备" }}</p>
        <h3>{{ loaded ? title : "设备信息" }}</h3>
        <p v-if="osLine" class="rdi-os">{{ osLine }}</p>
      </div>
      <div class="rdi-head-actions">
        <span v-if="connectionLabel" class="rdi-chip">{{ connectionLabel }}</span>
        <button type="button" class="small" :disabled="loading" @click="refresh(true)">
          {{ loading ? "同步中" : "刷新" }}
        </button>
      </div>
    </header>
    <p v-if="syncedLabel && loaded" class="rdi-sync muted">{{ syncedLabel }}</p>

    <div v-if="!loaded && !error" class="rdi-skeleton" aria-busy="true" aria-label="正在读取设备信息">
      <span /><span /><span />
    </div>

    <div v-else-if="meters.length" class="rdi-meters">
      <article v-for="meter in meters" :key="meter.id" class="rdi-meter" :class="meter.tone">
        <div class="rdi-meter-top">
          <span>{{ meter.label }}</span>
          <strong>{{ meter.primary }}</strong>
        </div>
        <div
          class="rdi-meter-track"
          role="progressbar"
          :aria-valuenow="meter.pct"
          aria-valuemin="0"
          aria-valuemax="100"
          :aria-label="meter.label"
        >
          <i :style="{ width: `${Math.max(0, Math.min(100, meter.pct))}%` }" />
        </div>
        <small v-if="meter.sub">{{ meter.sub }}</small>
      </article>
    </div>

    <section v-for="group in groups" :key="group.id" class="rdi-group">
      <h4>{{ group.title }}</h4>
      <dl>
        <div v-for="row in group.rows" :key="row.label" class="rdi-row">
          <dt>{{ row.label }}</dt>
          <dd :class="{ mono: row.mono }">
            <span :title="row.value">{{ row.value }}</span>
            <button
              v-if="row.copy"
              type="button"
              class="rdi-copy"
              :aria-label="`复制${row.label}`"
              @click="copyValue(row)"
            >
              {{ copiedKey === row.label ? "已复制" : "复制" }}
            </button>
          </dd>
        </div>
      </dl>
    </section>

    <p v-if="!loading && loaded && !groups.length && !meters.length" class="muted">
      设备未返回可展示字段，可稍后刷新。
    </p>
    <p v-if="error" class="bad">{{ error }}</p>
  </section>
</template>

<style scoped>
.remote-device-info-panel {
  gap: 0.85rem;
}

.rdi-head {
  align-items: flex-start;
}

.rdi-identity {
  min-width: 0;
  padding-left: 0.7rem;
  border-left: 2px solid var(--brand);
}

.rdi-kicker {
  margin: 0 0 0.15rem;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
}

.rdi-identity h3 {
  font-size: 1.05rem;
  line-height: 1.25;
}

.rdi-os {
  margin: 0.2rem 0 0;
  font-size: 0.78rem;
  color: var(--text-secondary);
}

.rdi-head-actions {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-shrink: 0;
}

.rdi-chip {
  padding: 0.18rem 0.45rem;
  border-radius: 999px;
  border: 1px solid var(--info-soft-border, var(--line));
  background: var(--action-selected, var(--surface-soft));
  color: var(--accent-text);
  font-size: 0.68rem;
  font-weight: 700;
}

.rdi-sync {
  margin: -0.45rem 0 0;
  font-size: 0.72rem;
}

.rdi-skeleton {
  display: grid;
  gap: 0.45rem;
}

.rdi-skeleton span {
  height: 3.1rem;
  border-radius: var(--radius-md, 6px);
  background: linear-gradient(
    90deg,
    var(--surface-soft) 0%,
    var(--surface-elevated, var(--control-bg-hover)) 50%,
    var(--surface-soft) 100%
  );
  background-size: 200% 100%;
  animation: rdi-shimmer 1.1s ease-in-out infinite;
}

.rdi-meters {
  display: grid;
  gap: 0.45rem;
}

.rdi-meter {
  display: grid;
  gap: 0.28rem;
  padding: 0.55rem 0.65rem;
  border-radius: var(--radius-md, 6px);
  border: 1px solid var(--line-soft);
  background: var(--surface-soft);
}

.rdi-meter-top {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.5rem;
  font-size: 0.75rem;
  color: var(--muted);
}

.rdi-meter-top strong {
  font-size: 0.92rem;
  color: var(--text);
}

.rdi-meter-track {
  height: 0.32rem;
  border-radius: 999px;
  background: var(--control-bg, rgba(255, 255, 255, 0.06));
  overflow: hidden;
}

.rdi-meter-track i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--brand);
}

.rdi-meter.warn .rdi-meter-track i {
  background: var(--warning);
}

.rdi-meter.danger .rdi-meter-track i {
  background: var(--bad);
}

.rdi-meter small {
  font-size: 0.72rem;
  color: var(--muted);
}

.rdi-group h4 {
  margin: 0 0 0.4rem;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
}

.rdi-group dl {
  margin: 0;
  display: grid;
  gap: 0.05rem;
}

.rdi-row {
  display: grid;
  grid-template-columns: 4.6rem minmax(0, 1fr);
  gap: 0.55rem;
  align-items: center;
  min-height: 1.7rem;
  padding: 0.18rem 0;
  border-bottom: 1px solid var(--line-soft);
}

.rdi-row:last-child {
  border-bottom: none;
}

.rdi-row dt {
  color: var(--muted);
  font-size: 0.75rem;
}

.rdi-row dd {
  margin: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.4rem;
  min-width: 0;
  font-size: 0.82rem;
  color: var(--text);
}

.rdi-row dd span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rdi-row dd.mono span {
  font-family: ui-monospace, "Cascadia Mono", "SF Mono", Consolas, monospace;
  font-size: 0.76rem;
}

.rdi-copy {
  flex-shrink: 0;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--accent-text);
  font-size: 0.72rem;
  font-weight: 600;
  cursor: pointer;
}

.rdi-copy:hover {
  text-decoration: underline;
}

@keyframes rdi-shimmer {
  0% {
    background-position: 100% 0;
  }
  100% {
    background-position: -100% 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .rdi-skeleton span {
    animation: none;
  }
}
</style>

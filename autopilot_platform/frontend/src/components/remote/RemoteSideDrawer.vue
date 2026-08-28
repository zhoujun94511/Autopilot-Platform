<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import {
  remoteCommandReady,
  remoteStreamControlReady,
} from "../../composables/remote/useRemoteCommands";
import {
  resetRemoteDeviceInfo,
  useRemoteDeviceInfo,
} from "../../composables/remote/useRemoteDeviceInfo";
import RemoteAppsPanel from "./RemoteAppsPanel.vue";
import RemoteClipboardPanel from "./RemoteClipboardPanel.vue";
import RemoteDeviceInfoPanel from "./RemoteDeviceInfoPanel.vue";
import RemoteDeviceLogPanel from "./RemoteDeviceLogPanel.vue";
import RemoteFilesPanel from "./RemoteFilesPanel.vue";
import RemoteIosControls from "./RemoteIosControls.vue";
import RemoteQuickControls from "./RemoteQuickControls.vue";
import RemoteStreamPanel from "./RemoteStreamPanel.vue";

const props = defineProps<{
  platform: string;
  readonly?: boolean;
  status: string;
  error?: string;
  transportMode: string;
}>();

const emit = defineEmits<{
  close: [];
  androidKey: [code: number];
  androidPower: [mode: 0 | 2];
  androidAction: [action: "rotate" | "expandNotification" | "expandSettings" | "collapse"];
}>();

const allTabs = [
  ["controls", "控制"],
  ["clipboard", "剪贴板"],
  ["files", "文件"],
  ["apps", "应用"],
  ["stream", "流质量"],
  ["device", "设备信息"],
  ["logs", "日志"],
] as const;
type DrawerTab = (typeof allTabs)[number][0];
function defaultTab(_platform: string): DrawerTab {
  return "controls";
}

const tabs = allTabs;
const active = ref<DrawerTab>(defaultTab(props.platform));

watch(
  () => props.platform,
  (platform) => {
    active.value = defaultTab(platform);
  },
);

const { prefetch } = useRemoteDeviceInfo();

watch(
  [remoteCommandReady, remoteStreamControlReady],
  ([cmdReady, streamReady]) => {
    if (!cmdReady) resetRemoteDeviceInfo();
    else if (streamReady) void prefetch();
  },
  { immediate: true },
);

onMounted(() => {
  if (remoteCommandReady.value) void prefetch();
});
</script>

<template>
  <aside class="remote-drawer">
    <header class="remote-drawer-head">
      <strong>更多</strong>
      <button type="button" class="drawer-close" title="关闭" aria-label="关闭侧栏" @click="emit('close')">
        ×
      </button>
    </header>
    <nav class="remote-tabs" role="tablist" aria-label="远控工具">
      <button
        v-for="[id, label] in tabs"
        :key="id"
        type="button"
        role="tab"
        class="remote-tab"
        :class="{ active: active === id }"
        :aria-selected="active === id"
        @click="active = id"
      >
        {{ label }}
      </button>
    </nav>
    <div class="remote-drawer-body">
      <RemoteIosControls
        v-if="active === 'controls' && platform === 'ios'"
        :readonly="readonly"
      />
      <RemoteQuickControls
        v-else-if="active === 'controls'"
        :readonly="readonly"
        @android-key="emit('androidKey', $event)"
        @android-power="emit('androidPower', $event)"
        @android-action="emit('androidAction', $event)"
      />
      <RemoteClipboardPanel v-else-if="active === 'clipboard'" :readonly="readonly" />
      <RemoteFilesPanel v-else-if="active === 'files'" :readonly="readonly" :platform="platform" />
      <RemoteAppsPanel v-else-if="active === 'apps'" :readonly="readonly" :platform="platform" />
      <RemoteStreamPanel
        v-else-if="active === 'stream'"
        :readonly="readonly"
        :platform="platform"
        :status="status"
        :error="error"
        :transport-mode="transportMode"
      />
      <RemoteDeviceInfoPanel v-else-if="active === 'device'" />
      <RemoteDeviceLogPanel
        v-else-if="active === 'logs'"
        :readonly="readonly"
        :platform="platform"
      />
    </div>
  </aside>
</template>

<style>
.remote-drawer {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  height: 100%;
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg, 8px);
  background: var(--surface-secondary);
  overflow: hidden;
}

.remote-drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  flex-shrink: 0;
  padding: 0.55rem 0.7rem 0.15rem;
}

.remote-drawer-head strong {
  font-size: 0.88rem;
}

.drawer-close {
  width: 1.85rem;
  height: 1.85rem;
  padding: 0;
  border: 0;
  border-radius: var(--radius-md, 6px);
  font-size: 1.15rem;
  line-height: 1;
  color: var(--muted);
  background: transparent;
  cursor: pointer;
}

.drawer-close:hover {
  color: var(--fg);
  background: var(--action-hover);
}

.remote-tabs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.35rem;
  flex-shrink: 0;
  padding: 0.55rem 0.65rem;
  border-bottom: 1px solid var(--line-soft);
  background: var(--surface-primary);
}

.remote-tabs .remote-tab {
  min-width: 0;
  padding: 0.45rem 0.35rem;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md, 6px);
  font-size: 0.78rem;
  font-weight: 600;
  line-height: 1.25;
  color: var(--text-secondary);
  background: var(--surface-soft, var(--control-bg));
  cursor: pointer;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition:
    color 0.15s ease,
    background-color 0.15s ease,
    border-color 0.15s ease,
    box-shadow 0.15s ease;
}

.remote-tabs .remote-tab:hover {
  color: var(--text);
  background: var(--action-hover);
  border-color: var(--line);
}

.remote-tabs .remote-tab.active {
  color: var(--accent-text);
  font-weight: 700;
  border-color: var(--info-soft-border);
  background: var(--action-selected);
  box-shadow: inset 0 -2px 0 var(--brand, var(--accent-text));
}

.remote-tabs .remote-tab:focus-visible {
  outline: 2px solid var(--brand, var(--accent-text));
  outline-offset: 1px;
}

.remote-drawer-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 0.85rem;
  display: flex;
  flex-direction: column;
}

.remote-drawer-body > .remote-tool-panel {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.remote-drawer-body > .remote-files-panel {
  overflow: hidden;
}

.remote-drawer-body > .remote-apps-panel {
  overflow: hidden;
}

.remote-drawer-body > .remote-device-info-panel {
  overflow: auto;
}

.remote-tool-panel {
  display: grid;
  gap: 0.75rem;
  align-content: start;
}

.remote-tool-panel header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.remote-tool-panel h3 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--text);
}

.remote-tool-panel textarea,
.remote-tool-panel input,
.remote-tool-panel select {
  width: 100%;
  box-sizing: border-box;
  max-width: 100%;
  padding: 0.55rem 0.65rem;
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: var(--radius-md, 6px);
  background: var(--input-bg);
  font: inherit;
  font-size: 0.88rem;
  line-height: 1.45;
}

.remote-tool-panel textarea {
  resize: vertical;
  min-height: 6.5rem;
}

.remote-tool-panel textarea::placeholder,
.remote-tool-panel input::placeholder {
  color: var(--text-disabled);
}

.remote-tool-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  align-items: center;
}

.remote-tool-actions .small,
.remote-tool-panel .small {
  padding: 0.38rem 0.62rem;
  border: 1px solid var(--btn-border);
  border-radius: var(--radius-md, 6px);
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--btn-fg);
  background: var(--btn-bg);
  cursor: pointer;
  transition: var(--transition);
}

.remote-tool-actions .small:hover:not(:disabled),
.remote-tool-panel .small:hover:not(:disabled) {
  background: var(--btn-bg-hover);
}

.remote-tool-actions .small:disabled,
.remote-tool-panel .small:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.remote-tool-actions .primary,
.remote-tool-panel .primary {
  color: var(--on-accent);
  border-color: var(--brand);
  background: var(--brand);
}

.remote-tool-actions .primary:hover:not(:disabled),
.remote-tool-panel .primary:hover:not(:disabled) {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
}

.remote-tool-actions .danger,
.remote-tool-panel .danger {
  color: var(--danger-soft-fg);
  border-color: var(--danger-soft-border);
  background: var(--danger-soft-bg);
}

.remote-file-path {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  min-width: 0;
}

.remote-file-path code {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.remote-file-list,
.remote-app-list {
  display: grid;
  gap: 0.35rem;
}

.remote-file-row,
.remote-app-row,
.remote-participant {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  justify-content: space-between;
  min-width: 0;
  padding: 0.55rem 0.65rem;
  border-radius: var(--radius-md, 6px);
  background: var(--surface-soft);
  border: 1px solid var(--line-soft);
}

.remote-file-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.remote-file-row-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
}

.remote-app-row > div:first-child,
.remote-participant > div {
  display: grid;
  min-width: 0;
}

.remote-app-row small,
.remote-participant small {
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
}

.remote-stats-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.45rem;
}

.remote-stats-grid span {
  display: grid;
  gap: 0.15rem;
  padding: 0.55rem 0.65rem;
  border-radius: var(--radius-md, 6px);
  background: var(--surface-soft);
  border: 1px solid var(--line-soft);
}

.remote-stats-grid strong {
  font-size: 0.85rem;
  color: var(--text);
}

.remote-diagnostics {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.45rem 0.75rem;
  margin: 0;
}

.remote-diagnostics dt {
  color: var(--muted);
}

.remote-diagnostics dd {
  margin: 0;
  word-break: break-word;
  color: var(--text);
}

.remote-drawer-body > .remote-log-panel {
  overflow: hidden;
}

.remote-log-panel {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  align-content: stretch;
}

.remote-log-panel header {
  align-items: flex-start;
}

.remote-log-sub {
  margin: 0.2rem 0 0;
  font-size: 0.72rem;
  font-weight: 500;
  line-height: 1.4;
  color: var(--muted);
}

.remote-log-pill {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 700;
  line-height: 1.3;
  border: 1px solid var(--line-soft);
  color: var(--muted);
  background: var(--surface-soft);
}

.remote-log-pill.on {
  color: var(--ok-soft-fg);
  border-color: var(--ok-soft-border);
  background: var(--ok-soft-bg);
}

.remote-log-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: flex-end;
}

.remote-log-actions {
  flex-wrap: nowrap;
}

.remote-log-actions .small {
  flex: 1 1 0;
  min-width: 0;
}

.remote-log-filters {
  padding: 0.45rem;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md, 6px);
  background: var(--surface-soft);
}

.remote-log-field {
  display: grid;
  gap: 0.2rem;
  min-width: 0;
}

.remote-log-field > span {
  font-size: 0.68rem;
  font-weight: 600;
  color: var(--muted);
  letter-spacing: 0.01em;
}

.remote-log-field-grow {
  flex: 1 1 7rem;
}

.remote-log-toolbar .ap-select,
.remote-log-toolbar input[type="text"] {
  width: 100%;
  min-width: 0;
  max-width: none;
}

.remote-log-toolbar input[type="text"] {
  padding: 0.32rem 0.5rem;
  font-size: 0.8rem;
}

.remote-log-field:has(.ap-select) {
  flex: 1 1 10.5rem;
  min-width: 10.5rem;
}

.remote-log-toolbar .small {
  width: auto;
  flex: 0 0 auto;
}

.remote-log-toggle {
  align-self: flex-end;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.remote-log-toolbar input.bad {
  border-color: var(--bad);
}

.remote-log-opts {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
}

.remote-switch {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.78rem;
  color: var(--muted);
  cursor: pointer;
}

.remote-switch input {
  width: auto;
  margin: 0;
}

.remote-log-counter {
  margin-left: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.72rem;
}

.remote-log-wrap {
  position: relative;
  flex: 1;
  min-width: 0;
  min-height: 12rem;
  display: flex;
}

.remote-log-view {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  padding: 0.45rem 0.55rem;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md, 6px);
  background: var(--code-bg);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.74rem;
  line-height: 1.45;
}

.remote-log-empty {
  padding: 1.2rem 0.4rem;
  text-align: center;
  white-space: normal;
}

.remote-log-line {
  display: block;
  width: 100%;
  box-sizing: border-box;
  padding: 0.02rem 0.15rem;
  border-radius: 3px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: normal;
}

.remote-log-view.nowrap .remote-log-line {
  width: max-content;
  min-width: 100%;
  white-space: pre;
  overflow-wrap: normal;
  word-break: normal;
}

.remote-log-line.lvl-V { color: var(--muted); }
.remote-log-line.lvl-D { color: #6ea8fe; }
.remote-log-line.lvl-I { color: var(--text); }
.remote-log-line.lvl-W {
  color: var(--warning-soft-fg, #d4a017);
}
.remote-log-line.lvl-E {
  color: var(--bad);
  background: var(--danger-soft-bg, rgba(224, 90, 90, 0.08));
}
.remote-log-line.lvl-F {
  color: var(--text);
  font-weight: 700;
  background: var(--danger-soft-bg, rgba(224, 90, 90, 0.28));
}

.remote-log-error {
  margin: 0;
  padding: 0.4rem 0.55rem;
  border-radius: var(--radius-md, 6px);
  font-size: 0.78rem;
  color: var(--danger-soft-fg, var(--bad));
  background: var(--danger-soft-bg, rgba(224, 90, 90, 0.1));
}

.remote-log-jump {
  position: absolute;
  right: 0.7rem;
  bottom: 0.7rem;
  width: 2.1rem;
  height: 2.1rem;
  padding: 0;
  border: 0;
  border-radius: 999px;
  font-size: 1rem;
  line-height: 1;
  color: var(--on-accent);
  background: var(--brand);
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.18);
}

.muted {
  color: var(--muted);
}

.bad {
  color: var(--bad);
}

.ok {
  color: var(--ok);
}
</style>

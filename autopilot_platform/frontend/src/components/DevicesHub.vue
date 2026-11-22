<script setup lang="ts">
defineOptions({ name: "DevicesHub" });

import { ref, watch } from "vue";
import { useRoute } from "vue-router";
import { storeToRefs } from "pinia";
import { useAuthStore } from "../stores/auth";
import { useShellStore } from "../stores/shellStore";
import { useAdminStore } from "../stores/adminStore";
import { goToHubSection } from "../navigation/tabSync";
import { router } from "../router";
import DevicesPanel from "./DevicesPanel.vue";
import ResourcePoolsPanel from "./ResourcePoolsPanel.vue";
import RunnersPanel from "./RunnersPanel.vue";

type Section = "devices" | "pools" | "runners";

const auth = useAuthStore();
const { canManageUsers } = storeToRefs(auth);
const shell = useShellStore();
const { activeTab } = storeToRefs(shell);
const admin = useAdminStore();
const { auditFilter } = storeToRefs(admin);
const route = useRoute();

function sectionFromRoute(): Section {
  const s = typeof route.query.section === "string" ? route.query.section.trim() : "";
  if (s === "pools" || s === "runners" || s === "devices") return s;
  return "devices";
}

const section = ref<Section>(sectionFromRoute());

watch(
  () => route.query.section,
  () => {
    section.value = sectionFromRoute();
  },
);

function setSection(next: Section) {
  section.value = next;
  goToHubSection(router, "devices", next === "devices" ? "" : next);
}

function openDeviceAudit() {
  if (!canManageUsers.value) return;
  auditFilter.value.action = "device.";
  auditFilter.value.actor = "";
  activeTab.value = "audit";
  void admin.refreshAudits();
}
</script>

<template>
  <section class="devices-hub" aria-labelledby="device-hub-title">
    <header class="devices-header">
      <h2 id="device-hub-title">设备</h2>
      <nav class="device-sections" aria-label="设备分区">
        <button type="button" :aria-current="section === 'devices' ? 'page' : undefined" @click="setSection('devices')">
          在线设备
        </button>
        <button type="button" :aria-current="section === 'pools' ? 'page' : undefined" @click="setSection('pools')">
          设备池
        </button>
        <button type="button" :aria-current="section === 'runners' ? 'page' : undefined" @click="setSection('runners')">
          执行节点
        </button>
      </nav>
      <div v-if="canManageUsers && section === 'devices'" class="device-header-actions">
        <button
          type="button"
          class="ghost small"
          @click="openDeviceAudit"
        >
          操作记录
        </button>
      </div>
    </header>
    <DevicesPanel v-if="section === 'devices'" embedded />
    <div v-else class="device-management">
      <ResourcePoolsPanel v-if="section === 'pools'" embedded />
      <RunnersPanel v-else embedded />
    </div>
  </section>
</template>

<style scoped>
.devices-hub {
  min-width: 0;
  background: var(--vben-bg-surface);
  border: 1px solid var(--vben-border);
  border-radius: var(--vben-radius-xl);
  box-shadow: var(--vben-shadow-card);
  overflow: hidden;
}

.devices-header {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0 var(--space-4);
  padding-inline: 20px;
  border-bottom: 1px solid var(--line-soft);
}

.devices-header h2 {
  margin: 0;
  color: var(--text);
  font-size: var(--font-size-title);
  font-weight: 650;
}

.device-header-actions {
  margin-inline-start: auto;
}

.device-sections {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  min-width: 0;
}

.device-sections button {
  min-height: 54px;
  padding-inline: 6px;
  border: 0;
  border-bottom: 2px solid transparent;
  border-radius: 0;
  background: transparent;
  color: var(--muted);
}

.device-sections button[aria-current] {
  border-bottom-color: var(--accent);
  color: var(--accent-text);
  font-weight: 650;
}

.device-sections button:hover {
  color: var(--accent-text);
}

.device-management {
  padding: 16px 20px;
}

@media (max-width: 720px) {
  .devices-header,
  .device-management {
    padding-inline: 12px;
  }
  .devices-header h2 {
    padding-top: 10px;
  }
  .device-sections {
    order: 1;
    flex-basis: 100%;
  }
  .device-header-actions {
    padding-top: 7px;
  }
  .device-sections button {
    min-height: 42px;
  }
}
</style>

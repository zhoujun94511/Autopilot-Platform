<script setup lang="ts">
defineOptions({ name: "DevicesHub" });

import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { storeToRefs } from "pinia";
import { useAuthStore } from "../stores/auth";
import { useShellStore } from "../stores/shellStore";
import { useCapabilities } from "../composables/useCapabilities";
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
const caps = useCapabilities();
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

const sectionMeta = computed(() => {
  const manageInfra = caps.canManageInfra;
  const canOps = caps.canOps;
  if (section.value === "pools") {
    return {
      title: "设备池",
      desc: canOps
        ? "按组织把设备授权给项目（不是在线设备列表）。查看全部设备请切到「在线设备」。"
        : manageInfra
          ? "给组织划定可用设备。具体用哪台，请在创建批跑或计划时选择。"
          : "查看本组织可以使用的设备范围。",
    };
  }
  if (section.value === "runners") {
    return {
      title: "执行节点",
      desc: canOps ? "" : "查看当前可用的执行节点。",
    };
  }
  return {
    title: "在线设备",
    desc: manageInfra
      ? "查看在线设备，需要时可以占用或释放。跑任务请到「批跑」或「计划」里选设备，不选则自动分配空闲设备。"
      : "查看设备是否空闲。创建任务时请到「批跑」或「计划」里选设备，不选则自动分配。",
  };
});

function openDeviceAudit() {
  if (!canManageUsers.value) return;
  auditFilter.value.action = "device.";
  auditFilter.value.actor = "";
  activeTab.value = "audit";
  void admin.refreshAudits();
}
</script>

<template>
  <!-- 单一工作区：标题 / 分区 / 内容同壳，避免三块白卡纵向堆叠 -->
  <section class="devices-hub workspace" aria-label="设备与执行">
    <header class="workspace-head">
      <div class="workspace-titles">
        <h2>设备与执行</h2>
        <p v-if="sectionMeta.desc" class="lede">{{ sectionMeta.desc }}</p>
        <button
          v-if="canManageUsers && section === 'devices'"
          type="button"
          class="linkish lede-link"
          @click="openDeviceAudit"
        >
          查看操作记录
        </button>
      </div>
      <nav class="subnav" aria-label="设备与执行分区">
        <button
          type="button"
          class="subnav-item"
          :class="{ active: section === 'devices' }"
          @click="setSection('devices')"
        >
          在线设备
        </button>
        <button
          type="button"
          class="subnav-item"
          :class="{ active: section === 'pools' }"
          @click="setSection('pools')"
        >
          设备池
        </button>
        <button
          type="button"
          class="subnav-item"
          :class="{ active: section === 'runners' }"
          @click="setSection('runners')"
        >
          执行节点
        </button>
      </nav>
    </header>

    <div class="workspace-body">
      <DevicesPanel v-if="section === 'devices'" embedded />
      <ResourcePoolsPanel v-else-if="section === 'pools'" embedded />
      <RunnersPanel v-else embedded />
    </div>
  </section>
</template>

<style scoped>
.devices-hub.workspace {
  max-width: none;
  width: 100%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: transparent;
  border: none;
  border-radius: 0;
  box-shadow: none;
  overflow: visible;
}

.workspace-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 0.85rem 1.25rem;
  padding: 0 0 0.85rem;
  margin: 0 0 0.85rem;
  border-bottom: 1px solid var(--line-soft, var(--line));
}

.workspace-titles h2 {
  margin: 0 0 0.3rem;
  font-size: 1.2rem;
  font-weight: 700;
  letter-spacing: -0.015em;
  color: var(--text);
}

.workspace-titles .lede {
  margin: 0;
  max-width: 42rem;
  color: var(--muted);
  font-size: 0.86rem;
  line-height: 1.5;
  white-space: normal;
  overflow-wrap: break-word;
}

.workspace-titles .lede-link {
  margin: 0.25rem 0 0;
  border: none;
  background: none;
  padding: 0;
  color: var(--accent, #2563eb);
  cursor: pointer;
  font: inherit;
  text-decoration: underline;
}

.subnav {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  padding: 0.2rem;
  background: var(--surface-soft, var(--surface-primary));
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  width: fit-content;
  max-width: 100%;
  flex-shrink: 0;
}

.subnav-item {
  appearance: none;
  border: none;
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: 0.82rem;
  font-weight: 650;
  padding: 0.4rem 0.85rem;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: var(--transition);
}

.subnav-item:hover {
  color: var(--text);
  background: var(--action-hover);
}

.subnav-item.active {
  color: var(--nav-active-fg);
  background: var(--nav-active-bg);
}

.workspace-body {
  padding: 0.85rem 1.25rem 1.25rem;
  min-height: 18rem;
}

/* 嵌入子面板：取消第二层白卡 */
.workspace-body :deep(.panel.embedded),
.workspace-body :deep(.panel.compact) {
  background: transparent;
  border: none;
  box-shadow: none;
  border-radius: 0;
  padding: 0;
}
</style>

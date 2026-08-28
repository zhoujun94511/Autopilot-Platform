<script setup lang="ts">
import { storeToRefs } from "pinia";
import { computed } from "vue";
import { useProjectsStore } from "../../stores/projectsStore";
import ApSelect from "../common/ApSelect.vue";

const projectsStore = useProjectsStore();
const { orgs, filterOrgId } = storeToRefs(projectsStore);
const options = computed(() => [
  { value: "", label: "全部组织" },
  ...(orgs.value || []).map((o) => ({
    value: o.id,
    label: o.name ? `${o.name} (${o.id})` : o.id,
  })),
]);
</script>

<template>
  <div class="org-select" title="切换当前组织" role="search">
    <svg
      viewBox="0 0 24 24"
      width="14"
      height="14"
      stroke="currentColor"
      stroke-width="2.5"
      fill="none"
      class="icon"
      aria-hidden="true"
    >
      <path d="M3 21h18M5 21V7l7-4 7 4v14M9 21v-6h6v6" />
    </svg>
    <ApSelect
      size="compact"
      aria-label="当前组织"
      :model-value="filterOrgId"
      :options="options"
      @update:model-value="projectsStore.selectOrg($event)"
    />
  </div>
</template>

<style scoped>
.org-select {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.25rem 0.55rem;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--surface-soft);
  min-width: 160px;
  max-width: 240px;
}
.org-select .icon {
  flex-shrink: 0;
  color: var(--muted);
}
.org-select :deep(.ap-select) {
  flex: 1;
  min-width: 0;
}
.org-select :deep(.ap-select-trigger) {
  border: none;
  background: transparent;
  min-height: 0;
  padding: 0.1rem 0;
  font-size: 0.82rem;
  box-shadow: none;
}
.org-select :deep(.ap-select-trigger:hover:not(:disabled)),
.org-select :deep(.ap-select.open .ap-select-trigger) {
  background: transparent;
  border-color: transparent;
}
</style>

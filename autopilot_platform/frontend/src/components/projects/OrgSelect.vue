<script setup lang="ts">
import { storeToRefs } from "pinia";
import { computed } from "vue";
import { Building2 } from "lucide-vue-next";
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
    <Building2 :size="14" class="icon" aria-hidden="true" />
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
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 8px;
  height: 30px;
  border-radius: 6px;
  background: transparent;
  min-width: 124px;
  max-width: 210px;
  transition: background-color 0.15s ease;
}
.org-select:hover {
  background: var(--vben-bg-hover);
}
.org-select .icon {
  flex-shrink: 0;
  color: var(--vben-fg-muted);
}
.org-select :deep(.ap-select) {
  flex: 1;
  min-width: 0;
}
.org-select :deep(.ap-select-trigger) {
  border: none;
  background: transparent;
  min-height: 0;
  padding: 0;
  font-size: 13px;
  font-weight: 500;
  color: var(--vben-fg);
  box-shadow: none;
}
.org-select :deep(.ap-select-trigger:hover:not(:disabled)),
.org-select :deep(.ap-select.open .ap-select-trigger) {
  background: transparent;
  border-color: transparent;
}
</style>

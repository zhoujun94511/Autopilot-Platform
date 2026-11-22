<script setup lang="ts">
import { storeToRefs } from "pinia";
import { computed } from "vue";
import { FolderKanban } from "lucide-vue-next";
import { useProjectsStore } from "../../stores/projectsStore";
import ApSelect from "../common/ApSelect.vue";

const projectsStore = useProjectsStore();
const { projects, filterProjectId } = storeToRefs(projectsStore);

const options = computed(() => [
  { value: "", label: "全部可见项目" },
  ...(projects.value || []).map((p) => ({
    value: p.id,
    label: p.name ? `${p.name} (${p.id})` : p.id,
  })),
]);
</script>

<template>
  <div class="project-select" title="切换当前项目" role="search">
    <FolderKanban :size="14" class="icon" aria-hidden="true" />
    <ApSelect
      size="compact"
      aria-label="当前项目"
      :model-value="filterProjectId"
      :options="options"
      @update:model-value="projectsStore.selectProject($event)"
    />
  </div>
</template>

<style scoped>
.project-select {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 8px;
  height: 30px;
  border-radius: 6px;
  background: transparent;
  min-width: 148px;
  max-width: 240px;
  transition: background-color 0.15s ease;
}
.project-select:hover {
  background: var(--vben-bg-hover);
}
.project-select .icon {
  flex-shrink: 0;
  color: var(--vben-fg-muted);
}
.project-select :deep(.ap-select) {
  flex: 1;
  min-width: 0;
}
.project-select :deep(.ap-select-trigger) {
  border: none;
  background: transparent;
  min-height: 0;
  padding: 0;
  font-size: 13px;
  font-weight: 500;
  color: var(--vben-fg);
  box-shadow: none;
}
.project-select :deep(.ap-select-trigger:hover:not(:disabled)),
.project-select :deep(.ap-select.open .ap-select-trigger) {
  background: transparent;
  border-color: transparent;
}
</style>

<script setup lang="ts">
import { storeToRefs } from "pinia";
import { computed } from "vue";
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
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
    </svg>
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
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.25rem 0.55rem;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--surface-soft);
  min-width: 180px;
  max-width: 280px;
}
.project-select .icon {
  flex-shrink: 0;
  color: var(--muted);
}
.project-select :deep(.ap-select) {
  flex: 1;
  min-width: 0;
}
.project-select :deep(.ap-select-trigger) {
  border: none;
  background: transparent;
  min-height: 0;
  padding: 0.1rem 0;
  font-size: 0.82rem;
  box-shadow: none;
}
.project-select :deep(.ap-select-trigger:hover:not(:disabled)),
.project-select :deep(.ap-select.open .ap-select-trigger) {
  background: transparent;
  border-color: transparent;
}
</style>

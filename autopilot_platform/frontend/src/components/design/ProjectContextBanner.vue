<script setup lang="ts">
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useShellStore } from "../../stores/shellStore";
import { useProjectsStore } from "../../stores/projectsStore";

const shell = useShellStore();
const projectsStore = useProjectsStore();
const { filterProjectId, projects } = storeToRefs(projectsStore);

const props = withDefaults(
  defineProps<{
    /** 写操作是否必须选项目 */
    requireProject?: boolean;
    /** 已选项目时是否展示弱提示（默认不展示，避免四页刷绿条） */
    showWhenReady?: boolean;
  }>(),
  { requireProject: true, showWhenReady: false },
);

const projectId = computed(() => filterProjectId.value?.trim() || "");
const missing = computed(() => props.requireProject && !projectId.value);
const projectName = computed(() => {
  const id = projectId.value;
  if (!id) return "";
  const hit = projects.value.find((p) => p.id === id);
  return (hit?.name || "").trim();
});

defineExpose({ projectId, missing });
</script>

<template>
  <div v-if="missing" class="alert-banner warn" role="status">
    <strong>需要先选择项目</strong>
    <span
      >设计域写操作必须绑定项目（与只读成员不同：此处是还没选项目）。请在顶部切换，或打开项目页选用一个空间。</span
    >
    <button type="button" class="small primary" @click="shell.activeTab = 'projects'">
      去选项目
    </button>
  </div>
  <div
    v-else-if="!requireProject && !projectId"
    class="alert-banner info"
    role="status"
  >
    <strong>未选项目</strong>
    <span>也可以先问测试问题。选项目后，助手才能带上该项目的需求和知识库。</span>
    <button type="button" class="small" @click="shell.activeTab = 'projects'">
      选项目（可选）
    </button>
  </div>
  <p v-else-if="showWhenReady && projectId" class="project-meta" role="status">
    当前项目
    <strong>{{ projectName || projectId }}</strong>
    <code v-if="projectName">{{ projectId }}</code>
  </p>
</template>

<style scoped>
.project-meta {
  margin: 0;
  font-size: 0.78rem;
  color: var(--muted);
  line-height: 1.4;
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.35rem 0.5rem;
}
.project-meta strong {
  color: var(--text);
  font-weight: 600;
}
.project-meta code {
  font-size: 0.72rem;
  opacity: 0.85;
}
</style>

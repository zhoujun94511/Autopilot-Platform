<script setup lang="ts">
/**
 * 执行域写操作：必须先选项目（C-OWN / PRODUCT_SURFACE A1）。
 * 与设计域 ProjectContextBanner 文案对齐，但指向执行资源语义。
 */
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useShellStore } from "../stores/shellStore";
import { useProjectsStore } from "../stores/projectsStore";
import { useCapabilities } from "../composables/useCapabilities";

withDefaults(
  defineProps<{
    /** 额外说明，如「上传制品」「新建批跑」 */
    actionHint?: string;
  }>(),
  { actionHint: "创建或上传" },
);

const shell = useShellStore();
const projectsStore = useProjectsStore();
const { filterProjectId } = storeToRefs(projectsStore);
const caps = useCapabilities();

const missingProject = computed(() => !String(filterProjectId.value || "").trim());
const viewerBlocked = computed(
  () => !missingProject.value && Boolean(caps.isProjectViewer),
);
const show = computed(() => missingProject.value || viewerBlocked.value);
</script>

<template>
  <div v-if="show" class="alert-banner warn" role="status">
    <template v-if="missingProject">
      <strong>需要先选择项目</strong>
      <span
        >制品 / 批跑 / 计划 / 应用包必须归属项目，不能无项目{{ actionHint }}。请在顶部切换项目。</span
      >
      <button type="button" class="small primary" @click="shell.activeTab = 'projects'">
        去选项目
      </button>
    </template>
    <template v-else>
      <strong>当前为项目只读成员</strong>
      <span>可查看执行资源，无法{{ actionHint }}。</span>
    </template>
  </div>
</template>

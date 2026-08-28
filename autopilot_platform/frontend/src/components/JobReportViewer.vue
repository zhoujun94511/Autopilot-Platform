<script setup lang="ts">
import { storeToRefs } from "pinia";
import { useExecStore } from "../stores/execution";
import ApModal from "./ApModal.vue";

const exec = useExecStore();
const { reportView } = storeToRefs(exec);

function onClose() {
  exec.closeJobReport();
}

function shortId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 12)}…` : id;
}
</script>

<template>
  <ApModal
    v-if="reportView"
    xwide
    :title="`任务报告 ${shortId(reportView.jobId)}`"
    @close="onClose"
  >
    <iframe
      class="job-report-frame"
      sandbox="allow-scripts"
      :src="reportView.url"
      title="任务报告"
    />
    <template #actions>
      <button type="button" class="ap-btn primary" data-autofocus @click="onClose">
        关闭
      </button>
    </template>
  </ApModal>
</template>

<style scoped>
.job-report-frame {
  display: block;
  width: 100%;
  height: min(72vh, 800px);
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface, #fff);
}
</style>

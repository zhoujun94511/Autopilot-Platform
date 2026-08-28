<script setup lang="ts">
import { computed } from "vue";
import type { RemoteUploadPhase } from "../../../composables/remote/useRemoteFiles";
import { isAndroidRootDir } from "../../../composables/remote/files/remoteUploadPath";

const props = defineProps<{
  destination: string;
  progress: number;
  transferLabel: string;
  phase?: RemoteUploadPhase;
  readonly?: boolean;
  platform?: string;
}>();

const emit = defineEmits<{
  cancel: [];
}>();

const isIos = computed(() => props.platform === "ios");
const busy = computed(() => props.phase === "sending" || props.phase === "writing");
const writing = computed(() => props.phase === "writing");
const percent = computed(() => Math.round(Math.min(1, Math.max(0, props.progress)) * 100));
const showRootWarning = computed(
  () => !isIos.value && isAndroidRootDir(props.destination),
);

const statusText = computed(() => {
  if (writing.value) {
    return props.transferLabel
      ? `正在写入设备 · ${props.transferLabel}`
      : "正在写入设备";
  }
  if (props.transferLabel) {
    return `上传 ${props.transferLabel} · ${percent.value}%`;
  }
  return `上传中 · ${percent.value}%`;
});
</script>

<template>
  <div v-if="!readonly" class="remote-file-upload-bar">
    <div v-if="busy" class="remote-file-upload-progress" role="status" aria-live="polite">
      <progress v-if="writing" />
      <progress v-else :value="progress" max="1" />
      <div class="remote-file-upload-status">
        <span class="remote-file-upload-status-text">{{ statusText }}</span>
        <button type="button" class="small danger" @click="emit('cancel')">取消</button>
      </div>
    </div>
    <p v-else class="remote-file-upload-dest">
      上传到 <code>{{ destination }}</code>
      <span v-if="showRootWarning" class="remote-file-upload-warn">根目录通常不可写，建议先进入 /sdcard</span>
      <span v-else class="muted">{{
        isIos ? "点「上传文件」或拖放到列表" : "点「上传文件」或拖放到下方列表"
      }}</span>
    </p>
  </div>
</template>

<style scoped>
.remote-file-upload-bar {
  display: grid;
  gap: 0.4rem;
}

.remote-file-upload-dest {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.35rem 0.55rem;
  margin: 0;
  font-size: 0.78rem;
  color: var(--text);
}

.remote-file-upload-dest code {
  font-size: 0.78rem;
}

.remote-file-upload-warn {
  color: var(--danger-soft-fg, #b42318);
}

.remote-file-upload-progress {
  display: grid;
  gap: 0.4rem;
  padding: 0.55rem 0.65rem;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md, 6px);
  background: var(--surface-soft);
}

.remote-file-upload-progress progress {
  width: 100%;
  height: 0.45rem;
  accent-color: var(--brand);
}

.remote-file-upload-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.55rem;
}

.remote-file-upload-status-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.78rem;
  color: var(--muted);
}
</style>

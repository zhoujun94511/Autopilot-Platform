<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  loading?: boolean;
  uploading?: boolean;
  readonly?: boolean;
  platform?: string;
  canMutate?: boolean;
}>();

const emit = defineEmits<{
  navigate: [path: string];
  refresh: [];
  mkdir: [];
  upload: [];
  home: [];
  up: [];
}>();

const pathInput = defineModel<string>("pathInput", { required: true });

const isIos = computed(() => props.platform === "ios");
const homeLabel = computed(() => (isIos.value ? "根目录" : "主页"));
const busy = computed(() => Boolean(props.loading || props.uploading));
</script>

<template>
  <div class="remote-file-toolbar">
    <div class="remote-file-toolbar-row">
      <button type="button" class="small" :disabled="busy" @click="emit('up')">
        上级
      </button>
      <button type="button" class="small" :disabled="busy" @click="emit('home')">
        {{ homeLabel }}
      </button>
      <input
        v-model="pathInput"
        class="remote-file-path-input"
        :placeholder="isIos ? '例如 . 或 Downloads' : '/sdcard'"
        :disabled="busy"
        aria-label="当前路径"
        @keydown.enter="emit('navigate', pathInput)"
      />
      <button
        type="button"
        class="small"
        :disabled="busy"
        title="刷新"
        @click="emit('refresh')"
      >
        刷新
      </button>
    </div>
    <div v-if="!readonly" class="remote-file-toolbar-row remote-file-toolbar-actions">
      <button
        v-if="canMutate"
        type="button"
        class="small"
        :disabled="busy"
        @click="emit('mkdir')"
      >
        新建目录
      </button>
      <button
        type="button"
        class="small primary"
        :disabled="busy"
        @click="emit('upload')"
      >
        上传文件
      </button>
    </div>
  </div>
</template>

<style scoped>
.remote-file-toolbar {
  display: grid;
  gap: 0.45rem;
}

.remote-file-toolbar-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: center;
}

.remote-file-path-input {
  flex: 1;
  min-width: 0;
}

.remote-file-toolbar-actions {
  justify-content: space-between;
}

.remote-file-toolbar-actions .primary {
  margin-left: auto;
}
</style>

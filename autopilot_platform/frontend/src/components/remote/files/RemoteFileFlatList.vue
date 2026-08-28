<script setup lang="ts">
import { canPreviewFile } from "../../../composables/remote/files/filePreviewKind";
import { formatFileSize } from "../../../composables/remote/files/formatFileSize";
import type { RemoteFileEntry } from "../../../composables/remote/useRemoteFiles";

defineProps<{
  entries: RemoteFileEntry[];
  loading?: boolean;
  readonly?: boolean;
  canMutate?: boolean;
}>();

const emit = defineEmits<{
  open: [entry: RemoteFileEntry];
  download: [entry: RemoteFileEntry];
  preview: [entry: RemoteFileEntry];
  rename: [entry: RemoteFileEntry];
  remove: [entry: RemoteFileEntry];
}>();
</script>

<template>
  <div class="remote-file-flat-list">
    <div
      v-for="entry in entries"
      :key="entry.path"
      class="remote-file-row"
      @dblclick="emit('open', entry)"
    >
      <span class="remote-file-kind">{{ entry.is_dir ? "📁" : "📄" }}</span>
      <span class="remote-file-name" :title="entry.path">{{ entry.name }}</span>
      <span class="remote-file-size muted">
        {{ entry.is_dir ? "—" : formatFileSize(entry.size) }}
      </span>
      <span class="remote-file-row-actions">
        <button
          v-if="!entry.is_dir && canPreviewFile(entry.name)"
          type="button"
          class="small"
          @click.stop="emit('preview', entry)"
        >
          预览
        </button>
        <button type="button" class="small" @click.stop="emit('open', entry)">
          {{ entry.is_dir ? "打开" : "下载" }}
        </button>
        <button
          v-if="canMutate"
          type="button"
          class="small"
          @click.stop="emit('rename', entry)"
        >
          重命名
        </button>
        <button
          v-if="canMutate"
          type="button"
          class="small danger"
          @click.stop="emit('remove', entry)"
        >
          删除
        </button>
      </span>
    </div>
    <p v-if="!entries.length && !loading" class="muted remote-file-empty">目录为空</p>
  </div>
</template>

<style scoped>
.remote-file-flat-list {
  display: grid;
  gap: 0.35rem;
}

.remote-file-kind {
  flex-shrink: 0;
}

.remote-file-size {
  flex-shrink: 0;
  font-size: 0.78rem;
  min-width: 4.5rem;
  text-align: right;
}

.remote-file-empty {
  margin: 0;
  font-size: 0.82rem;
}
</style>

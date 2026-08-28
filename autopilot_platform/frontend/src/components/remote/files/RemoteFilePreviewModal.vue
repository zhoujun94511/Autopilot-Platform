<script setup lang="ts">
import { onMounted, onUnmounted, reactive, watch } from "vue";
import {
  filePreviewKind,
  TEXT_PREVIEW_LIMIT,
  type FilePreviewKind,
} from "../../../composables/remote/files/filePreviewKind";
import { formatFileSize } from "../../../composables/remote/files/formatFileSize";

export type RemoteFilePreviewTarget = {
  name: string;
  path: string;
  size?: number;
};

const props = defineProps<{
  open: boolean;
  target: RemoteFilePreviewTarget | null;
  fetchPreviewBlob: (target: RemoteFilePreviewTarget) => Promise<Blob>;
}>();

const emit = defineEmits<{ close: []; download: [target: RemoteFilePreviewTarget] }>();

const state = reactive({
  kind: null as FilePreviewKind,
  loading: false,
  error: "",
  text: "",
  url: "",
});

function resetState() {
  if (state.url) URL.revokeObjectURL(state.url);
  state.kind = null;
  state.loading = false;
  state.error = "";
  state.text = "";
  state.url = "";
}

async function loadPreview() {
  resetState();
  const target = props.target;
  if (!target) return;

  const kind = filePreviewKind(target.name);
  state.kind = kind;
  if (!kind) {
    state.error = "此类型不支持内联预览";
    return;
  }

  state.loading = true;
  try {
    const blob = await props.fetchPreviewBlob(target);
    if (kind === "text") {
      if (blob.size > TEXT_PREVIEW_LIMIT) {
        const slice = blob.slice(0, TEXT_PREVIEW_LIMIT);
        state.text = `${await slice.text()}\n\n— 预览已截断（${formatFileSize(blob.size)}）—`;
      } else {
        state.text = await blob.text();
      }
    } else {
      state.url = URL.createObjectURL(blob);
    }
  } catch (cause) {
    state.error = cause instanceof Error ? cause.message : String(cause);
  } finally {
    state.loading = false;
  }
}

watch(
  () => [props.open, props.target?.path] as const,
  ([open]) => {
    if (open && props.target) void loadPreview();
    else resetState();
  },
);

function onKey(event: KeyboardEvent) {
  if (props.open && event.key === "Escape") emit("close");
}

onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => {
  window.removeEventListener("keydown", onKey);
  resetState();
});
</script>

<template>
  <Teleport to="body">
    <Transition name="remote-file-preview-fade">
      <div
        v-if="open && target"
        class="remote-file-preview-overlay"
        @click.self="emit('close')"
      >
        <div class="remote-file-preview-modal" role="dialog" aria-modal="true">
          <header class="remote-file-preview-head">
            <strong class="remote-file-preview-name" :title="target.path">
              {{ target.name }}
            </strong>
            <div class="remote-file-preview-actions">
              <button
                type="button"
                class="remote-file-preview-icon-btn"
                title="下载"
                @click="emit('download', target)"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path d="M12 3v12" />
                  <path d="m7 12 5 5 5-5" />
                  <path d="M5 21h14" />
                </svg>
              </button>
              <button
                type="button"
                class="remote-file-preview-icon-btn"
                title="关闭"
                @click="emit('close')"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <line x1="6" y1="6" x2="18" y2="18" />
                  <line x1="18" y1="6" x2="6" y2="18" />
                </svg>
              </button>
            </div>
          </header>
          <div class="remote-file-preview-body" :class="`kind-${state.kind || 'unsupported'}`">
            <p v-if="state.error" class="bad">{{ state.error }}</p>
            <p v-else-if="state.loading" class="muted remote-file-preview-loading">
              正在拉取文件…
            </p>
            <pre v-else-if="state.kind === 'text'" class="remote-file-preview-text">{{
              state.text
            }}</pre>
            <img
              v-else-if="state.kind === 'image'"
              :src="state.url"
              :alt="target.name"
            />
            <video
              v-else-if="state.kind === 'video'"
              :src="state.url"
              controls
              autoplay
            />
            <audio
              v-else-if="state.kind === 'audio'"
              :src="state.url"
              controls
              autoplay
            />
            <iframe v-else-if="state.kind === 'pdf'" :src="state.url" :title="target.name" />
            <div v-else class="remote-file-preview-unsupported">
              <p>此类型不支持内联预览</p>
              <button type="button" class="small primary" @click="emit('download', target)">
                下载文件
              </button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.remote-file-preview-overlay {
  position: fixed;
  inset: 0;
  /* 高于远控 ApModal (10001)，低于 stacked 确认框 (10003) */
  z-index: 10002;
  display: grid;
  place-items: center;
  padding: 1.5rem;
  background: rgba(2, 6, 23, 0.66);
  backdrop-filter: blur(3px);
}

.remote-file-preview-modal {
  display: flex;
  flex-direction: column;
  width: min(92vw, 1100px);
  max-height: 88vh;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface-primary);
  box-shadow: var(--shadow-lg, 0 16px 48px rgba(0, 0, 0, 0.35));
}

.remote-file-preview-head {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--line-soft);
}

.remote-file-preview-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.9rem;
}

.remote-file-preview-actions {
  display: flex;
  gap: 0.35rem;
}

.remote-file-preview-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  padding: 0;
  border: 1px solid var(--line-soft);
  border-radius: 8px;
  color: var(--muted);
  background: var(--surface-soft);
  cursor: pointer;
}

.remote-file-preview-icon-btn:hover {
  color: var(--text);
  border-color: var(--line);
}

.remote-file-preview-icon-btn svg {
  width: 16px;
  height: 16px;
}

.remote-file-preview-body {
  overflow: auto;
  padding: 1rem;
  background: var(--surface-soft);
}

.remote-file-preview-loading {
  margin: 0;
}

.remote-file-preview-text {
  margin: 0;
  max-height: calc(88vh - 120px);
  overflow: auto;
  font-size: 0.82rem;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}

.remote-file-preview-body img,
.remote-file-preview-body video {
  display: block;
  max-width: 100%;
  max-height: calc(88vh - 120px);
  margin: 0 auto;
  border-radius: 8px;
}

.remote-file-preview-body audio {
  width: min(80vw, 460px);
}

.remote-file-preview-body iframe {
  width: min(88vw, 900px);
  height: calc(88vh - 120px);
  border: none;
  border-radius: 8px;
  background: #fff;
}

.remote-file-preview-unsupported {
  display: grid;
  gap: 0.75rem;
  justify-items: start;
}

.remote-file-preview-fade-enter-active,
.remote-file-preview-fade-leave-active {
  transition: opacity 0.18s ease;
}

.remote-file-preview-fade-enter-from,
.remote-file-preview-fade-leave-to {
  opacity: 0;
}
</style>

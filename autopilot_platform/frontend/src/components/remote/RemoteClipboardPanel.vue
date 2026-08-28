<script setup lang="ts">
import { useRemoteClipboard } from "../../composables/remote/useRemoteClipboard";

defineProps<{ readonly?: boolean }>();

const {
  text,
  loading,
  error,
  success,
  activeAction,
  charCount,
  commandReady,
  readDevice,
  writeDevice,
  readBrowser,
  writeBrowser,
} = useRemoteClipboard();

function isBusy(action: typeof activeAction.value) {
  return loading.value && activeAction.value === action;
}
</script>

<template>
  <section class="remote-tool-panel remote-clipboard-panel">
    <header class="remote-clipboard-head">
      <div>
        <h3>剪贴板</h3>
        <p class="remote-clipboard-hint">
          文本框是中转区。下方<strong>手机</strong>组经远控读写手机剪贴板，<strong>本机</strong>组读写电脑 Ctrl+C/V。
          <span v-if="!commandReady" class="remote-clipboard-warn">手机写入需等待可靠通道就绪。</span>
        </p>
      </div>
    </header>

    <label class="remote-clipboard-editor-label" for="remote-clipboard-text">
      文本内容
      <span class="remote-clipboard-count">{{ charCount }} 字</span>
    </label>
    <textarea
      id="remote-clipboard-text"
      v-model="text"
      rows="6"
      placeholder="在此编辑，或从手机 / 本机剪贴板读取"
      :readonly="readonly"
      :disabled="loading"
    />

    <div class="remote-clipboard-groups">
      <fieldset class="remote-clipboard-group" :disabled="loading">
        <legend>手机</legend>
        <div class="remote-clipboard-action-grid remote-clipboard-action-grid--phone">
          <button
            type="button"
            class="small remote-clipboard-btn-full"
            :disabled="!commandReady || loading"
            :aria-busy="isBusy('read-device')"
            @click="readDevice"
          >
            {{ isBusy("read-device") ? "读取中…" : "读取手机剪贴板" }}
          </button>
          <button
            v-if="!readonly"
            type="button"
            class="small primary"
            :disabled="!commandReady || loading || !text.length"
            :aria-busy="isBusy('write-device')"
            @click="writeDevice(false)"
          >
            {{ isBusy("write-device") ? "写入中…" : "写入手机" }}
          </button>
          <button
            v-if="!readonly"
            type="button"
            class="small primary remote-clipboard-btn-accent"
            :disabled="!commandReady || loading || !text.length"
            :aria-busy="isBusy('write-paste')"
            title="写入手机剪贴板并在当前焦点处粘贴"
            @click="writeDevice(true)"
          >
            {{ isBusy("write-paste") ? "粘贴中…" : "写入并粘贴" }}
          </button>
        </div>
      </fieldset>

      <fieldset class="remote-clipboard-group" :disabled="loading">
        <legend>本机（电脑）</legend>
        <p class="remote-clipboard-side-hint">
          读写你这台电脑上的 Ctrl+C / Ctrl+V 剪贴板（Chrome 可能需允许权限）。
        </p>
        <div class="remote-clipboard-action-grid remote-clipboard-action-grid--host">
          <button
            type="button"
            class="small"
            :disabled="loading"
            :aria-busy="isBusy('read-browser')"
            @click="readBrowser"
          >
            {{ isBusy("read-browser") ? "读取中…" : "读取本机剪贴板" }}
          </button>
          <button
            type="button"
            class="small"
            :disabled="loading || !text.length"
            :aria-busy="isBusy('write-browser')"
            @click="writeBrowser"
          >
            {{ isBusy("write-browser") ? "复制中…" : "复制到本机" }}
          </button>
        </div>
      </fieldset>
    </div>

    <p v-if="success" class="remote-clipboard-feedback ok" role="status">{{ success }}</p>
    <p v-if="error" class="remote-clipboard-feedback bad" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.remote-clipboard-head {
  display: block;
}

.remote-clipboard-hint {
  margin: 0.25rem 0 0;
  font-size: 0.78rem;
  line-height: 1.45;
  color: var(--muted);
}

.remote-clipboard-warn {
  color: var(--warning-soft-fg, var(--bad));
}

.remote-clipboard-editor-label {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--muted);
}

.remote-clipboard-count {
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}

.remote-clipboard-groups {
  display: grid;
  gap: 0.75rem;
}

.remote-clipboard-group {
  margin: 0;
  padding: 0.65rem 0.7rem 0.75rem;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md, 6px);
  background: var(--surface-soft);
}

.remote-clipboard-group:disabled {
  opacity: 0.72;
}

.remote-clipboard-group legend {
  padding: 0 0.25rem;
  font-size: 0.74rem;
  font-weight: 700;
  color: var(--text-secondary);
}

.remote-clipboard-side-hint {
  margin: 0 0 0.5rem;
  font-size: 0.74rem;
  line-height: 1.45;
  color: var(--muted);
}

.remote-clipboard-action-grid {
  display: grid;
  gap: 0.45rem;
}

.remote-clipboard-action-grid--phone {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.remote-clipboard-action-grid--phone .remote-clipboard-btn-full {
  grid-column: 1 / -1;
}

.remote-clipboard-action-grid--host {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.remote-clipboard-action-grid .small {
  width: 100%;
  justify-content: center;
  text-align: center;
  white-space: nowrap;
}

.remote-clipboard-btn-accent {
  box-shadow: inset 0 0 0 1px rgb(255 255 255 / 12%);
}

.remote-clipboard-feedback {
  margin: 0;
  padding: 0.5rem 0.65rem;
  border-radius: var(--radius-md, 6px);
  font-size: 0.82rem;
  line-height: 1.45;
}

.remote-clipboard-feedback.ok {
  color: var(--ok-soft-fg);
  background: var(--ok-soft-bg);
  border: 1px solid var(--ok-soft-border);
}

.remote-clipboard-feedback.bad {
  color: var(--danger-soft-fg);
  background: var(--danger-soft-bg);
  border: 1px solid var(--danger-soft-border);
}
</style>

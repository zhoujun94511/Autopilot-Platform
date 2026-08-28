<script setup lang="ts">
defineProps<{ visible?: boolean }>();
</script>

<template>
  <div v-if="visible" class="remote-file-drop-overlay" aria-hidden="true">
    <div class="remote-file-drop-card">
      <strong>松开以上传文件</strong>
      <p class="muted">将文件拖放到此区域</p>
    </div>
  </div>
</template>

<style scoped>
.remote-file-drop-overlay {
  position: absolute;
  inset: 0;
  z-index: 5;
  display: grid;
  place-items: center;
  padding: 1rem;
  background: rgba(15, 23, 42, 0.55);
  border-radius: var(--radius-md, 6px);
  pointer-events: none;
}

.remote-file-drop-card {
  display: grid;
  gap: 0.35rem;
  padding: 1rem 1.25rem;
  text-align: center;
  border: 2px dashed var(--brand, var(--accent-text));
  border-radius: var(--radius-lg, 8px);
  background: var(--surface-primary);
}

.remote-file-drop-card p {
  margin: 0;
  font-size: 0.82rem;
}
</style>

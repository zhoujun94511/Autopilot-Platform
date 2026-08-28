<script setup lang="ts">
import { useCapabilities } from "../../composables/useCapabilities";

const caps = useCapabilities();
</script>

<template>
  <div v-if="caps.isProjectViewer" class="alert-banner info" role="status">
    <strong>当前为项目只读成员</strong>
    <span>已选中项目，但角色为 viewer：可查看内容，无法生成、导入或删除。</span>
  </div>
</template>

<style scoped>
.alert-banner {
  margin: 0 0 0.75rem;
  padding: 0.65rem 0.85rem;
  border-radius: 8px;
  font-size: 0.85rem;
  line-height: 1.4;
}
.alert-banner.info {
  border: 1px solid var(--line);
  background: var(--surface-soft);
  color: var(--muted);
}
</style>

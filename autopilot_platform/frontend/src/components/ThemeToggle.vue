<script setup lang="ts">
import { Sun, Moon } from "lucide-vue-next";
import { useTheme } from "../composables/useTheme";

const { theme, toggleTheme } = useTheme();
</script>

<template>
  <button
    type="button"
    class="theme-toggle"
    :title="theme === 'dark' ? '切换到浅色主题' : '切换到深色主题'"
    :aria-label="theme === 'dark' ? '切换到浅色主题' : '切换到深色主题'"
    @click="toggleTheme"
  >
    <Sun v-if="theme === 'dark'" :size="16" class="theme-icon" aria-hidden="true" />
    <Moon v-else :size="16" class="theme-icon" aria-hidden="true" />
  </button>
</template>

<style scoped>
.theme-toggle {
  width: 32px;
  height: 32px;
  padding: 0;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--vben-fg);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background-color 0.15s ease, color 0.15s ease;
  flex-shrink: 0;
}

.theme-toggle:hover {
  background: var(--vben-bg-hover);
  color: var(--vben-primary);
}

.theme-toggle:focus-visible {
  outline: 2px solid var(--vben-primary);
  outline-offset: 2px;
}

.theme-icon {
  display: block;
}
</style>

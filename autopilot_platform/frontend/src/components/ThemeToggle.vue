<script setup lang="ts">
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
    <!-- 当前深色：显示太阳（点一下切浅色） -->
    <svg
      v-if="theme === 'dark'"
      class="theme-icon"
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="4" stroke="currentColor" stroke-width="2" />
      <path
        d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
      />
    </svg>
    <!-- 当前浅色：显示月亮 -->
    <svg
      v-else
      class="theme-icon"
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M21 14.5A8.5 8.5 0 0 1 9.5 3 7 7 0 1 0 21 14.5z"
        stroke="currentColor"
        stroke-width="2"
        stroke-linejoin="round"
      />
    </svg>
  </button>
</template>

<style scoped>
.theme-toggle {
  width: 32px;
  height: 32px;
  padding: 0;
  border-radius: 6px;
  border: 1px solid var(--line);
  background: var(--control-bg);
  color: var(--text);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: var(--transition);
  flex-shrink: 0;
}

.theme-toggle:hover {
  border-color: var(--accent);
  background: var(--brand-soft);
  color: var(--accent-text);
}

.theme-toggle:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.theme-icon {
  display: block;
}
</style>

/**
 * Web 管理台主题：dark / light，持久化到 localStorage，通过 documentElement data-theme 驱动 CSS 变量。
 */
import { computed, ref } from "vue";

export type ThemeMode = "dark" | "light";

const STORAGE_KEY = "autopilot-mc-theme";

const theme = ref<ThemeMode>(readStored());

function readStored(): ThemeMode {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "light" || raw === "dark") return raw;
  } catch {
    /* ignore */
  }
  return "dark";
}

/** 在 Vue 挂载前调用，减少闪白/闪黑 */
export function applyStoredTheme(): ThemeMode {
  const mode = readStored();
  applyTheme(mode);
  theme.value = mode;
  return mode;
}

export function applyTheme(mode: ThemeMode) {
  const root = document.documentElement;
  root.setAttribute("data-theme", mode);
  root.style.colorScheme = mode;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    meta.setAttribute("content", mode === "light" ? "#f0f2f5" : "#0e1116");
  }
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    /* ignore */
  }
}

export function useTheme() {
  const isDark = computed(() => theme.value === "dark");
  const isLight = computed(() => theme.value === "light");

  function setTheme(mode: ThemeMode) {
    theme.value = mode;
    applyTheme(mode);
  }

  function toggleTheme() {
    setTheme(theme.value === "dark" ? "light" : "dark");
  }

  return {
    theme,
    isDark,
    isLight,
    setTheme,
    toggleTheme,
  };
}

<script setup lang="ts">
import { ref } from "vue";

defineProps<{
  platform: string;
  readonly?: boolean;
  drawerOpen?: boolean;
}>();

const emit = defineEmits<{
  androidKey: [code: number];
  androidAction: [action: "rotate" | "expandNotification" | "expandSettings" | "collapse"];
  androidSwipe: [direction: "up" | "down" | "left" | "right"];
  iosHome: [];
  iosVolume: [name: "volumeup" | "volumedown"];
  iosSwipe: [direction: "up" | "down" | "left" | "right"];
  toggleDrawer: [];
}>();

const dpadOpen = ref(false);

function closeDpad() {
  dpadOpen.value = false;
}

function dpad(dir: "up" | "down" | "left" | "right", ios: boolean) {
  if (ios) emit("iosSwipe", dir);
  else emit("androidSwipe", dir);
}

function onToggleDrawer() {
  dpadOpen.value = false;
  emit("toggleDrawer");
}
</script>

<template>
  <nav class="remote-toolbar" aria-label="设备按键">
    <div v-if="platform === 'ios'" class="remote-toolbar-row">
      <button type="button" class="ap-btn ghost" :disabled="readonly" @click="emit('iosHome')">
        Home
      </button>
      <button
        type="button"
        class="ap-btn ghost"
        :class="{ active: dpadOpen }"
        :disabled="readonly"
        @click="dpadOpen = !dpadOpen"
      >
        方向键
      </button>
      <span class="remote-toolbar-sep" aria-hidden="true" />
      <button
        type="button"
        class="ap-btn ghost"
        :disabled="readonly"
        @click="emit('iosVolume', 'volumeup')"
      >
        Vol+
      </button>
      <button
        type="button"
        class="ap-btn ghost"
        :disabled="readonly"
        @click="emit('iosVolume', 'volumedown')"
      >
        Vol-
      </button>
      <span class="remote-toolbar-sep" aria-hidden="true" />
      <button
        type="button"
        class="ap-btn ghost"
        :class="{ active: drawerOpen }"
        @click="onToggleDrawer"
      >
        更多
      </button>
    </div>

    <div v-else class="remote-toolbar-row">
      <button type="button" class="ap-btn ghost" :disabled="readonly" @click="emit('androidKey', 4)">
        返回
      </button>
      <button type="button" class="ap-btn ghost" :disabled="readonly" @click="emit('androidKey', 3)">
        Home
      </button>
      <button type="button" class="ap-btn ghost" :disabled="readonly" @click="emit('androidKey', 187)">
        多任务
      </button>
      <span class="remote-toolbar-sep" aria-hidden="true" />
      <button
        type="button"
        class="ap-btn ghost"
        :disabled="readonly"
        @click="emit('androidAction', 'rotate')"
      >
        旋转
      </button>
      <button
        type="button"
        class="ap-btn ghost"
        :class="{ active: dpadOpen }"
        :disabled="readonly"
        @click="dpadOpen = !dpadOpen"
      >
        方向键
      </button>
      <span class="remote-toolbar-sep" aria-hidden="true" />
      <button
        type="button"
        class="ap-btn ghost"
        :class="{ active: drawerOpen }"
        @click="onToggleDrawer"
      >
        更多
      </button>
    </div>

    <div v-if="dpadOpen" class="remote-dpad-wrap">
      <div class="remote-dpad" role="group" aria-label="方向键">
        <button type="button" class="dpad-key up" :disabled="readonly" @click="dpad('up', platform === 'ios')">
          ↑
        </button>
        <button type="button" class="dpad-key left" :disabled="readonly" @click="dpad('left', platform === 'ios')">
          ←
        </button>
        <button
          type="button"
          class="dpad-key center dpad-close"
          :disabled="readonly"
          aria-label="关闭方向键"
          title="关闭"
          @click="closeDpad"
        >
          ×
        </button>
        <button type="button" class="dpad-key right" :disabled="readonly" @click="dpad('right', platform === 'ios')">
          →
        </button>
        <button type="button" class="dpad-key down" :disabled="readonly" @click="dpad('down', platform === 'ios')">
          ↓
        </button>
      </div>
    </div>
  </nav>
</template>

<style scoped>
.remote-toolbar {
  position: relative;
  display: grid;
  gap: 0.55rem;
  padding-top: 0.75rem;
  flex-shrink: 0;
}

.remote-toolbar-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: center;
}

.remote-toolbar-sep {
  width: 1px;
  height: 1.25rem;
  margin: 0 0.15rem;
  background: var(--line-soft);
}

.ap-btn.ghost.active {
  color: var(--accent-text);
  border-color: var(--info-soft-border);
  background: var(--action-selected);
}

.remote-dpad-wrap {
  position: absolute;
  right: 0;
  bottom: calc(100% + 0.35rem);
  z-index: 2;
}

.remote-dpad {
  display: grid;
  grid-template-columns: repeat(3, 2.4rem);
  grid-template-rows: repeat(3, 2.4rem);
  gap: 0.25rem;
  width: fit-content;
  padding: 0.45rem;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-lg, 8px);
  background: var(--surface-secondary);
  box-shadow: 0 8px 24px rgb(0 0 0 / 18%);
}

.dpad-key {
  display: grid;
  place-items: center;
  border: 1px solid var(--btn-border);
  border-radius: var(--radius-md, 6px);
  font-size: 1rem;
  font-weight: 700;
  color: var(--btn-fg);
  background: var(--btn-bg);
  cursor: pointer;
}

.dpad-key:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.dpad-key.up { grid-column: 2; grid-row: 1; }
.dpad-key.left { grid-column: 1; grid-row: 2; }
.dpad-key.center { grid-column: 2; grid-row: 2; }
.dpad-key.right { grid-column: 3; grid-row: 2; }
.dpad-key.down { grid-column: 2; grid-row: 3; }

.dpad-close {
  font-size: 1.15rem;
  line-height: 1;
  color: var(--muted);
}

.dpad-key:not(:disabled):hover {
  background: var(--btn-bg-hover);
}

.dpad-close:not(:disabled):hover {
  color: var(--fg);
  background: var(--danger-soft-bg, var(--btn-bg-hover));
}
</style>

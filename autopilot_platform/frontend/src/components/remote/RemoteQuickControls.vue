<script setup lang="ts">
defineProps<{ readonly?: boolean }>();

const emit = defineEmits<{
  androidKey: [code: number];
  androidPower: [mode: 0 | 2];
  androidAction: [action: "rotate" | "expandNotification" | "expandSettings" | "collapse"];
}>();
</script>

<template>
  <section class="remote-tool-panel remote-quick-controls">
    <header>
      <h3>快捷控制</h3>
    </header>
    <p class="muted">对齐 WebAppFlaskscrcpy 侧栏快开：电源、音量、通知、亮灭屏等。</p>
    <div class="remote-tool-actions">
      <button type="button" class="small" :disabled="readonly" @click="emit('androidKey', 26)">
        电源
      </button>
      <button type="button" class="small" :disabled="readonly" @click="emit('androidKey', 24)">
        Vol+
      </button>
      <button type="button" class="small" :disabled="readonly" @click="emit('androidKey', 25)">
        Vol-
      </button>
      <button type="button" class="small" :disabled="readonly" @click="emit('androidKey', 83)">
        通知栏
      </button>
      <button type="button" class="small" :disabled="readonly" @click="emit('androidKey', 176)">
        设置
      </button>
      <button type="button" class="small" :disabled="readonly" @click="emit('androidKey', 82)">
        菜单
      </button>
      <button type="button" class="small" :disabled="readonly" @click="emit('androidPower', 2)">
        亮屏
      </button>
      <button type="button" class="small" :disabled="readonly" @click="emit('androidPower', 0)">
        灭屏
      </button>
      <button
        type="button"
        class="small"
        :disabled="readonly"
        @click="emit('androidAction', 'expandNotification')"
      >
        展开通知
      </button>
      <button
        type="button"
        class="small"
        :disabled="readonly"
        @click="emit('androidAction', 'expandSettings')"
      >
        快速设置
      </button>
      <button
        type="button"
        class="small"
        :disabled="readonly"
        @click="emit('androidAction', 'collapse')"
      >
        收起面板
      </button>
    </div>
  </section>
</template>

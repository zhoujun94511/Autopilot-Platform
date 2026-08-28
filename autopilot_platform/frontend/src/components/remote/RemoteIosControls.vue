<script setup lang="ts">
import { onMounted, reactive, ref, watch } from "vue";
import { notify } from "../../composables/useNotify";
import {
  remoteCommandReady,
  sendRemoteCommand,
} from "../../composables/remote/useRemoteCommands";

defineProps<{ readonly?: boolean }>();

const FEATURES = [
  ["assistivetouch", "辅助触控"],
  ["voiceover", "旁白"],
  ["zoom", "缩放"],
] as const;

const a11y = reactive<Record<string, boolean | null>>({
  assistivetouch: null,
  voiceover: null,
  zoom: null,
});
const a11yBusy = ref("");
const text = ref("");
const alertPresent = ref(false);
const alertText = ref("");
const alertChecked = ref(false);
const shot = ref("");
const error = ref("");
const busy = ref("");

watch(remoteCommandReady, (ready) => {
  if (ready) void refreshA11y();
});

onMounted(() => {
  if (remoteCommandReady.value) void refreshA11y();
});

function labelOf(feature: string): string {
  return FEATURES.find(([id]) => id === feature)?.[1] || feature;
}

async function call(command: Record<string, unknown>, timeoutMs = 20_000) {
  error.value = "";
  return sendRemoteCommand(command, timeoutMs);
}

async function refreshA11y() {
  if (!remoteCommandReady.value) return;
  await Promise.all(
    FEATURES.map(async ([feature]) => {
      try {
        const result = await call({ t: "accessibility", feature, action: "get" });
        a11y[feature] = typeof result.enabled === "boolean" ? result.enabled : null;
      } catch {
        /* 查询失败不挡开关 */
      }
    }),
  );
}

function reportError(exc: unknown) {
  error.value = exc instanceof Error ? exc.message : String(exc);
  notify(error.value, "error");
}

async function toggleA11y(feature: string) {
  a11yBusy.value = feature;
  try {
    const result = await call({ t: "accessibility", feature, action: "toggle" });
    if (typeof result.enabled === "boolean") a11y[feature] = result.enabled;
    const state = result.enabled === true ? "开" : result.enabled === false ? "关" : "已切换";
    notify(`${labelOf(feature)} · ${state}`, "success");
  } catch (exc) {
    reportError(exc);
  } finally {
    a11yBusy.value = "";
  }
}

async function checkAlert() {
  busy.value = "alert";
  try {
    const result = await call({ t: "alert.get" });
    alertPresent.value = Boolean(result.present);
    alertText.value = String(result.text || "");
    alertChecked.value = true;
  } catch (exc) {
    reportError(exc);
  } finally {
    busy.value = "";
  }
}

async function doAlert(action: "accept" | "dismiss") {
  busy.value = action;
  try {
    await call({ t: `alert.${action}` });
    await checkAlert();
  } catch (exc) {
    reportError(exc);
  } finally {
    busy.value = "";
  }
}

async function sendText() {
  const payload = text.value;
  if (!payload) return;
  busy.value = "text";
  try {
    await call({ t: "input.text", text: payload });
    text.value = "";
    notify("已发送文本", "success");
  } catch (exc) {
    reportError(exc);
  } finally {
    busy.value = "";
  }
}

async function sendKey(key: "backspace" | "enter" | "space") {
  busy.value = key;
  try {
    await call({ t: "input.key", key });
  } catch (exc) {
    reportError(exc);
  } finally {
    busy.value = "";
  }
}

async function takeShot() {
  busy.value = "shot";
  try {
    const result = await call({ t: "device.screenshot" }, 30_000);
    shot.value = String(result.image || "");
    if (shot.value) notify("截图已保存到控制页", "success");
  } catch (exc) {
    reportError(exc);
  } finally {
    busy.value = "";
  }
}

function downloadShot() {
  if (!shot.value) return;
  const link = document.createElement("a");
  link.href = shot.value;
  link.download = `ios-screenshot-${Date.now()}.png`;
  link.click();
}
</script>

<template>
  <section class="remote-tool-panel remote-ios-controls">
    <header>
      <h3>控制</h3>
    </header>
    <p class="muted">对齐 WebAppFlaskauto-iOS：无障碍走 go-ios，弹窗/键入/截图走 WDA。</p>

    <label class="muted">无障碍</label>
    <div class="remote-tool-actions">
      <button
        v-for="[id, label] in FEATURES"
        :key="id"
        type="button"
        class="small"
        :class="{ primary: a11y[id] === true }"
        :disabled="readonly || Boolean(a11yBusy) || !remoteCommandReady"
        @click="toggleA11y(id)"
      >
        {{ a11yBusy === id ? "切换中…" : label }}{{ a11y[id] === true ? " · 开" : a11y[id] === false ? " · 关" : "" }}
      </button>
    </div>

    <label class="muted">系统弹窗</label>
    <div class="remote-tool-actions">
      <button
        type="button"
        class="small"
        :disabled="readonly || Boolean(busy) || !remoteCommandReady"
        @click="checkAlert"
      >
        {{ busy === "alert" ? "检查中…" : "检查" }}
      </button>
      <button
        v-if="alertPresent"
        type="button"
        class="small primary"
        :disabled="readonly || Boolean(busy)"
        @click="doAlert('accept')"
      >
        接受
      </button>
      <button
        v-if="alertPresent"
        type="button"
        class="small"
        :disabled="readonly || Boolean(busy)"
        @click="doAlert('dismiss')"
      >
        关闭
      </button>
    </div>
    <p v-if="alertPresent" class="muted">{{ alertText || "有系统弹窗" }}</p>
    <p v-else-if="alertChecked" class="muted">当前没有系统弹窗</p>

    <label class="muted">文本输入</label>
    <div class="remote-tool-actions">
      <input
        v-model="text"
        type="text"
        placeholder="输入后发送到当前焦点"
        :disabled="readonly || Boolean(busy)"
        @keyup.enter="sendText"
      />
      <button
        type="button"
        class="small primary"
        :disabled="readonly || !text || Boolean(busy) || !remoteCommandReady"
        @click="sendText"
      >
        发送
      </button>
    </div>
    <div class="remote-tool-actions">
      <button
        type="button"
        class="small"
        :disabled="readonly || Boolean(busy) || !remoteCommandReady"
        title="退格"
        @click="sendKey('backspace')"
      >
        ⌫
      </button>
      <button
        type="button"
        class="small"
        :disabled="readonly || Boolean(busy) || !remoteCommandReady"
        @click="sendKey('enter')"
      >
        回车
      </button>
      <button
        type="button"
        class="small"
        :disabled="readonly || Boolean(busy) || !remoteCommandReady"
        @click="sendKey('space')"
      >
        空格
      </button>
    </div>

    <label class="muted">截图</label>
    <div class="remote-tool-actions">
      <button
        type="button"
        class="small"
        :disabled="readonly || Boolean(busy) || !remoteCommandReady"
        @click="takeShot"
      >
        {{ busy === "shot" ? "截图中…" : "截图" }}
      </button>
      <button v-if="shot" type="button" class="small" @click="downloadShot">下载</button>
    </div>
    <img v-if="shot" :src="shot" alt="设备截图" class="ios-shot" />

    <p v-if="error" class="bad">{{ error }}</p>
  </section>
</template>

<style scoped>
.ios-shot {
  width: 100%;
  max-height: 16rem;
  object-fit: contain;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md, 6px);
  background: var(--surface-soft);
}

.remote-ios-controls input[type="text"] {
  flex: 1;
  min-width: 0;
}
</style>

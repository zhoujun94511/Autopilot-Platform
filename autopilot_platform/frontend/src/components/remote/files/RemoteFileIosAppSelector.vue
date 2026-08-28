<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { sendRemoteCommand } from "../../../composables/remote/useRemoteCommands";
import type { RemoteApp } from "../../../composables/remote/useRemoteApps";
import ApSelect from "../../common/ApSelect.vue";

const model = defineModel<string>({ default: "" });

const props = defineProps<{ readonly?: boolean }>();

const apps = ref<RemoteApp[]>([]);
const loading = ref(false);
const error = ref("");

const options = computed(() => [
  { value: "", label: "系统媒体库（默认）" },
  ...apps.value.map((app) => ({
    value: app.package,
    label: `${app.name || app.package} (${app.package})`,
  })),
]);

async function loadApps() {
  loading.value = true;
  error.value = "";
  try {
    const result = await sendRemoteCommand({
      t: "app.list",
      filesharing: true,
    });
    apps.value = Array.isArray(result.packages)
      ? (result.packages as RemoteApp[])
      : [];
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void loadApps();
});
</script>

<template>
  <label class="remote-file-ios-app">
    <span class="remote-file-ios-app-label">App Documents</span>
    <ApSelect
      v-model="model"
      stack
      size="toolbar"
      :disabled="props.readonly || loading"
      :options="options"
      aria-label="App Documents"
    />
    <p class="remote-file-ios-app-hint muted">
      选择开启文件共享的应用后，路径通常以 <code>Documents</code> 为根；留空则浏览设备媒体目录。
    </p>
    <p v-if="error" class="bad">{{ error }}</p>
  </label>
</template>

<style scoped>
.remote-file-ios-app {
  display: grid;
  gap: 0.35rem;
}

.remote-file-ios-app-label {
  font-size: 0.78rem;
  color: var(--muted);
}

.remote-file-ios-app-hint {
  margin: 0;
  font-size: 0.75rem;
  line-height: 1.4;
}

.remote-file-ios-app-hint code {
  font-size: 0.75rem;
}
</style>

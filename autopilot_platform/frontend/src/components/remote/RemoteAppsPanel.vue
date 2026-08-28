<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { confirmDialog, notify } from "../../composables/useNotify";
import { useRemoteApps, type RemoteApp } from "../../composables/remote/useRemoteApps";
import { formatFileSize } from "../../composables/remote/files/formatFileSize";
import ApSelect from "../common/ApSelect.vue";

const props = defineProps<{ readonly?: boolean; platform: string }>();
const manager = useRemoteApps(props.platform);
const { apps, scope, loading, progress, error } = manager;
const installer = ref<HTMLInputElement | null>(null);
const searchQuery = ref("");
const scopeOptions = [
  { value: "third_party", label: "第三方" },
  { value: "system", label: "系统" },
  { value: "all", label: "全部" },
];

const filteredApps = computed(() => {
  const q = searchQuery.value.trim().toLowerCase();
  if (!q) return apps.value;
  return apps.value.filter((app) => {
    const title = appTitle(app).toLowerCase();
    return title.includes(q) || app.package.toLowerCase().includes(q);
  });
});

onMounted(() => void manager.list());

watch(scope, () => {
  void manager.list();
});

function appTitle(app: RemoteApp): string {
  if (app.name && app.name !== app.package) return app.name;
  const parts = app.package.split(".").filter(Boolean);
  return parts[parts.length - 1] || app.package;
}

function appAvatar(app: RemoteApp): string {
  const ch = appTitle(app).charAt(0);
  return (ch || "?").toUpperCase();
}

function appMeta(app: RemoteApp): string {
  const parts: string[] = [];
  if (app.version_name && app.version_name !== "null") {
    parts.push(`v${app.version_name}`);
  } else if (app.version_code) {
    parts.push(`code ${app.version_code}`);
  }
  if (app.size) parts.push(formatFileSize(app.size));
  return parts.length ? parts.join(" · ") : "版本未知";
}

async function launchApp(app: RemoteApp) {
  try {
    await manager.action("app.launch", app.package);
    notify(`已启动 ${appTitle(app)}`, "success");
  } catch (cause) {
    notify(cause instanceof Error ? cause.message : String(cause), "error");
  }
}

async function stopApp(app: RemoteApp) {
  try {
    await manager.action("app.stop", app.package);
    notify(`已停止 ${appTitle(app)}`, "success");
  } catch (cause) {
    notify(cause instanceof Error ? cause.message : String(cause), "error");
  }
}

async function exportApp(app: RemoteApp) {
  try {
    await manager.exportPackage(app);
    notify(`已开始下载 ${appTitle(app)}`, "success");
  } catch (cause) {
    notify(cause instanceof Error ? cause.message : String(cause), "error");
  }
}

async function uninstall(app: RemoteApp) {
  const ok = await confirmDialog(`卸载 ${appTitle(app)}？应用数据可能丢失。`, {
    title: "卸载应用",
    okText: "卸载",
    danger: true,
  });
  if (!ok) return;
  try {
    await manager.action("app.uninstall", app.package);
    notify(`已卸载 ${appTitle(app)}`, "success");
  } catch (cause) {
    notify(cause instanceof Error ? cause.message : String(cause), "error");
  }
}

async function installSelected(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  try {
    await manager.install(file);
    notify("应用安装完成", "success");
  } catch (cause) {
    notify(cause instanceof Error ? cause.message : String(cause), "error");
  } finally {
    input.value = "";
  }
}
</script>

<template>
  <section class="remote-tool-panel remote-apps-panel">
    <header>
      <h3>应用</h3>
      <button type="button" class="small" :disabled="loading" @click="manager.list()">
        刷新
      </button>
    </header>

    <div class="remote-apps-toolbar">
      <ApSelect
        v-model="scope"
        stack
        :options="scopeOptions"
        size="toolbar"
        aria-label="应用范围"
      />
      <input
        v-model="searchQuery"
        class="remote-apps-search"
        type="search"
        placeholder="搜索应用或包名"
        aria-label="搜索应用"
      />
    </div>

    <button
      v-if="!readonly"
      type="button"
      class="remote-apps-install primary"
      @click="installer?.click()"
    >
      安装 {{ platform === "ios" ? "IPA" : "APK / XAPK" }}
    </button>
    <input
      ref="installer"
      hidden
      type="file"
      :accept="platform === 'ios' ? '.ipa' : '.apk,.xapk'"
      @change="installSelected"
    />

    <div class="remote-apps-status">
      <span v-if="loading" class="muted">正在加载应用列表…</span>
      <span v-else-if="!error" class="muted">
        {{ filteredApps.length === apps.length
          ? `共 ${apps.length} 个应用`
          : `${filteredApps.length} / ${apps.length} 个应用` }}
      </span>
      <progress v-if="progress > 0 && progress < 1" :value="progress" max="1" />
    </div>

    <div class="remote-apps-scroll" role="list" aria-label="已安装应用">
      <p v-if="loading && !filteredApps.length" class="remote-apps-empty muted">
        正在加载…
      </p>
      <p v-else-if="!loading && !filteredApps.length" class="remote-apps-empty muted">
        {{ searchQuery.trim() ? "无匹配应用" : "暂无应用" }}
      </p>

      <article
        v-for="app in filteredApps"
        :key="app.package"
        class="remote-app-card"
        role="listitem"
      >
        <div class="remote-app-main">
          <span class="remote-app-avatar" aria-hidden="true">{{ appAvatar(app) }}</span>
          <div class="remote-app-text">
            <div class="remote-app-title-row">
              <strong :title="appTitle(app)">{{ appTitle(app) }}</strong>
              <span
                class="remote-app-badge"
                :class="app.system ? 'system' : 'user'"
              >
                {{ app.system ? "系统" : "三方" }}
              </span>
            </div>
            <code class="remote-app-package" :title="app.package">{{ app.package }}</code>
            <span class="remote-app-meta muted">{{ appMeta(app) }}</span>
          </div>
        </div>

        <div class="remote-app-actions">
          <button type="button" class="small primary" @click="launchApp(app)">启动</button>
          <button type="button" class="small" @click="stopApp(app)">停止</button>
          <button
            v-if="platform !== 'ios'"
            type="button"
            class="small"
            @click="exportApp(app)"
          >
            导出
          </button>
          <button
            v-if="!readonly && !app.system"
            type="button"
            class="small danger"
            @click="uninstall(app)"
          >
            卸载
          </button>
        </div>
      </article>
    </div>

    <p v-if="platform === 'ios'" class="muted remote-apps-footnote">
      iOS 安全模型不允许导出已安装 IPA。
    </p>
    <p v-if="error" class="bad">{{ error }}</p>
  </section>
</template>

<style scoped>
.remote-apps-panel {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.remote-apps-toolbar {
  display: grid;
  grid-template-columns: minmax(0, 7.5rem) minmax(0, 1fr);
  gap: 0.45rem;
  align-items: center;
}

.remote-apps-search {
  min-width: 0;
  min-height: 34px;
  padding: 0 0.55rem;
  border-radius: var(--radius-md, 6px);
  border: 1px solid var(--line-soft);
  background: var(--surface-soft);
  color: var(--text);
  font-size: 0.82rem;
}

.remote-apps-search:focus {
  outline: 2px solid var(--accent-soft-border, rgba(59, 130, 246, 0.45));
  outline-offset: 1px;
}

.remote-apps-install {
  width: 100%;
  justify-content: center;
}

.remote-apps-status {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.remote-apps-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  padding-right: 0.1rem;
}

.remote-apps-empty {
  margin: 1rem 0;
  text-align: center;
}

.remote-app-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 0.55rem;
  padding: 0.65rem;
  border-radius: var(--radius-md, 6px);
  border: 1px solid var(--line-soft);
  background: var(--surface-soft);
}

.remote-app-main {
  display: flex;
  gap: 0.55rem;
  align-items: flex-start;
  min-width: 0;
}

.remote-app-avatar {
  flex-shrink: 0;
  width: 2rem;
  height: 2rem;
  border-radius: 8px;
  display: grid;
  place-items: center;
  font-size: 0.82rem;
  font-weight: 700;
  background: var(--accent-soft-bg, rgba(59, 130, 246, 0.12));
  color: var(--accent, #3b82f6);
}

.remote-app-text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
}

.remote-app-title-row {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  min-width: 0;
}

.remote-app-title-row strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.88rem;
}

.remote-app-badge {
  flex-shrink: 0;
  font-size: 0.62rem;
  line-height: 1.2;
  padding: 0.08rem 0.38rem;
  border-radius: 999px;
  font-weight: 600;
}

.remote-app-badge.system {
  color: var(--muted);
  background: var(--surface-elevated, rgba(128, 128, 128, 0.12));
  border: 1px solid var(--line-soft);
}

.remote-app-badge.user {
  color: var(--accent, #3b82f6);
  background: var(--accent-soft-bg, rgba(59, 130, 246, 0.12));
  border: 1px solid var(--accent-soft-border, rgba(59, 130, 246, 0.25));
}

.remote-app-package {
  display: block;
  font-size: 0.72rem;
  line-height: 1.35;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.remote-app-meta {
  font-size: 0.72rem;
}

.remote-app-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.3rem;
}

.remote-app-actions .small {
  min-height: 28px;
  padding: 0.2rem 0.35rem;
  font-size: 0.76rem;
  white-space: nowrap;
}

.remote-apps-footnote {
  margin: 0;
  font-size: 0.78rem;
}
</style>

<script setup lang="ts">
defineOptions({ name: "OpsPanel" });

import { computed, onActivated, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useAuthStore } from "../stores/auth";
import { useShellStore } from "../stores/shellStore";
import { confirmDialog, notify } from "../composables/useNotify";
import { useOpsStore } from "../stores/opsStore";
import { useAdminStore } from "../stores/adminStore";
import { useManualPageRefresh } from "../composables/useManualPageRefresh";
import { api, apiErrorMessage } from "../api";
import ApSelect from "./common/ApSelect.vue";
import {
  CATEGORY_FIELD_GROUPS,
  CONFIG_KEY_HELPERS,
  CONFIG_KEY_LABELS,
  CONFIG_NAV_ITEMS,
  FALLBACK_AI_PROVIDERS,
  exportOpsConfig,
  fieldKind,
  fieldOptions,
  findAiProvider,
  getAiProviders,
  getOpsConfig,
  importOpsConfig,
  isCatalogDefaultBaseUrl,
  isReplaceableAiModel,
  saveOpsConfig,
  type AiProviderInfo,
  type ConfigFieldGroup,
  type ConfigNavItem,
  type OpsConfigResponse,
} from "../api/opsConfig";
import { buildOpsHealthRows } from "../utils/opsHealthRows";
import OpsHealthOverview from "./OpsHealthOverview.vue";

const TECH_KEYS_LS = "ap-mc-ops-show-tech-keys";

const auth = useAuthStore();
const shell = useShellStore();
const { user } = storeToRefs(auth);
const { activeTab, opsFocusCategory } = storeToRefs(shell);
const opsStore = useOpsStore();
const admin = useAdminStore();
const { ops } = storeToRefs(opsStore);


const loading = ref(false);
const saving = ref(false);
const exporting = ref(false);
const importing = ref(false);
const testing = ref<"alert" | "design" | null>(null);
const configBusy = computed(() => loading.value || saving.value || exporting.value || importing.value);
const error = ref("");
const notice = ref("");
const selectedNavId = ref("overview");
const config = ref<OpsConfigResponse | null>(null);
const draft = reactive<Record<string, string>>({});
const baseline = ref<Record<string, string>>({});
const importInput = ref<HTMLInputElement | null>(null);
const configMenu = ref<HTMLDetailsElement | null>(null);
const aiProviders = ref<AiProviderInfo[]>([...FALLBACK_AI_PROVIDERS]);
const baseUrlCustomized = ref(false);
const skipProviderSync = ref(false);
const showTechKeys = ref(false);

try {
  showTechKeys.value = localStorage.getItem(TECH_KEYS_LS) === "1";
} catch {
  /* ignore */
}

watch(showTechKeys, (v) => {
  try {
    localStorage.setItem(TECH_KEYS_LS, v ? "1" : "0");
  } catch {
    /* ignore */
  }
});

const backendCategories = computed(() => config.value?.categories || []);

const navItems = computed<ConfigNavItem[]>(() => CONFIG_NAV_ITEMS);

const selectedNav = computed(
  () => navItems.value.find((n) => n.id === selectedNavId.value) || navItems.value[0] || null,
);

const selectedKeys = computed(() => {
  const nav = selectedNav.value;
  if (!nav || nav.overview) return [] as string[];
  const keys: string[] = [];
  for (const bid of nav.backendIds) {
    const cat = backendCategories.value.find((c) => c.id === bid);
    if (cat?.keys?.length) keys.push(...cat.keys);
    else {
      for (const g of CATEGORY_FIELD_GROUPS[bid] || []) keys.push(...g.keys);
    }
  }
  return [...new Set(keys)];
});

const secretKeys = computed(() => config.value?.secret_keys || []);
const secretMask = computed(() => config.value?.secret_mask || "********");

const fieldGroups = computed<ConfigFieldGroup[]>(() => {
  const nav = selectedNav.value;
  if (!nav || nav.overview) return [];
  const provider = String(draft.AP_AI_PROVIDER || "").trim().toLowerCase();
  const groups: ConfigFieldGroup[] = [];
  const allowed = new Set(selectedKeys.value);
  for (const bid of nav.backendIds) {
    const predefined = CATEGORY_FIELD_GROUPS[bid];
    if (!predefined?.length) continue;
    for (const g of predefined) {
      if (g.id === "deepseek" && provider !== "deepseek") continue;
      const keys = g.keys.filter((k) => allowed.has(k));
      if (!keys.length) continue;
      groups.push({ ...g, keys });
    }
  }
  if (!groups.length && selectedKeys.value.length) {
    groups.push({
      id: "default",
      title: nav.title,
      subtitle: nav.description,
      keys: [...selectedKeys.value],
    });
  }
  return groups;
});

const currentAiProvider = computed(() =>
  findAiProvider(aiProviders.value, String(draft.AP_AI_PROVIDER || "")),
);

const currentModelOptions = computed(() => {
  const models = currentAiProvider.value?.models || [];
  const cur = String(draft.AP_AI_MODEL || "").trim();
  if (cur && !models.includes(cur)) return [cur, ...models];
  return [...models];
});

const providerSelectOptions = computed(() => fieldOptions("AP_AI_PROVIDER", aiProviders.value));

function isDirtyKey(key: string): boolean {
  return String(draft[key] ?? "") !== String(baseline.value[key] ?? "");
}

const dirtyCount = computed(() => {
  let n = 0;
  for (const k of Object.keys(draft)) {
    if (isDirtyKey(k)) n += 1;
  }
  return n;
});

const dirtyInNav = computed(() => selectedKeys.value.filter((k) => isDirtyKey(k)).length);

function dirtyForNav(nav: ConfigNavItem): number {
  if (nav.overview) return 0;
  const keys = new Set<string>();
  for (const bid of nav.backendIds) {
    const cat = backendCategories.value.find((c) => c.id === bid);
    if (cat?.keys?.length) cat.keys.forEach((k) => keys.add(k));
    else (CATEGORY_FIELD_GROUPS[bid] || []).forEach((g) => g.keys.forEach((k) => keys.add(k)));
  }
  let n = 0;
  for (const k of keys) if (isDirtyKey(k)) n += 1;
  return n;
}

const metricsEnabled = computed(
  () => String(draft.MC_METRICS_ENABLED || "1").trim() !== "0",
);

const metricsScrapeUrl = computed(() => {
  const path = ops.value?.metrics_path || "/metrics";
  if (typeof window !== "undefined" && window.location?.origin) {
    return `${window.location.origin}${path}`;
  }
  return path;
});

const apiKeyConfigured = computed(() =>
  Boolean(
    config.value?.design_ai_summary?.api_key_configured ||
      config.value?.secret_configured?.AP_AI_API_KEY,
  ),
);

const webhookConfigured = computed(() => Boolean(baseline.value.MC_WEBHOOK_URL?.trim()));

const healthRows = computed(() =>
  buildOpsHealthRows({
    apiKeyConfigured: apiKeyConfigured.value,
    webhookConfigured: webhookConfigured.value,
    provider:
      config.value?.design_ai_summary?.provider || baseline.value.AP_AI_PROVIDER || "—",
    model: config.value?.design_ai_summary?.model || baseline.value.AP_AI_MODEL || "—",
    embedder:
      ops.value?.rag?.embedder_name ||
      ops.value?.rag?.active_embedder ||
      config.value?.design_ai_summary?.rag_embedder ||
      baseline.value.AP_RAG_EMBEDDER ||
      "—",
    ragOk: Number(ops.value?.rag?.success_count ?? 0),
    ragFail: Number(ops.value?.rag?.failure_count ?? 0),
    ragLastError: ops.value?.rag?.last_error || "",
  }),
);

function sourceLabel(key: string): string {
  const src = config.value?.sources?.[key];
  if (src === "env") return "环境变量";
  if (src === "runtime" || src === "file") return "运行时";
  return "";
}

function applyValues(values: Record<string, string>) {
  const secrets = new Set(secretKeys.value);
  const mask = secretMask.value;
  const next: Record<string, string> = {};
  for (const [k, raw] of Object.entries(values || {})) {
    const v = String(raw ?? "");
    next[k] = secrets.has(k) && (v === mask || v === "") ? "" : v;
  }
  skipProviderSync.value = true;
  for (const k of Object.keys(draft)) {
    delete draft[k];
  }
  Object.assign(draft, next);
  baseline.value = { ...next };
  const providerId = String(next.AP_AI_PROVIDER || "");
  baseUrlCustomized.value = !isCatalogDefaultBaseUrl(
    String(next.AP_AI_BASE_URL || ""),
    aiProviders.value,
    providerId,
  );
  queueMicrotask(() => {
    skipProviderSync.value = false;
  });
}

async function loadAiProviders() {
  try {
    const out = await getAiProviders();
    if (out?.providers?.length) {
      aiProviders.value = out.providers;
    }
  } catch {
    /* 保留 FALLBACK */
  }
}

function applyFocusFromStore() {
  const focus = shell.consumeOpsFocusCategory();
  if (focus && navItems.value.some((n) => n.id === focus)) {
    selectedNavId.value = focus;
  }
}

async function load() {
  if (configBusy.value || user.value?.role !== "admin") return;
  loading.value = true;
  error.value = "";
  notice.value = "";
  try {
    await loadAiProviders();
    const out = await getOpsConfig();
    config.value = out;
    applyValues(out.values || {});
    applyFocusFromStore();
    if (!navItems.value.some((n) => n.id === selectedNavId.value)) {
      selectedNavId.value = "overview";
    }
    await opsStore.refreshOps();
  } catch (e) {
    error.value = apiErrorMessage(e);
  } finally {
    loading.value = false;
  }
}

async function refreshConfig() {
  if (configBusy.value) return;
  if (dirtyCount.value && !(await confirmDialog("刷新将丢弃未保存的修改。继续？"))) return;
  await load();
}

function applyProviderDefaults(prevProviderId: string, nextProviderId: string) {
  const next = findAiProvider(aiProviders.value, nextProviderId);
  if (!next) return;
  const curUrl = String(draft.AP_AI_BASE_URL || "");
  if (
    !baseUrlCustomized.value ||
    isCatalogDefaultBaseUrl(curUrl, aiProviders.value, prevProviderId)
  ) {
    draft.AP_AI_BASE_URL = next.default_base_url;
    baseUrlCustomized.value = false;
  }
  const curModel = String(draft.AP_AI_MODEL || "");
  if (isReplaceableAiModel(curModel, aiProviders.value, prevProviderId)) {
    draft.AP_AI_MODEL = next.default_model;
  }
}

function onBaseUrlInput() {
  const providerId = String(draft.AP_AI_PROVIDER || "");
  baseUrlCustomized.value = !isCatalogDefaultBaseUrl(
    String(draft.AP_AI_BASE_URL || ""),
    aiProviders.value,
    providerId,
  );
}

function selectNav(id: string) {
  if (id === selectedNavId.value) return;
  selectedNavId.value = id;
}

function closeConfigMenu() {
  if (!configMenu.value?.open) return;
  configMenu.value.open = false;
  configMenu.value.querySelector("summary")?.focus();
}

async function onSave() {
  if (!config.value || configBusy.value) return;
  saving.value = true;
  error.value = "";
  notice.value = "";
  try {
    const payload: Record<string, string> = {};
    const secrets = new Set(secretKeys.value);
    const mask = secretMask.value;
    for (const key of Object.keys(draft)) {
      if (!isDirtyKey(key)) continue;
      const val = draft[key] ?? "";
      if (secrets.has(key) && (val === "" || val === mask)) continue;
      payload[key] = val;
    }
    if (!Object.keys(payload).length) {
      notice.value = "没有可保存的修改";
      return;
    }
    const out = await saveOpsConfig(payload);
    config.value = out;
    applyValues(out.values || {});
    notice.value = "配置已保存，立即生效";
    await opsStore.refreshOps();
    await opsStore.refreshOpsConfig();
  } catch (e) {
    error.value = apiErrorMessage(e);
  } finally {
    saving.value = false;
  }
}

function onReloadNav() {
  if (configBusy.value) return;
  skipProviderSync.value = true;
  for (const k of selectedKeys.value) {
    draft[k] = baseline.value[k] ?? "";
  }
  if (selectedKeys.value.includes("AP_AI_BASE_URL")) onBaseUrlInput();
  queueMicrotask(() => { skipProviderSync.value = false; });
  error.value = "";
  notice.value = "已还原当前分类未保存修改";
}

async function onExport() {
  if (configBusy.value) return;
  closeConfigMenu();
  exporting.value = true;
  error.value = "";
  notice.value = "";
  try {
    const data = await exportOpsConfig();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `runtime_config_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    notice.value = "配置已导出";
  } catch (e) {
    error.value = apiErrorMessage(e);
  } finally {
    exporting.value = false;
  }
}

async function triggerImport() {
  if (configBusy.value) return;
  closeConfigMenu();
  if (
    dirtyCount.value > 0 &&
    !(await confirmDialog("导入将覆盖当前草稿并立即写入。继续？", {
      danger: true,
    }))
  ) {
    return;
  }
  importInput.value?.click();
}

async function onImportFile(ev: Event) {
  const input = ev.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file || configBusy.value) return;
  importing.value = true;
  error.value = "";
  notice.value = "";
  try {
    const text = await file.text();
    const payload = JSON.parse(text);
    const out = await importOpsConfig(payload);
    config.value = out;
    applyValues(out.values || {});
    notice.value = "配置已导入并保存";
    await opsStore.refreshOps();
    await opsStore.refreshOpsConfig();
  } catch (e) {
    error.value = apiErrorMessage(e);
  } finally {
    importing.value = false;
  }
}

function copyMetricsUrl() {
  admin.copyText(metricsScrapeUrl.value, "已复制 Prometheus 抓取地址");
}

async function onDesignWebhookTest() {
  if (testing.value || configBusy.value) return;
  testing.value = "design";
  try {
    const out = await api<{ ok: boolean }>("/api/v1/ops/design-webhook-test", {
      method: "POST",
    });
    notify(out.ok ? "测试通知已发送" : "发送失败，请查看平台日志", out.ok ? "success" : "error", {
      toast: true,
    });
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  } finally {
    testing.value = null;
  }
}

async function onAlertTest() {
  if (testing.value || configBusy.value) return;
  testing.value = "alert";
  try {
    await opsStore.onAlertTest();
  } finally {
    testing.value = null;
  }
}

function toggleValue(key: string, checked: boolean) {
  draft[key] = checked ? "1" : "0";
}

function isToggleOn(key: string): boolean {
  const v = String(draft[key] ?? "").trim().toLowerCase();
  return v === "1" || v === "true" || v === "yes" || v === "on";
}

function goCluster() {
  activeTab.value = "devices";
}

watch(
  () => draft.AP_AI_PROVIDER,
  (next, prev) => {
    if (skipProviderSync.value) return;
    const nextId = String(next || "").trim().toLowerCase();
    const prevId = String(prev || "").trim().toLowerCase();
    if (!nextId || nextId === prevId) return;
    applyProviderDefaults(prevId, nextId);
  },
);

watch(
  opsFocusCategory,
  (v) => {
    if (activeTab.value === "ops" && v) {
      applyFocusFromStore();
    }
  },
);

useManualPageRefresh("ops", refreshConfig);

function onBeforeUnload(ev: BeforeUnloadEvent) {
  if (dirtyCount.value > 0) {
    ev.preventDefault();
    ev.returnValue = "";
  }
}

let skipInitialActivation = false;
onMounted(() => {
  skipInitialActivation = true;
  window.addEventListener("beforeunload", onBeforeUnload);
  void load();
});
onUnmounted(() => {
  window.removeEventListener("beforeunload", onBeforeUnload);
});
onActivated(() => {
  if (skipInitialActivation) {
    skipInitialActivation = false;
    return;
  }
  applyFocusFromStore();
  if (dirtyCount.value) {
    void opsStore.refreshOps();
    return;
  }
  void load();
});
</script>

<template>
  <section v-if="user?.role === 'admin'" class="page-stack data-page config-center" :aria-busy="loading || saving || importing">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2>运维</h2>
      </div>
      <div class="page-hero-actions">
        <input
          ref="importInput"
          type="file"
          accept=".json,application/json"
          hidden
          @change="onImportFile"
        />
        <button type="button" class="small" :disabled="configBusy" @click="refreshConfig">刷新</button>
        <details ref="configMenu" class="action-menu" @keydown.esc.stop.prevent="closeConfigMenu">
          <summary class="small">{{ importing ? "正在导入…" : exporting ? "正在导出…" : "配置工具" }}</summary>
          <div class="action-menu-panel">
            <button type="button" :disabled="configBusy" @click="triggerImport">导入配置</button>
            <button type="button" :disabled="configBusy" @click="onExport">导出配置</button>
            <label class="cc-tech-toggle">
              <input v-model="showTechKeys" type="checkbox" />
              显示技术键名
            </label>
          </div>
        </details>
      </div>
    </header>

    <div v-if="error" class="msg bad" role="alert">{{ error }}</div>
    <div v-if="notice" class="msg ok" role="status">{{ notice }}</div>

    <p v-if="loading && !config" class="cc-loading" role="status">加载配置中…</p>
    <p v-else-if="!config" class="cc-loading">配置暂不可用，可点击「刷新」重试。</p>

    <div v-else class="cc-layout">
      <nav class="cc-cat-list" aria-label="配置分类">
        <button
          v-for="nav in navItems"
          :key="nav.id"
          type="button"
          class="cc-cat-item"
          :aria-pressed="nav.id === selectedNavId"
          aria-controls="ops-config-content"
          @click="selectNav(nav.id)"
        >
          <span>{{ nav.title }}</span>
          <span v-if="dirtyForNav(nav)" class="cc-dirty-dot" :aria-label="`${dirtyForNav(nav)} 项未保存`">
            {{ dirtyForNav(nav) }}
          </span>
        </button>
      </nav>

      <div id="ops-config-content" class="cc-main">
        <!-- 配置健康 -->
        <OpsHealthOverview
          v-if="selectedNavId === 'overview'"
          :rows="healthRows"
          :ops="ops"
          @select-nav="selectNav"
          @go-cluster="goCluster"
        />

        <!-- 可编辑分类 -->
        <template v-else>
          <div class="cc-panel-head">
            <h3 class="cc-panel-title">{{ selectedNav?.title }}</h3>
            <span v-if="dirtyInNav" class="cc-draft">{{ dirtyInNav }} 项未保存</span>
          </div>

          <div class="cc-groups">
            <component
              :is="group.collapsed ? 'details' : 'section'"
              v-for="group in fieldGroups"
              :key="group.id"
              class="cc-card"
              :class="{ 'cc-details': group.collapsed, 'cc-card--danger': group.danger }"
            >
              <summary v-if="group.collapsed" class="cc-details-summary">
                <span>
                  <span class="cc-card-title">{{ group.title }}</span>
                  <span v-if="group.subtitle" class="cc-card-sub">{{ group.subtitle }}</span>
                </span>
                <span v-if="group.danger" class="cc-danger-tag">谨慎</span>
              </summary>
              <header v-else class="cc-card-head">
                <div>
                  <h4 class="cc-card-title">{{ group.title }}</h4>
                  <p v-if="group.subtitle" class="cc-card-sub">{{ group.subtitle }}</p>
                </div>
                <span v-if="group.danger" class="cc-danger-tag">谨慎</span>
              </header>
              <fieldset class="cc-fields" :disabled="configBusy">
                <label
                  v-for="key in group.keys"
                  :key="key"
                  class="cc-field"
                  :title="CONFIG_KEY_HELPERS[key] || undefined"
                >
                  <span class="cc-field-label">
                    <span>{{ CONFIG_KEY_LABELS[key] || key }}</span>
                    <span v-if="sourceLabel(key)" class="cc-source">{{ sourceLabel(key) }}</span>
                  </span>

                  <ApSelect
                    v-if="fieldKind(key, secretKeys) === 'select'"
                    v-model="draft[key]"
                    class="cc-control"
                    :disabled="configBusy"
                    :aria-label="CONFIG_KEY_LABELS[key] || key"
                    :options="key === 'AP_AI_PROVIDER' ? providerSelectOptions : fieldOptions(key)"
                  />

                  <span v-else-if="fieldKind(key, secretKeys) === 'model_combo'" class="cc-combo">
                    <input
                      v-model="draft[key]"
                      type="text"
                      class="cc-control"
                      list="ap-ai-model-options"
                      :placeholder="currentAiProvider?.default_model || '模型名称'"
                      autocomplete="off"
                    />
                  </span>

                  <span v-else-if="fieldKind(key, secretKeys) === 'toggle'" class="cc-toggle-row">
                    <input
                      type="checkbox"
                      :checked="isToggleOn(key)"
                      @change="toggleValue(key, ($event.target as HTMLInputElement).checked)"
                    />
                    <span>{{ isToggleOn(key) ? "已启用" : "已关闭" }}</span>
                  </span>

                  <input
                    v-else-if="fieldKind(key, secretKeys) === 'password'"
                    v-model="draft[key]"
                    type="password"
                    class="cc-control"
                    :placeholder="
                      config?.secret_configured?.[key] ? `${secretMask}（留空保持）` : '未配置'
                    "
                    autocomplete="new-password"
                  />

                  <input
                    v-else-if="fieldKind(key, secretKeys) === 'number'"
                    v-model="draft[key]"
                    type="number"
                    step="any"
                    class="cc-control"
                  />

                  <input
                    v-else-if="key === 'AP_AI_BASE_URL'"
                    v-model="draft[key]"
                    type="text"
                    class="cc-control"
                    :placeholder="currentAiProvider?.default_base_url || 'Base URL'"
                    @input="onBaseUrlInput"
                  />

                  <input v-else v-model="draft[key]" type="text" class="cc-control" />

                  <span v-if="showTechKeys && CONFIG_KEY_HELPERS[key]" class="cc-help">{{ CONFIG_KEY_HELPERS[key] }}</span>
                  <code v-if="showTechKeys" class="cc-key">{{ key }}</code>
                </label>
              </fieldset>

              <div
                v-if="group.id === 'alert' && draft.MC_ALERT_WEBHOOK_URL"
                class="cc-card-foot"
              >
                <button type="button" class="small" :disabled="configBusy || Boolean(testing)" @click="onAlertTest">
                  {{ testing === "alert" ? "正在发送…" : "发送测试告警" }}
                </button>
              </div>
              <div
                v-if="group.id === 'design_webhook'"
                class="cc-card-foot design-webhook-foot"
              >
                <p class="cc-inline-help">
                  在 IDE 启动接收服务后填写通知地址，例如 <code>http://127.0.0.1:8765/hooks/intent</code>。
                </p>
                <button
                  v-if="draft.MC_DESIGN_WEBHOOK_URL"
                  type="button"
                  class="small"
                  :disabled="configBusy || Boolean(testing)"
                  @click="onDesignWebhookTest"
                >
                  {{ testing === "design" ? "正在发送…" : "发送设计域测试事件" }}
                </button>
              </div>
            </component>

            <datalist id="ap-ai-model-options">
              <option v-for="m in currentModelOptions" :key="m" :value="m" />
            </datalist>

            <article v-if="selectedNavId === 'platform_policy'" class="cc-card">
              <div class="cc-card-head">
                <div>
                  <h4 class="cc-card-title">Prometheus 抓取地址</h4>
                </div>
              </div>
              <div class="cc-metrics-row">
                <input :value="metricsScrapeUrl" readonly class="cc-control mono" :disabled="!metricsEnabled" aria-label="Prometheus 抓取地址" />
                <button type="button" class="small" :disabled="!metricsEnabled" @click="copyMetricsUrl">
                  复制地址
                </button>
              </div>
            </article>
          </div>

        </template>
      </div>
      <footer v-if="selectedNavId !== 'overview' || dirtyCount" class="cc-savebar">
        <span v-if="dirtyCount" class="cc-draft" role="status">{{ dirtyCount }} 项待保存</span>
        <div class="cc-savebar-actions">
          <button
            v-if="selectedNavId !== 'overview'"
            type="button"
            class="small"
            :disabled="configBusy || dirtyInNav === 0"
            @click="onReloadNav"
          >
            还原本分类
          </button>
          <button
            type="button"
            class="primary"
            :disabled="configBusy || dirtyCount === 0"
            @click="onSave"
          >
            {{ saving ? "保存中…" : "保存修改" }}
          </button>
        </div>
      </footer>
    </div>
  </section>
</template>

<style scoped>
.config-center {
  min-height: 0;
}

.cc-tech-toggle {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.4rem 0.65rem;
  font-size: var(--font-size-body);
  cursor: pointer;
}

.cc-tech-toggle input,
.cc-toggle-row input {
  width: auto;
  margin: 0;
}

.cc-loading {
  margin: 0;
  padding: 0.65rem 0;
  color: var(--muted);
}

.cc-layout {
  min-width: 0;
}

.cc-cat-list {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  column-gap: 1rem;
  border-bottom: 1px solid var(--line);
}

.cc-cat-item {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.55rem 0.15rem;
  background: transparent;
  border: 0;
  border-bottom: 2px solid transparent;
  border-radius: 0;
  color: var(--muted);
  box-shadow: none;
}

.cc-cat-item:hover,
.cc-cat-item[aria-pressed="true"] {
  color: var(--accent-text, var(--accent));
}

.cc-cat-item[aria-pressed="true"] {
  border-bottom-color: var(--accent);
}

.cc-dirty-dot,
.cc-draft {
  color: var(--warning-soft-fg);
  font-size: var(--font-size-meta);
  font-variant-numeric: tabular-nums;
}

.cc-dirty-dot {
  display: inline-block;
  min-width: 1.15rem;
  padding: 0.05rem 0.25rem;
  text-align: center;
  border-radius: var(--radius-sm);
  background: var(--warning-soft-bg);
}

.cc-main {
  padding-top: 1rem;
  min-width: 0;
}

.cc-panel-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.5rem;
}

.cc-panel-title {
  margin: 0;
  font-size: 1.05rem;
}

.cc-groups {
  margin-top: 0.75rem;
}

.cc-card {
  min-width: 0;
  padding: 1rem 0;
  border-top: 1px solid var(--line-soft);
}

.cc-card--danger {
  border-top-color: var(--warning-soft-border);
}

.cc-details {
  padding: 0;
}

.cc-details-summary {
  display: flex;
  align-items: flex-start;
  gap: 0.65rem;
  padding-block: 0.85rem;
  cursor: pointer;
  list-style: none;
}

.cc-details-summary::-webkit-details-marker {
  display: none;
}

.cc-details-summary::before {
  content: "›";
  line-height: 1.45;
  font-weight: 700;
  color: var(--muted);
}

.cc-details[open] .cc-details-summary::before {
  transform: rotate(90deg);
}

.cc-details-summary > span:first-of-type {
  flex: 1;
  min-width: 0;
}

.cc-details .cc-fields {
  padding-bottom: 1rem;
}

.cc-card-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.75rem;
  margin-bottom: 0.7rem;
}

.cc-card-title {
  display: block;
  margin: 0;
  font-size: var(--font-size-body);
  font-weight: 650;
}

.cc-card-sub,
.cc-inline-help {
  display: block;
  margin: 0.25rem 0 0;
  color: var(--muted);
  font-size: var(--font-size-meta);
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.cc-danger-tag {
  color: var(--warning-soft-fg);
  font-size: var(--font-size-meta);
  white-space: nowrap;
}

.cc-card-foot {
  margin-top: 0.75rem;
}

.design-webhook-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.65rem;
}

.cc-fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(16rem, 100%), 1fr));
  gap: 0.65rem 1rem;
  max-width: 66rem;
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 0;
}

.cc-field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  min-width: 0;
}

.cc-field-label {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.15rem 0.5rem;
  font-size: var(--font-size-meta);
  font-weight: 600;
}

.cc-source,
.cc-help,
.cc-key {
  color: var(--muted);
  font-size: var(--font-size-meta);
  font-weight: 400;
  overflow-wrap: anywhere;
}

.cc-control,
.cc-combo {
  width: 100%;
}

.cc-toggle-row {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  font-size: var(--font-size-body);
  color: var(--muted);
  min-height: var(--control-height);
}

.cc-metrics-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  max-width: 42rem;
}

.cc-metrics-row .cc-control {
  flex: 1 1 12rem;
  min-width: 0;
}

.cc-savebar {
  position: sticky;
  bottom: 0;
  z-index: 2;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 1rem;
  margin-top: 0.25rem;
  padding: 0.65rem 0;
  border-top: 1px solid var(--line);
  background: var(--panel);
}

.cc-savebar-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-inline-start: auto;
}

.msg.bad,
.msg.ok {
  margin: 0;
}

@media (max-width: 560px) {
  .cc-cat-list {
    column-gap: 0.75rem;
  }

  .cc-fields {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>

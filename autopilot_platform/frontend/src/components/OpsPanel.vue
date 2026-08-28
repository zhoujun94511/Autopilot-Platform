<script setup lang="ts">
defineOptions({ name: "OpsPanel" });

import { computed, onActivated, onMounted, reactive, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useAuthStore } from "../stores/auth";
import { useShellStore } from "../stores/shellStore";
import { confirmDialog, notify } from "../composables/useNotify";
import { useOpsStore } from "../stores/opsStore";
import { useAdminStore } from "../stores/adminStore";
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
const error = ref("");
const notice = ref("");
const selectedNavId = ref("overview");
const config = ref<OpsConfigResponse | null>(null);
const draft = reactive<Record<string, string>>({});
const baseline = ref<Record<string, string>>({});
const importInput = ref<HTMLInputElement | null>(null);
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

const webhookConfigured = computed(() => {
  const url = String(draft.MC_WEBHOOK_URL || baseline.value.MC_WEBHOOK_URL || "").trim();
  return Boolean(url);
});

const healthRows = computed(() =>
  buildOpsHealthRows({
    apiKeyConfigured: apiKeyConfigured.value,
    webhookConfigured: webhookConfigured.value,
    provider:
      config.value?.design_ai_summary?.provider || draft.AP_AI_PROVIDER || "—",
    model: config.value?.design_ai_summary?.model || draft.AP_AI_MODEL || "—",
    embedder:
      ops.value?.rag?.embedder_name ||
      ops.value?.rag?.active_embedder ||
      config.value?.design_ai_summary?.rag_embedder ||
      draft.AP_RAG_EMBEDDER ||
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
  loading.value = true;
  error.value = "";
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

async function selectNav(id: string) {
  if (id === selectedNavId.value) return;
  if (
    dirtyCount.value > 0 &&
    !(await confirmDialog("当前有未保存修改，切换分类将保留草稿但不自动保存。继续？"))
  ) {
    return;
  }
  selectedNavId.value = id;
}

async function onSave() {
  if (!config.value) return;
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
  for (const k of selectedKeys.value) {
    draft[k] = baseline.value[k] ?? "";
  }
  notice.value = "已还原当前分类未保存修改";
}

async function onExport() {
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
  if (!file) return;
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
  try {
    const out = await api<{ ok: boolean }>("/api/v1/ops/design-webhook-test", {
      method: "POST",
    });
    notify(out.ok ? "测试通知已发送" : "发送失败，请查看平台日志", out.ok ? "success" : "error", {
      toast: true,
    });
  } catch (e) {
    notify(apiErrorMessage(e), "error");
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
  () => activeTab.value,
  (tab) => {
    if (tab === "ops") void load();
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

let _skipActivateReload = false;
onMounted(() => {
  _skipActivateReload = true;
  void load();
});
onActivated(() => {
  if (_skipActivateReload) {
    _skipActivateReload = false;
    return;
  }
  void load();
});
</script>

<template>
  <section v-if="user?.role === 'admin'" class="config-center">
    <header class="cc-header">
      <div class="cc-header-copy">
        <h2>配置中心</h2>
        <p class="cc-lede">密钥不会完整显示。不想改就留空，保存后仍用原来的值。</p>
      </div>
      <div class="cc-header-actions">
        <label class="cc-tech-toggle" title="显示环境变量名与字段说明">
          <input v-model="showTechKeys" type="checkbox" />
          显示技术键名
        </label>
        <input
          ref="importInput"
          type="file"
          accept=".json,application/json"
          hidden
          @change="onImportFile"
        />
        <button type="button" class="small" :disabled="loading || saving || exporting" @click="onExport">
          {{ exporting ? "导出中…" : "导出" }}
        </button>
        <button type="button" class="small" :disabled="loading || saving || importing" @click="triggerImport">
          {{ importing ? "导入中…" : "导入" }}
        </button>
        <button type="button" class="small" :disabled="loading || saving" @click="load">刷新</button>
        <button
          type="button"
          class="primary"
          :disabled="loading || saving || !config || dirtyCount === 0"
          @click="onSave"
        >
          {{ saving ? "保存中…" : dirtyCount > 0 ? `保存（${dirtyCount}）` : "已保存" }}
        </button>
      </div>
    </header>

    <div v-if="error" class="msg bad">{{ error }}</div>
    <div v-if="notice" class="msg ok">{{ notice }}</div>

    <div v-if="loading && !config" class="cc-loading">加载配置中…</div>

    <div v-else class="cc-layout">
      <aside class="cc-sidebar">
        <div class="cc-sidebar-title">分类</div>
        <nav class="cc-cat-list" aria-label="配置分类">
          <button
            v-for="nav in navItems"
            :key="nav.id"
            type="button"
            class="cc-cat-item"
            :class="{ active: nav.id === selectedNavId }"
            @click="selectNav(nav.id)"
          >
            <span class="cc-cat-text">
              <span class="cc-cat-name">{{ nav.title }}</span>
              <span class="cc-cat-desc">{{ nav.description }}</span>
            </span>
            <span v-if="dirtyForNav(nav) > 0" class="cc-dirty-dot" :title="`${dirtyForNav(nav)} 项未保存`">
              {{ dirtyForNav(nav) }}
            </span>
          </button>
        </nav>
      </aside>

      <div class="cc-main">
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
            <div>
              <h3 class="cc-panel-title">{{ selectedNav?.title }}</h3>
              <p class="cc-panel-sub">{{ selectedNav?.description }}</p>
            </div>
            <div class="cc-panel-meta">
              <span class="cc-dirty-pill" :class="{ active: dirtyInNav > 0 }">
                {{ dirtyInNav > 0 ? `${dirtyInNav} 项未保存` : "无未保存修改" }}
              </span>
            </div>
          </div>

          <div class="cc-groups">
            <template v-for="group in fieldGroups" :key="group.id">
              <details
                v-if="group.collapsed"
                class="cc-card cc-details"
                :class="{ 'cc-card--danger': group.danger }"
              >
                <summary class="cc-details-summary">
                  <span>
                    <span class="cc-card-title">{{ group.title }}</span>
                    <span v-if="group.subtitle" class="cc-card-sub inline">{{ group.subtitle }}</span>
                  </span>
                  <span v-if="group.danger" class="cc-danger-tag">谨慎</span>
                </summary>
                <div class="cc-fields">
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
                    <input v-else v-model="draft[key]" type="text" class="cc-control" />
                    <span v-if="showTechKeys && CONFIG_KEY_HELPERS[key]" class="cc-help">{{ CONFIG_KEY_HELPERS[key] }}</span>
                    <code v-if="showTechKeys" class="cc-key">{{ key }}</code>
                  </label>
                </div>
              </details>

              <article v-else class="cc-card" :class="{ 'cc-card--danger': group.danger }">
                <div class="cc-card-head">
                  <div>
                    <h4 class="cc-card-title">{{ group.title }}</h4>
                    <p v-if="group.subtitle" class="cc-card-sub">{{ group.subtitle }}</p>
                  </div>
                  <span v-if="group.danger" class="cc-danger-tag">谨慎</span>
                </div>

                <div class="cc-fields">
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
                </div>

                <div
                  v-if="group.id === 'alert' && draft.MC_ALERT_WEBHOOK_URL"
                  class="cc-card-foot"
                >
                  <button type="button" class="small" @click="opsStore.onAlertTest">发送测试告警</button>
                </div>
                <div
                  v-if="group.id === 'design_webhook'"
                  class="cc-card-foot design-webhook-foot"
                >
                  <p class="cc-inline-help">
                    审核通过后自动写入本机工程：先在 IDE 启动接收服务，再把通知地址填在这里（本机示例
                    <code>http://127.0.0.1:8765/hooks/intent</code>）。
                  </p>
                  <button
                    v-if="draft.MC_DESIGN_WEBHOOK_URL"
                    type="button"
                    class="small"
                    @click="onDesignWebhookTest"
                  >
                    发送设计域测试事件
                  </button>
                </div>
              </article>
            </template>

            <datalist id="ap-ai-model-options">
              <option v-for="m in currentModelOptions" :key="m" :value="m" />
            </datalist>

            <article v-if="selectedNavId === 'platform_policy'" class="cc-card">
              <div class="cc-card-head">
                <div>
                  <h4 class="cc-card-title">Prometheus 抓取</h4>
                  <p class="cc-card-sub">机器可读指标接口，勿在浏览器中当页面打开。</p>
                </div>
              </div>
              <div class="cc-metrics-row">
                <input :value="metricsScrapeUrl" readonly class="cc-control mono" :disabled="!metricsEnabled" />
                <button type="button" class="small" :disabled="!metricsEnabled" @click="copyMetricsUrl">
                  复制地址
                </button>
              </div>
            </article>
          </div>

          <footer class="cc-savebar">
            <span class="cc-savebar-status">
              {{ dirtyCount > 0 ? `共 ${dirtyCount} 项待保存` : "所有修改已同步" }}
            </span>
            <div class="cc-savebar-actions">
              <button
                type="button"
                class="small"
                :disabled="saving || dirtyInNav === 0"
                @click="onReloadNav"
              >
                还原本分类
              </button>
              <button
                type="button"
                class="primary"
                :disabled="saving || dirtyCount === 0"
                @click="onSave"
              >
                {{ saving ? "保存中…" : "保存修改" }}
              </button>
            </div>
          </footer>
        </template>
      </div>
    </div>
  </section>
</template>

<style scoped>
.config-center {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-height: 0;
  height: 100%;
  width: 100%;
  max-width: none;
}

.cc-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
  flex-wrap: wrap;
}

.cc-header-copy h2 {
  margin: 0 0 0.35rem;
  font-size: 1.25rem;
}

.cc-lede {
  margin: 0;
  max-width: 36rem;
  color: var(--muted);
  font-size: 0.88rem;
  line-height: 1.5;
}

.cc-header-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}

.cc-tech-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.78rem;
  color: var(--muted);
  margin-right: 0.25rem;
  cursor: pointer;
  user-select: none;
}

.cc-tech-toggle input {
  width: auto;
  margin: 0;
}

.cc-loading {
  padding: 2rem;
  color: var(--muted);
  text-align: center;
}

.cc-layout {
  display: grid;
  grid-template-columns: minmax(200px, 240px) minmax(0, 1fr);
  gap: 1rem;
  align-items: start;
  min-height: 0;
  flex: 1;
}

.cc-sidebar {
  position: sticky;
  top: 0.5rem;
  background: var(--surface-soft);
  border: 1px solid var(--line-soft);
  border-radius: 12px;
  padding: 0.85rem;
}

.cc-sidebar-title {
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 0.65rem;
}

.cc-cat-list {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.cc-cat-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
  width: 100%;
  text-align: left;
  padding: 0.65rem 0.7rem;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--panel, var(--surface-primary, #fff));
  color: var(--text);
  cursor: pointer;
  transition: var(--transition);
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.03);
}

.cc-cat-item:hover {
  background: var(--nav-hover, var(--action-hover));
  border-color: var(--border-strong, var(--line));
}

.cc-cat-item.active {
  background: var(--nav-active-bg);
  border-color: var(--accent);
  box-shadow: inset 0 0 0 1px rgba(21, 101, 192, 0.2);
}

.cc-cat-text {
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
  min-width: 0;
}

.cc-cat-name {
  font-size: 0.9rem;
  font-weight: 600;
}

.cc-cat-desc {
  font-size: 0.7rem;
  color: var(--muted);
  line-height: 1.35;
}

.cc-dirty-dot {
  flex-shrink: 0;
  min-width: 1.15rem;
  height: 1.15rem;
  padding: 0 0.28rem;
  border-radius: 999px;
  background: var(--warning-soft-bg, rgba(217, 153, 59, 0.2));
  border: 1px solid var(--warning-soft-border, rgba(217, 153, 59, 0.45));
  color: var(--warning-soft-fg, #d9993b);
  font-size: 0.65rem;
  font-weight: 700;
  line-height: 1.15rem;
  text-align: center;
}

.cc-main {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-width: 0;
}

.cc-panel-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
}

.cc-panel-title {
  margin: 0 0 0.25rem;
  font-size: 1.05rem;
}

.cc-panel-sub {
  margin: 0;
  color: var(--muted);
  font-size: 0.84rem;
  line-height: 1.45;
}

.cc-dirty-pill {
  font-size: 0.75rem;
  padding: 0.25rem 0.55rem;
  border-radius: 999px;
  border: 1px solid var(--line);
  color: var(--muted);
  background: var(--chip-bg);
  white-space: nowrap;
}

.cc-dirty-pill.active {
  border-color: var(--warning-soft-border);
  background: var(--warning-soft-bg);
  color: var(--warning-soft-fg);
}

button.small.linkish {
  border: none;
  background: transparent;
  color: var(--accent-text, var(--accent));
  text-decoration: underline;
  padding: 0 0.15rem;
  cursor: pointer;
}

.cc-groups {
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
}

.cc-card {
  background: var(--surface-soft);
  border: 1px solid var(--line-soft);
  border-radius: 12px;
  padding: 0.85rem 1rem;
}

.cc-card--danger {
  border-color: var(--warning-soft-border);
  background: linear-gradient(
    180deg,
    var(--warning-soft-bg) 0%,
    var(--surface-soft) 28%
  );
}

.cc-details {
  padding: 0;
}

.cc-details-summary {
  list-style: none;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.85rem 1rem;
  user-select: none;
}

.cc-details-summary::-webkit-details-marker {
  display: none;
}

.cc-details-summary .cc-card-title {
  display: block;
}

.cc-details-summary .cc-card-sub.inline {
  display: block;
  margin-top: 0.3rem;
}

.cc-details[open] .cc-details-summary {
  border-bottom: 1px solid var(--line-soft);
  margin-bottom: 0;
}

.cc-details .cc-fields {
  padding: 0.75rem 1rem 0.9rem;
}

.cc-card-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.75rem;
  margin-bottom: 0.85rem;
}

.cc-card-title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 700;
}

.cc-card-sub {
  margin: 0.3rem 0 0;
  font-size: 0.8rem;
  color: var(--muted);
  line-height: 1.4;
}

.cc-danger-tag {
  font-size: 0.68rem;
  font-weight: 700;
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
  background: var(--warning-soft-bg);
  border: 1px solid var(--warning-soft-border);
  color: var(--warning-soft-fg);
}

.cc-card-foot {
  margin-top: 0.85rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--line-soft);
  display: flex;
  justify-content: flex-end;
}

.design-webhook-foot {
  flex-direction: column;
  align-items: stretch;
  gap: 0.65rem;
}

.cc-inline-help {
  margin: 0;
  font-size: 0.78rem;
  line-height: 1.45;
  color: var(--muted);
  white-space: normal;
  overflow-wrap: break-word;
}

.cc-inline-help code {
  font-size: 0.74rem;
}

.cc-fields {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(16rem, 22rem));
  gap: 0.55rem 0.85rem;
}

.cc-field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  min-width: 0;
}

.cc-field-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8rem;
  font-weight: 600;
}

.cc-source {
  font-size: 0.68rem;
  font-weight: 500;
  color: var(--muted);
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
  background: var(--chip-bg);
  border: 1px solid var(--line);
}

.cc-control {
  width: 100%;
  box-sizing: border-box;
}

.cc-toggle-row {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
  color: var(--muted);
  min-height: 2.1rem;
}

.cc-combo {
  display: block;
  width: 100%;
}

.cc-toggle-row input {
  width: auto;
  margin: 0;
}

.cc-help {
  font-size: 0.75rem;
  color: var(--muted);
  line-height: 1.35;
}

.cc-key {
  font-size: 0.68rem;
  color: var(--muted);
  opacity: 0.85;
}

.cc-metrics-row {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.cc-metrics-row .cc-control {
  flex: 1;
  min-width: 0;
}

.cc-savebar {
  position: sticky;
  bottom: 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
  padding: 0.85rem 1rem;
  margin-top: 0.25rem;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--elevated);
  box-shadow: var(--panel-shadow);
  z-index: 2;
}

.cc-savebar-status {
  font-size: 0.82rem;
  color: var(--muted);
}

.cc-savebar-actions {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.msg.bad,
.msg.ok {
  margin: 0;
  padding: 0.65rem 0.85rem;
  border-radius: 8px;
  font-size: 0.85rem;
}

.msg.bad {
  background: var(--danger-soft-bg);
  border: 1px solid var(--danger-soft-border);
  color: var(--danger-soft-fg);
}

.msg.ok {
  background: var(--ok-soft-bg);
  border: 1px solid var(--ok-soft-border);
  color: var(--ok-soft-fg);
}

@media (max-width: 900px) {
  .cc-layout {
    grid-template-columns: 1fr;
  }

  .cc-sidebar {
    position: static;
  }

  .cc-cat-list {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  }
}
</style>

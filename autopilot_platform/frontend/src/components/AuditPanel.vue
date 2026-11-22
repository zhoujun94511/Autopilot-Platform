<script setup lang="ts">
defineOptions({ name: "AuditPanel" });

import { storeToRefs } from "pinia";
import { computed, onDeactivated, reactive, ref, watch } from "vue";
import type { AuditLog } from "../api";
import { listAuditsPage, OPS_LIST_PAGE_SIZE } from "../api/opsLists";
import { useAuthStore } from "../stores/auth";
import { useCapabilities } from "../composables/useCapabilities";
import { usePagedList } from "../composables/usePagedList";
import { useAdminStore } from "../stores/adminStore";
import { useProjectsStore } from "../stores/projectsStore";
import { useManualPageRefresh } from "../composables/useManualPageRefresh";
import ApModal from "./ApModal.vue";
import DataPager from "./common/DataPager.vue";
import { auditResourceLabel, formatAuditRow } from "../utils/auditDisplay";
import { parseApiTime } from "../utils/parseApiTime";

const auth = useAuthStore();
const { canManageUsers } = storeToRefs(auth);
const admin = useAdminStore();
const { auditsListVersion, auditFilter } = storeToRefs(admin);
const { filterOrgId } = storeToRefs(useProjectsStore());
const caps = useCapabilities();
const draft = reactive({ ...auditFilter.value });
const selected = ref<AuditLog | null>(null);
const dateTime = new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "medium" });

const list = usePagedList<AuditLog>({
  immediate: false,
  pageSize: OPS_LIST_PAGE_SIZE,
  fetchPage: ({ page, pageSize }) =>
    listAuditsPage({
      page,
      pageSize,
      action: auditFilter.value.action.trim() || undefined,
      actor: auditFilter.value.actor.trim() || undefined,
    }),
  resetSources: [filterOrgId],
});

const { items, total, page, pageSize, loading, hasLoaded, error, reload, setPage, setPageSize } = list;

watch(
  [() => auditFilter.value.action, () => auditFilter.value.actor, auditsListVersion],
  ([action, actor], [previousAction, previousActor]) => {
    const changed = action !== previousAction || actor !== previousActor;
    if (changed) {
      Object.assign(draft, { action, actor });
      if (items.value.length) hasLoaded.value = false;
      items.value = [];
      total.value = 0;
    }
    void reload(changed);
  },
);
useManualPageRefresh("audit", () => reload(false));
void reload(true);

function applyFilter() {
  const action = draft.action.trim();
  const actor = draft.actor.trim();
  if (action === auditFilter.value.action && actor === auditFilter.value.actor) {
    Object.assign(draft, { action, actor });
    void reload(true);
  } else {
    Object.assign(auditFilter.value, { action, actor });
  }
}

const auditFiltered = computed(
  () => Boolean(auditFilter.value.action.trim() || auditFilter.value.actor.trim()),
);
const emptyMessage = computed(() => {
  if (!hasLoaded.value) return "正在读取审计记录…";
  return auditFiltered.value ? "没有符合查询条件的记录" : "暂无审计记录";
});

function clearAuditFilter() {
  Object.assign(draft, { action: "", actor: "" });
  applyFilter();
}

function closeDetails() {
  selected.value = null;
}

watch(filterOrgId, closeDetails, { flush: "sync" });
watch(canManageUsers, (allowed) => {
  if (!allowed) closeDetails();
});
onDeactivated(closeDetails);

function fullTime(value?: string | null) {
  const stamp = parseApiTime(value);
  return Number.isFinite(stamp) ? dateTime.format(stamp) : value || "—";
}

const rows = computed(() =>
  items.value.map((a) => ({
    raw: a,
    display: formatAuditRow(a),
  })),
);
</script>

<template>
  <section v-if="canManageUsers" class="panel page-stack data-page">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2>审计</h2>
        <p v-if="!caps.canOps" class="lede">只显示当前组织的操作记录。</p>
      </div>
      <div class="page-hero-actions">
        <button type="button" class="ghost" :disabled="loading" @click="reload(false)">刷新</button>
      </div>
    </header>

    <form class="audit-filter-form" aria-label="审计筛选" @submit.prevent="applyFilter">
      <div class="audit-field">
        <label for="audit-action-input">操作代码</label>
        <input
          id="audit-action-input"
          v-model="draft.action"
          placeholder="例如 job.create 或 device."
          list="audit-action-prefixes"
        />
        <datalist id="audit-action-prefixes">
          <option value="job." label="批跑任务" />
          <option value="device." label="设备" />
          <option value="design." label="测试设计" />
          <option value="acl." label="共享授权" />
          <option value="user." label="用户管理" />
          <option value="auth." label="登录认证" />
        </datalist>
      </div>
      <div class="audit-field">
        <label for="audit-actor-input">操作者</label>
        <input id="audit-actor-input" v-model="draft.actor" placeholder="输入完整用户名" />
      </div>
      <div class="audit-filter-actions">
        <button type="submit" class="primary" :disabled="loading">查询</button>
        <button
          v-if="auditFiltered || draft.action || draft.actor"
          type="button"
          class="ghost"
          @click="clearAuditFilter"
        >重置</button>
      </div>
    </form>

    <div v-if="error" class="audit-error" role="alert">
      <span>{{ error }}</span>
      <button type="button" class="linkish" :disabled="loading" @click="reload(false)">重试</button>
    </div>
    <div class="table-wrap">
      <table aria-label="审计记录" :aria-busy="loading">
        <thead>
          <tr>
            <th scope="col">时间</th>
            <th scope="col">操作</th>
            <th scope="col">操作者</th>
            <th scope="col">组织</th>
            <th scope="col">资源</th>
            <th scope="col">详情</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!rows.length && !error">
            <td class="empty" colspan="6">{{ emptyMessage }}</td>
          </tr>
          <tr v-for="{ raw, display } in rows" :key="raw.id">
            <td class="mono time-cell" :title="fullTime(raw.created_at)">{{ display.time }}</td>
            <td>
              <button
                type="button"
                class="linkish audit-record"
                :aria-label="'查看记录 ' + display.actionLabel + ' · ' + raw.id"
                @click="selected = raw"
              >{{ display.actionLabel }}</button>
            </td>
            <td>{{ raw.actor || "—" }}</td>
            <td class="mono">{{ raw.org_id || "—" }}</td>
            <td class="audit-resource-cell" :title="raw.resource_id ? `${raw.resource_type}: ${raw.resource_id}` : undefined">
              {{ display.resourceSummary }}
            </td>
            <td class="audit-desc-cell" :title="raw.detail || undefined">{{ display.detailSummary }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <DataPager
      v-if="total > 0"
      :total="total"
      :page="page"
      :page-size="pageSize"
      :loading="loading"
      @update:page="setPage"
      @update:page-size="setPageSize"
    />

    <ApModal v-if="selected" title="操作记录" variant="drawer" @close="closeDetails">
      <dl class="audit-record-fields">
        <dt>操作</dt>
        <dd>{{ formatAuditRow(selected).actionLabel }} <code v-if="selected.action">{{ selected.action }}</code></dd>
        <dt>时间</dt>
        <dd>{{ fullTime(selected.created_at) }}</dd>
        <dt>操作者</dt>
        <dd>{{ selected.actor || "—" }} <span v-if="selected.actor_kind">({{ selected.actor_kind }})</span></dd>
        <dt>组织</dt>
        <dd>{{ selected.org_id || "—" }}</dd>
        <template v-if="selected.resource_type || selected.resource_id">
          <dt>资源</dt>
          <dd>
            {{ auditResourceLabel(selected.resource_type) }}
            <code v-if="selected.resource_id">{{ selected.resource_id }}</code>
            <button v-if="selected.resource_id" type="button" class="linkish" @click="admin.copyText(selected.resource_id)">
              复制 ID
            </button>
          </dd>
        </template>
        <dt>记录 ID</dt>
        <dd><code>{{ selected.id }}</code></dd>
      </dl>
      <pre v-if="selected.detail" class="audit-record-detail" aria-label="记录详情">{{ selected.detail }}</pre>
      <template #actions>
        <button type="button" @click="closeDetails">关闭</button>
      </template>
    </ApModal>
  </section>
</template>

<style scoped>
.audit-filter-form {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 10px;
  background: var(--vben-bg-muted);
  border: 1px solid var(--vben-border-soft);
}

.audit-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 0 1 240px;
  min-width: 180px;
}

.audit-field label {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--vben-fg-muted);
}

.audit-field input {
  height: 34px;
  border-radius: 6px;
}

.audit-filter-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.audit-error {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  color: var(--danger-soft-fg);
}

.time-cell {
  color: var(--vben-fg-muted);
  white-space: nowrap;
}

.audit-record {
  text-align: start;
  font-weight: 500;
}

.audit-resource-cell {
  white-space: nowrap;
  color: var(--vben-fg);
}

.audit-desc-cell {
  max-width: 42ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--vben-fg-muted);
}

.audit-record-fields {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 0.65rem 1rem;
  font-size: var(--font-size-body);
}

.audit-record-fields dt {
  color: var(--muted);
}

.audit-record-fields dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.audit-record-fields code,
.audit-record-fields dd span {
  color: var(--muted);
}

.audit-record-fields button {
  margin-inline-start: 0.5rem;
}

.audit-record-detail {
  padding: 0.75rem;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface-soft);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>

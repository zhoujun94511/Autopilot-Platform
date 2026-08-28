<script setup lang="ts">
defineOptions({ name: "AuditPanel" });

import { storeToRefs } from "pinia";
import { computed, watch } from "vue";
import type { AuditLog } from "../api";
import { listAuditsPage, OPS_LIST_PAGE_SIZE } from "../api/opsLists";
import { useAuthStore } from "../stores/auth";
import { useCapabilities } from "../composables/useCapabilities";
import { usePagedList } from "../composables/usePagedList";
import { useAdminStore } from "../stores/adminStore";
import DataPager from "./common/DataPager.vue";
import { formatAuditRow } from "../utils/auditDisplay";

const auth = useAuthStore();
const { canManageUsers } = storeToRefs(auth);
const admin = useAdminStore();
const { auditsListVersion, auditFilter } = storeToRefs(admin);
const caps = useCapabilities();

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
  filterSources: [() => auditFilter.value.action, () => auditFilter.value.actor],
  isUnfiltered: () => !auditFilter.value.action.trim() && !auditFilter.value.actor.trim(),
});

const { items, total, page, pageSize, loading, hasLoaded, reload, setPage, setPageSize } = list;

watch(auditsListVersion, () => void reload(false));
void reload(true);

function applyFilter() {
  void reload(true);
}

const rows = computed(() =>
  items.value.map((a) => ({
    raw: a,
    display: formatAuditRow(a),
  })),
);
</script>

<template>
  <section v-if="canManageUsers" class="panel page-stack">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2>审计</h2>
        <p v-if="!caps.canOps" class="lede">只显示当前组织的操作记录。</p>
        <p v-else class="lede">按操作类型和操作人筛选记录。</p>
      </div>
      <div class="page-hero-actions">
        <button type="button" class="small" :disabled="loading" @click="applyFilter">刷新</button>
      </div>
    </header>

    <form class="audit-filter-form" @submit.prevent="applyFilter">
      <label>
        操作类型
        <input v-model="auditFilter.action" placeholder="例如：创建用户" />
      </label>
      <label>
        操作人
        <input v-model="auditFilter.actor" placeholder="操作人用户名" />
      </label>
      <button type="submit" class="primary">应用筛选</button>
    </form>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>时间</th>
            <th>动作</th>
            <th>操作者</th>
            <th>组织</th>
            <th>资源</th>
            <th>详情</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!rows.length && hasLoaded">
            <td class="empty" colspan="6">暂无审计记录</td>
          </tr>
          <tr v-for="{ raw, display } in rows" :key="raw.id">
            <td class="mono time-cell" :title="raw.created_at || ''">
              {{ display.time }}
            </td>
            <td>
              <span class="action-tag" :title="raw.action">{{ display.actionLabel }}</span>
            </td>
            <td>
              {{ raw.actor }}
              <span class="actor-kind-tag">{{ raw.actor_kind }}</span>
            </td>
            <td class="mono">{{ raw.org_id || "-" }}</td>
            <td class="mono">
              <template v-if="raw.resource_type">
                <span class="res-type">{{ display.resourceSummary }}</span>
                <button
                  v-if="raw.resource_id"
                  type="button"
                  class="small"
                  @click="admin.copyText(raw.resource_id)"
                >
                  复制 ID
                </button>
              </template>
              <span v-else>-</span>
            </td>
            <td class="audit-desc-cell" :title="raw.detail">{{ display.detailSummary }}</td>
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
  </section>
</template>

<style scoped>
.hint {
  font-size: 0.82rem;
  color: var(--muted);
  margin: 0 0 0.75rem;
}
.panel-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}
.panel-header-row h2 {
  margin: 0;
}
.audit-filter-form {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: flex-end;
  margin-bottom: 1rem;
  padding: 0.85rem;
  background: var(--surface-soft);
  border: 1px solid var(--line-soft);
  border-radius: 8px;
}
.audit-filter-form label {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  font-size: 0.78rem;
  color: var(--muted);
  min-width: 180px;
  flex: 1;
}
.time-cell {
  color: var(--muted);
  white-space: nowrap;
}
.action-tag {
  font-size: 0.72rem;
  font-weight: 700;
  background: var(--control-bg);
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
}
.actor-kind-tag {
  font-size: 0.65rem;
  margin-left: 0.35rem;
  color: var(--muted);
}
.res-type {
  font-size: 0.7rem;
  color: var(--info-soft-fg);
  margin-right: 0.35rem;
}
.audit-desc-cell {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
}
td.empty {
  text-align: center;
}
</style>

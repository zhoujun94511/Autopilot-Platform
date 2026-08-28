<script setup lang="ts">
import { ref, watch } from "vue";
import { listProjectsPage, PROJECT_LIST_PAGE_SIZE, type Project } from "../../api/projects";
import { storeToRefs } from "pinia";
import { useProjectsStore } from "../../stores/projectsStore";
import { useAdminStore } from "../../stores/adminStore";
import { useCapabilities } from "../../composables/useCapabilities";
import { usePagedList } from "../../composables/usePagedList";
import DataPager from "../common/DataPager.vue";

const emit = defineEmits<{ create: []; "configure-org": [] }>();
const projectsStore = useProjectsStore();
const admin = useAdminStore();
const { filterOrgId, filterProjectId, orgs, projects } = storeToRefs(projectsStore);

const caps = useCapabilities();

const searchQ = ref("");

const orgId = () => (filterOrgId.value || "").trim();

const list = usePagedList<Project>({
  immediate: false,
  pageSize: PROJECT_LIST_PAGE_SIZE,
  fetchPage: ({ page, pageSize }) =>
    listProjectsPage(orgId() || undefined, {
      page,
      pageSize,
      q: searchQ.value.trim() || undefined,
    }),
  resetSources: [() => filterOrgId.value, () => projects.value.length],
});

const { items, total, page, pageSize, loading, hasLoaded, reload, setPage, setPageSize } = list;

const currentOrgName = () => {
  const oid = orgId();
  if (!oid) return "";
  const hit = orgs.value.find((o) => o.id === oid);
  return hit?.name || oid;
};

function onSelect(id: string) {
  projectsStore.selectProject(id);
}

function isSelected(id: string) {
  return (filterProjectId.value || "").trim() === id;
}

void reload(true);
watch(
  () => filterOrgId.value,
  () => void reload(true),
);
watch(
  () => projects.value.length,
  () => void reload(true),
);
let searchTimer: ReturnType<typeof setTimeout> | undefined;
watch(searchQ, () => {
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(() => void reload(true), 280);
});

defineExpose({ reload });
</script>

<template>
  <section class="surface-card project-list">
    <div class="card-title-row">
      <h3>我的项目</h3>
      <span class="count-chip">{{ total || (loading ? "…" : 0) }}</span>
    </div>
    <p class="list-hint">
      <template v-if="orgId()">
        列表已按顶栏组织「{{ currentOrgName() }}」过滤；选用后设计域读写会落到该空间。
      </template>
      <template v-else-if="caps.canManageAnyOrg">
        顶栏为「全部组织」：显示你可见的项目（分页浏览）。新建项目前请先选定具体组织 / 事业部。
      </template>
      <template v-else>
        顶栏为「全部组织」：显示你已加入的项目（分页浏览）。可在顶栏选定组织以缩小范围。
      </template>
    </p>

    <label class="search-row">
      搜索
      <input
        v-model="searchQ"
        type="search"
        placeholder="项目 ID 或名称"
        autocomplete="off"
      />
    </label>

    <div v-if="!orgId() && caps.canManageAnyOrg" class="org-needed-banner">
      <p>新建项目需要组织归属。请先在顶栏选择，或前往组织设置。</p>
      <button type="button" class="small primary" @click="emit('configure-org')">
        先配置组织 / 事业部
      </button>
    </div>

    <div v-if="!hasLoaded" class="empty-state">加载中…</div>
    <div v-else-if="!items.length" class="empty-state">
      <template v-if="searchQ.trim()">
        <p class="empty-title">无匹配项目</p>
        <p class="empty-desc">请调整搜索词或清空搜索框。</p>
      </template>
      <template v-else-if="!orgId()">
        <p class="empty-title">还没有可读项目</p>
        <template v-if="caps.canManageAnyOrg">
          <p class="empty-desc">
            请先配置或选定组织 / 事业部，再创建归属该组织的项目；也可等待同事发来邀请。
          </p>
          <button type="button" class="primary small" @click="emit('configure-org')">
            先配置组织 / 事业部
          </button>
        </template>
        <p v-else class="empty-desc">
          请在顶栏选择已加入的组织，或等待管理员邀请你加入项目。组织无法自行创建。
        </p>
      </template>
      <template v-else>
        <p class="empty-title">当前组织下还没有项目</p>
        <p v-if="caps.canCreateProject" class="empty-desc">
          在本组织下新建空间，或请同事发邀请链接给你。
        </p>
        <p v-else class="empty-desc">
          本组织默认由负责人或管理员创建项目。你也可以等待同事发来邀请。
        </p>
        <button
          v-if="caps.canCreateProject"
          type="button"
          class="primary small"
          @click="emit('create')"
        >
          新建项目
        </button>
      </template>
    </div>

    <ul v-else class="proj-rows" role="listbox" aria-label="项目列表">
      <li
        v-for="p in items"
        :key="p.id"
        class="proj-row"
        :class="{ active: isSelected(p.id) }"
        role="option"
        :aria-selected="isSelected(p.id)"
        @click="onSelect(p.id)"
      >
        <div class="proj-main">
          <span class="proj-name">{{ p.name || "未命名" }}</span>
          <button
            type="button"
            class="id-chip mono"
            :title="p.id"
            @click.stop="admin.copyText(p.id)"
          >
            {{ p.id }}
          </button>
        </div>
        <div class="proj-meta">
          <span v-if="isSelected(p.id)" class="pill ok">当前选用</span>
          <button
            v-else
            type="button"
            class="small primary"
            @click.stop="onSelect(p.id)"
          >
            选用
          </button>
        </div>
      </li>
    </ul>

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
.project-list {
  padding: 1rem 1.05rem;
  min-width: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.project-list .proj-rows {
  flex: 1;
}

.list-hint {
  margin: -0.25rem 0 0.85rem;
  font-size: 0.78rem;
  color: var(--muted);
  line-height: 1.45;
}

.search-row {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin-bottom: 0.85rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--muted);
}

.org-needed-banner {
  margin-bottom: 0.85rem;
  padding: 0.65rem 0.75rem;
  border-radius: var(--radius-md);
  background: var(--surface-soft);
  border: 1px solid var(--border-weak);
  font-size: 0.82rem;
  color: var(--muted);
}

.org-needed-banner p {
  margin: 0 0 0.55rem;
}

.proj-rows {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.proj-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.65rem;
  padding: 0.55rem 0.65rem;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md);
  background: var(--surface-soft);
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}

.proj-row:hover {
  border-color: var(--line);
}

.proj-row.active {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.proj-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.proj-name {
  font-weight: 650;
  font-size: 0.88rem;
}

.id-chip {
  align-self: flex-start;
  appearance: none;
  border: none;
  background: none;
  padding: 0;
  font-size: 0.72rem;
  color: var(--mono);
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.proj-meta {
  flex-shrink: 0;
}
</style>

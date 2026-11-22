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
const { filterOrgId, filterProjectId, projects } = storeToRefs(projectsStore);

const caps = useCapabilities();

const searchQ = ref("");

const orgId = () => (filterOrgId.value || "").trim();

const list = usePagedList<Project>({
  pageSize: PROJECT_LIST_PAGE_SIZE,
  fetchPage: ({ page, pageSize }) =>
    listProjectsPage(orgId() || undefined, {
      page,
      pageSize,
      q: searchQ.value.trim() || undefined,
    }),
  resetSources: [() => filterOrgId.value, () => projects.value.length],
});

const { items, total, page, pageSize, loading, hasLoaded, error, reload, setPage, setPageSize } = list;

function onSelect(id: string) {
  projectsStore.selectProject(id);
}

function isSelected(id: string) {
  return (filterProjectId.value || "").trim() === id;
}

watch(searchQ, (_value, _oldValue, onCleanup) => {
  const searchTimer = setTimeout(() => void reload(true), 280);
  onCleanup(() => clearTimeout(searchTimer));
});

defineExpose({ reload });
</script>

<template>
  <section class="project-list" aria-labelledby="my-projects-heading">
    <div class="card-title-row">
      <h3 id="my-projects-heading">项目列表</h3>
      <span v-if="hasLoaded" class="meta-line">{{ total }} 个</span>
    </div>
    <input
      id="projects-search-input"
      v-model="searchQ"
      name="projects-search"
      class="search-row"
      type="search"
      aria-label="搜索项目"
      placeholder="项目 ID 或名称"
      autocomplete="off"
    />

    <div v-if="error" class="project-list-error" role="alert">
      <span>{{ error }}</span>
      <button type="button" class="linkish" @click="reload()">重试</button>
    </div>

    <div v-if="!hasLoaded" class="empty-state" role="status">加载中…</div>
    <div v-else-if="!items.length && !error" class="empty-state">
      <template v-if="searchQ.trim()">
        <p class="empty-title">无匹配项目</p>
        <p class="empty-desc">请调整搜索词或清空搜索框。</p>
      </template>
      <template v-else-if="!orgId()">
        <p class="empty-title">还没有可读项目</p>
        <template v-if="caps.canManageAnyOrg">
          <p class="empty-desc">
            选择组织后可以新建项目。
          </p>
          <button type="button" class="primary small" @click="emit('configure-org')">
            组织设置
          </button>
        </template>
        <p v-else class="empty-desc">
          组织无法自行创建，可联系管理员加入项目。
        </p>
      </template>
      <template v-else>
        <p class="empty-title">当前组织下还没有项目</p>
        <p v-if="!caps.canCreateProject" class="empty-desc">
          可联系组织管理员新建项目。
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

    <ul v-else-if="items.length" class="proj-rows" :aria-busy="loading">
      <li
        v-for="p in items"
        :key="p.id"
        class="proj-row"
        :class="{ active: isSelected(p.id) }"
      >
        <div class="proj-main">
          <button
            type="button"
            class="linkish proj-name"
            :aria-pressed="isSelected(p.id)"
            @click="onSelect(p.id)"
          >{{ p.name || p.id }}</button>
          <button
            type="button"
            class="linkish id-chip mono"
            :title="'复制 ' + p.id"
            @click="admin.copyText(p.id)"
          >
            {{ p.id }}
          </button>
        </div>
        <span v-if="isSelected(p.id)" class="proj-meta">当前项目</span>
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
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.search-row {
  margin: 0.65rem 0;
}

.project-list-error {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.82rem;
  color: var(--bad);
}

.proj-rows {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  border-top: 1px solid var(--line);
}

.proj-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.65rem;
  padding: 0.55rem 0.6rem;
  border-bottom: 1px solid var(--line);
}

.proj-row.active {
  background: var(--accent-soft);
}

.proj-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  overflow-wrap: anywhere;
}

.proj-name {
  font-weight: 650;
  font-size: 0.88rem;
  text-align: left;
}

.id-chip {
  font-size: 0.72rem;
  color: var(--mono);
  text-align: left;
}

.proj-meta {
  flex-shrink: 0;
  font-size: 0.72rem;
  color: var(--muted);
}
</style>

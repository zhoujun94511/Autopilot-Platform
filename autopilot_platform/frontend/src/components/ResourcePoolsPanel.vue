<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { apiErrorMessage } from "../api";
import {
  createResourcePool,
  deleteResourcePool,
  listResourcePoolCandidates,
  listResourcePoolsPage,
  setResourcePoolMember,
  setResourcePoolProject,
  updateResourcePool,
  type ResourcePool,
  type ResourcePoolCandidates,
} from "../api/resourcePools";
import { storeToRefs } from "pinia";
import { useProjectsStore } from "../stores/projectsStore";
import { useCapabilities } from "../composables/useCapabilities";
import { usePagedList } from "../composables/usePagedList";
import { confirmDialog, notify } from "../composables/useNotify";
import DataPager from "./common/DataPager.vue";

const POOL_PAGE_SIZE = 50;

const props = defineProps<{
  embedded?: boolean;
}>();

const projectsStore = useProjectsStore();
const { filterOrgId, orgs } = storeToRefs(projectsStore);
const caps = useCapabilities();
const candidates = ref<ResourcePoolCandidates | null>(null);
const modalOpen = ref(false);
const createMode = ref(false);
const selected = ref<ResourcePool | null>(null);
const form = ref({ name: "", description: "", is_default: false, enabled: true });
const formError = ref("");

const orgId = computed(() => (filterOrgId.value || "").trim());

const list = usePagedList<ResourcePool>({
  immediate: false,
  pageSize: POOL_PAGE_SIZE,
  fetchPage: ({ page, pageSize }) => {
    if (!orgId.value) {
      return Promise.resolve({ items: [], total: 0, page: 1, page_size: pageSize });
    }
    return listResourcePoolsPage(orgId.value, "", { page, pageSize });
  },
  resetSources: [orgId],
});

const { items: pools, total, page, pageSize, loading, hasLoaded, reload, setPage, setPageSize } = list;
const currentOrg = computed(() => orgs.value.find((item) => item.id === orgId.value));
const canManage = computed(() => {
  if (caps.canOps) return true;
  const role = currentOrg.value?.my_role;
  return role === "owner" || role === "admin";
});

async function loadCandidates() {
  if (!canManage.value || !orgId.value) return;
  try {
    candidates.value = await listResourcePoolCandidates(orgId.value);
  } catch (error) {
    candidates.value = null;
    notify(apiErrorMessage(error), "error");
  }
}

function openCreate() {
  createMode.value = true;
  selected.value = null;
  form.value = { name: "", description: "", is_default: false, enabled: true };
  formError.value = "";
  modalOpen.value = true;
}

async function openPool(pool: ResourcePool) {
  createMode.value = false;
  selected.value = pool;
  form.value = {
    name: pool.name,
    description: pool.description,
    is_default: pool.is_default,
    enabled: pool.enabled,
  };
  formError.value = "";
  modalOpen.value = true;
  await loadCandidates();
}

async function savePool() {
  formError.value = "";
  if (!orgId.value || !form.value.name.trim()) {
    formError.value = "请填写设备池名称";
    return;
  }
  try {
    const body = { ...form.value, name: form.value.name.trim() };
    const out = createMode.value
      ? await createResourcePool(orgId.value, body)
      : await updateResourcePool(selected.value!.id, body);
    selected.value = out;
    createMode.value = false;
    notify("设备池已保存", "success");
    await reload(false);
    await loadCandidates();
  } catch (error) {
    notify(apiErrorMessage(error), "error");
  }
}

async function removePool(pool: ResourcePool) {
  if (
    !(await confirmDialog(`删除设备池「${pool.name}」？其中的设备和项目授权会一并解除。`, {
      title: "删除设备池",
      okText: "删除",
      danger: true,
    }))
  ) {
    return;
  }
  try {
    await deleteResourcePool(pool.id);
    modalOpen.value = false;
    notify("设备池已删除", "success");
    await reload();
  } catch (error) {
    notify(apiErrorMessage(error), "error");
  }
}

function replacePool(out: ResourcePool) {
  selected.value = out;
  void reload(false);
}

async function toggleMember(
  kind: "runners" | "devices",
  resourceId: string,
  next: boolean,
) {
  if (!selected.value) return;
  try {
    replacePool(await setResourcePoolMember(selected.value.id, kind, resourceId, next));
  } catch (error) {
    notify(apiErrorMessage(error), "error");
  }
}

async function toggleProject(project: string, next: boolean) {
  if (!selected.value) return;
  try {
    replacePool(await setResourcePoolProject(selected.value.id, project, next));
  } catch (error) {
    notify(apiErrorMessage(error), "error");
  }
}

watch(orgId, () => void reload(true));
onMounted(() => void reload(true));
</script>

<template>
  <section class="panel pool-panel" :class="{ embedded: props.embedded }">
    <div class="panel-toolbar">
      <div class="panel-toolbar-left">
        <template v-if="!props.embedded">
          <h3 class="compact-title">设备池管理</h3>
          <p class="panel-toolbar-desc">按组织划定设备范围，再授权给项目使用；设备本身不绑某个项目</p>
        </template>
      </div>
      <button v-if="canManage && orgId" type="button" class="primary" @click="openCreate">
        新建设备池
      </button>
    </div>

    <div v-if="!orgId" class="empty-state">
      <template v-if="caps.canOps">
        <p class="empty-title">资源池按组织管理</p>
        <p class="empty-desc">
          此页用于把设备<strong>授权给项目</strong>，不是「在线设备」列表。
          查看全部已注册设备请切换到「在线设备」；管理资源池请在顶栏选择一个组织。
        </p>
      </template>
      <template v-else>
        <p class="empty-title">请先选择组织</p>
        <p class="empty-desc">请先在顶栏选择组织。设备池按组织划分，授权后项目才能使用。</p>
      </template>
    </div>
    <div v-else-if="!hasLoaded" class="empty-state">正在加载设备池…</div>
    <div v-else-if="!pools.length" class="empty-state">
      <p class="empty-title">暂无可见设备池</p>
      <p class="empty-desc">
        {{ canManage ? "创建后把设备加入池，再按需授权给项目使用。" : "当前组织下还没有对你可见的设备池。" }}
      </p>
    </div>
    <div v-else class="pool-grid">
      <article v-for="pool in pools" :key="pool.id" class="pool-card">
        <div class="pool-card-head">
          <div>
            <h4>{{ pool.name }}</h4>
            <p>{{ pool.description || "无描述" }}</p>
          </div>
          <span class="pill" :class="pool.enabled ? 'ok' : ''">
            {{ pool.enabled ? "启用" : "停用" }}
          </span>
        </div>
        <div class="pool-stats">
          <span>Runner {{ pool.runner_ids.length }}</span>
          <span>设备 {{ pool.device_ids.length }}</span>
          <span>项目 {{ pool.project_ids.length }}</span>
          <span v-if="pool.is_default">默认标记</span>
        </div>
        <button type="button" class="small" @click="openPool(pool)">
          {{ pool.can_manage ? "管理成员与授权" : "查看详情" }}
        </button>
      </article>
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

  <div v-if="modalOpen" class="modal-backdrop" @click.self="modalOpen = false">
    <section class="pool-dialog" role="dialog" aria-modal="true" aria-label="设备池管理">
      <header class="dialog-head">
        <div>
          <h3>{{ createMode ? "新建设备池" : selected?.name }}</h3>
          <p>默认池仅作标记；Runner、设备和项目都需手动加入。</p>
        </div>
        <button type="button" class="ghost" aria-label="关闭" @click="modalOpen = false">×</button>
      </header>

      <div v-if="canManage" class="dialog-section form-grid">
        <label>
          名称
          <input v-model="form.name" maxlength="128" />
          <span v-if="formError" class="ap-field-error" role="alert">{{ formError }}</span>
        </label>
        <label>
          描述
          <input v-model="form.description" maxlength="2000" />
        </label>
        <label class="check-row"><input v-model="form.enabled" type="checkbox" /> 启用调度</label>
        <label class="check-row"><input v-model="form.is_default" type="checkbox" /> 默认标记</label>
        <button type="button" class="primary" :disabled="loading" @click="savePool">保存</button>
      </div>

      <template v-if="!createMode && selected">
        <div class="dialog-section">
          <h4>已授权项目</h4>
          <div v-if="canManage && candidates" class="choice-grid">
            <label v-for="project in candidates.projects" :key="project.id" class="choice">
              <input
                type="checkbox"
                :checked="selected.project_ids.includes(project.id)"
                @change="toggleProject(project.id, !selected!.project_ids.includes(project.id))"
              />
              <span>{{ project.name }} <small>{{ project.id }}</small></span>
            </label>
          </div>
          <div v-else class="tag-row">
            <span v-for="id in selected.project_ids" :key="id" class="pill">{{ id }}</span>
            <span v-if="!selected.project_ids.length" class="muted">尚未授权项目</span>
          </div>
        </div>

        <div class="dialog-section">
          <h4>Runner 成员</h4>
          <div v-if="canManage && candidates" class="choice-grid">
            <label v-for="runner in candidates.runners" :key="runner.runner_id" class="choice">
              <input
                type="checkbox"
                :checked="selected.runner_ids.includes(runner.runner_id)"
                @change="
                  toggleMember(
                    'runners',
                    runner.runner_id,
                    !selected!.runner_ids.includes(runner.runner_id),
                  )
                "
              />
              <span>
                {{ runner.runner_id }}
                <small>{{ runner.online ? "在线" : "未心跳" }} · {{ runner.hostname }}</small>
              </span>
            </label>
          </div>
          <div v-else class="tag-row">
            <span v-for="id in selected.runner_ids" :key="id" class="pill">{{ id }}</span>
          </div>
        </div>

        <div class="dialog-section">
          <h4>单设备成员</h4>
          <div v-if="canManage && candidates" class="choice-grid">
            <label v-for="device in candidates.devices" :key="device.id" class="choice">
              <input
                type="checkbox"
                :checked="selected.device_ids.includes(device.id)"
                @change="
                  toggleMember('devices', device.id, !selected!.device_ids.includes(device.id))
                "
              />
              <span>
                {{ device.name || device.udid }}
                <small>{{ device.platform }} · {{ device.runner_id }} · {{ device.udid }}</small>
              </span>
            </label>
          </div>
          <p v-else class="muted">已绑定 {{ selected.device_ids.length }} 台设备</p>
        </div>

        <footer v-if="canManage" class="dialog-actions">
          <button type="button" class="danger" @click="removePool(selected)">删除设备池</button>
          <button type="button" @click="modalOpen = false">完成</button>
        </footer>
      </template>
    </section>
  </div>
</template>

<style scoped>
.pool-panel {
  border: none;
  box-shadow: none;
  background: transparent;
  padding: 0;
}
.compact-title {
  margin: 0;
  font-size: 0.95rem;
}
.pool-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 0.85rem;
}
.pool-card {
  padding: 1rem;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--surface-primary);
  box-shadow: var(--panel-shadow);
}
.pool-card-head {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
}
.pool-card h4,
.dialog-head h3,
.dialog-section h4 {
  margin: 0;
}
.pool-card p,
.dialog-head p {
  margin: 0.25rem 0 0;
  color: var(--muted);
  font-size: 0.78rem;
}
.pool-stats,
.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin: 0.85rem 0;
}
.pool-stats span {
  padding: 0.2rem 0.45rem;
  border-radius: 999px;
  background: var(--chip-bg);
  color: var(--muted);
  font-size: 0.72rem;
}
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1100;
  display: grid;
  place-items: center;
  padding: 1rem;
  background: rgb(0 0 0 / 52%);
}
.pool-dialog {
  width: min(900px, 96vw);
  max-height: 90vh;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--surface-primary);
  box-shadow: var(--panel-shadow);
}
.dialog-head,
.dialog-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  padding: 1rem 1.15rem;
}
.dialog-section {
  padding: 1rem 1.15rem;
  border-top: 1px solid var(--line-soft);
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem;
}
.form-grid label:not(.check-row) {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  color: var(--muted);
  font-size: 0.75rem;
}
.check-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.choice-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 0.5rem;
  margin-top: 0.65rem;
}
.choice {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.55rem;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
  background: var(--surface-soft);
  font-size: 0.8rem;
}
.choice span,
.choice small {
  display: block;
  min-width: 0;
  word-break: break-all;
}
.choice small,
.muted {
  color: var(--muted);
}
.dialog-actions {
  border-top: 1px solid var(--line-soft);
}
@media (max-width: 640px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>

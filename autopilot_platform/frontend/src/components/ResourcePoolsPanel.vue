<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
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
import ApModal from "./ApModal.vue";
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
const actionError = ref("");
const candidateError = ref("");
const saving = ref(false);
const candidatesLoading = ref(false);
const poolName = ref<HTMLInputElement | null>(null);
let editorVersion = 0;


const orgId = computed(() => (filterOrgId.value || "").trim());

const list = usePagedList<ResourcePool>({
  pageSize: POOL_PAGE_SIZE,
  fetchPage: ({ page, pageSize }) => {
    if (!orgId.value) {
      return Promise.resolve({ items: [], total: 0, page: 1, page_size: pageSize });
    }
    return listResourcePoolsPage(orgId.value, "", { page, pageSize });
  },
  resetSources: [orgId],
});

const { items: pools, total, page, pageSize, loading, hasLoaded, error, reload, setPage, setPageSize } = list;
const currentOrg = computed(() => orgs.value.find((item) => item.id === orgId.value));
const canManage = computed(() => {
  if (caps.canOps) return true;
  const role = currentOrg.value?.my_role;
  return role === "owner" || role === "admin";
});

const canEditPool = computed(() => canManage.value && (createMode.value || Boolean(selected.value?.can_manage)));

function resetEditorFeedback() {
  formError.value = "";
  actionError.value = "";
  candidateError.value = "";
  candidates.value = null;
  candidatesLoading.value = false;
}

function closeEditor() {
  editorVersion += 1;
  modalOpen.value = false;
  saving.value = false;
  resetEditorFeedback();
}

async function loadCandidates() {
  if (!canEditPool.value || !orgId.value) return;
  const version = editorVersion;
  const organization = orgId.value;
  candidatesLoading.value = true;
  candidateError.value = "";
  try {
    const nextCandidates = await listResourcePoolCandidates(organization);
    if (version === editorVersion) candidates.value = nextCandidates;
  } catch (error) {
    if (version === editorVersion) candidateError.value = apiErrorMessage(error);
  } finally {
    if (version === editorVersion) candidatesLoading.value = false;
  }
}

function openCreate() {
  if (!canManage.value || !orgId.value) return;
  createMode.value = true;
  selected.value = null;
  form.value = { name: "", description: "", is_default: false, enabled: true };
  resetEditorFeedback();
  modalOpen.value = true;
}

function openPool(pool: ResourcePool) {
  if (pool.org_id !== orgId.value) return;
  createMode.value = false;
  selected.value = pool;
  form.value = {
    name: pool.name,
    description: pool.description,
    is_default: pool.is_default,
    enabled: pool.enabled,
  };
  resetEditorFeedback();
  modalOpen.value = true;
  void loadCandidates();
}

async function applyPoolChange(change: () => Promise<void>) {
  if (!canEditPool.value || saving.value) return;
  const version = editorVersion;
  saving.value = true;
  actionError.value = "";
  try {
    await change();
  } catch (error) {
    if (version === editorVersion) actionError.value = apiErrorMessage(error);
  } finally {
    if (version === editorVersion) saving.value = false;
  }
}

async function savePool() {
  formError.value = "";
  if (!orgId.value || !form.value.name.trim()) {
    formError.value = "请填写设备池名称";
    await nextTick();
    poolName.value?.focus();
    return;
  }
  await applyPoolChange(async () => {
    const version = editorVersion;
    const body = { ...form.value, name: form.value.name.trim() };
    const out = createMode.value
      ? await createResourcePool(orgId.value, body)
      : await updateResourcePool(selected.value!.id, body);
    if (version !== editorVersion) return;
    selected.value = out;
    createMode.value = false;
    notify("设备池已保存", "success");
    await reload(false);
    if (version === editorVersion) await loadCandidates();
  });
}

async function removePool(pool: ResourcePool) {
  const version = editorVersion;
  if (
    !(await confirmDialog(`删除设备池「${pool.name}」？其中的设备和项目授权会一并解除。`, {
      title: "删除设备池",
      okText: "删除",
      danger: true,
    }))
  ) return;
  if (version !== editorVersion) return;
  await applyPoolChange(async () => {
    await deleteResourcePool(pool.id);
    if (version !== editorVersion) return;
    closeEditor();
    notify("设备池已删除", "success");
    await reload();
  });
}

async function toggleAssignment(event: Event, retained: boolean, change: (next: boolean) => Promise<ResourcePool>) {
  const input = event.currentTarget as HTMLInputElement;
  const next = input.checked;
  input.checked = retained;
  await applyPoolChange(async () => {
    const version = editorVersion;
    const pool = await change(next);
    if (version !== editorVersion) return;
    selected.value = pool;
    void reload(false);
  });
}

watch(orgId, closeEditor);
</script>

<template>
  <section class="page-stack pool-panel" aria-label="设备池">
    <header class="page-hero">
      <div>
        <h2 v-if="!props.embedded">设备池</h2>
        <p class="pool-scope">
          <strong v-if="currentOrg">{{ currentOrg.name }} · </strong>
          按组织管理设备范围并授权给项目。设备本身不绑某个项目。
        </p>
      </div>
      <div v-if="canManage && orgId" class="page-hero-actions">
        <button type="button" class="primary" @click="openCreate">新建设备池</button>
      </div>
    </header>
    <p class="pool-scope-note" aria-hidden="true">不是「在线设备」列表</p>

    <div v-if="!orgId" class="empty-state">
      <p class="empty-title">请选择组织</p>
      <p class="empty-desc">在顶栏选择组织后，即可查看设备池和项目授权。</p>
    </div>
    <template v-else>
      <div v-if="error" class="pool-list-error" role="alert">
        <span>无法加载设备池。{{ error }}</span>
        <button type="button" class="small" @click="reload(false)">重试</button>
      </div>
      <div v-if="!hasLoaded" class="empty-state" role="status">正在加载设备池…</div>
      <div v-else-if="!pools.length && !error" class="empty-state">
        <p class="empty-title">暂无可见设备池</p>
        <p class="empty-desc">
          {{ canManage ? "创建后把设备加入池，再按需授权给项目使用。" : "当前组织下还没有对你可见的设备池。" }}
        </p>
      </div>
      <div v-else-if="pools.length" class="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">设备池</th>
              <th scope="col">调度</th>
              <th scope="col">执行节点</th>
              <th scope="col">设备</th>
              <th scope="col">授权项目</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="pool in pools" :key="pool.id">
              <td class="pool-name">
                <strong>{{ pool.name }}</strong>
                <span v-if="pool.is_default" class="pool-default">默认</span>
                <small v-if="pool.description">{{ pool.description }}</small>
              </td>
              <td><span class="pill" :class="pool.enabled ? 'ok' : ''">{{ pool.enabled ? "启用" : "停用" }}</span></td>
              <td class="pool-count">{{ pool.runner_ids.length }}</td>
              <td class="pool-count">{{ pool.device_ids.length }}</td>
              <td class="pool-count">{{ pool.project_ids.length }}</td>
              <td><button type="button" class="small" @click="openPool(pool)">{{ pool.can_manage ? "管理" : "查看" }}</button></td>
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
    </template>
  </section>

  <ApModal
    v-if="modalOpen"
    :title="createMode ? '新建设备池' : selected?.name || '设备池'"
    :description="createMode ? undefined : '默认池仅作标记。执行节点、设备及项目授权分别维护。'"
    :wide="createMode"
    :xwide="!createMode"
    :close-on-backdrop="!saving"
    :close-on-esc="!saving"
    @close="closeEditor"
  >
    <form v-if="canEditPool" id="pool-edit-form" class="pool-form" novalidate @submit.prevent="savePool">
      <label>
        <span>名称（必填）</span>
        <input ref="poolName" v-model="form.name" name="name" maxlength="128" required data-autofocus
          :disabled="saving" :aria-invalid="Boolean(formError)"
          :aria-describedby="formError ? 'pool-name-error' : undefined" @input="formError = ''" />
        <span v-if="formError" id="pool-name-error" class="ap-field-error" role="alert">{{ formError }}</span>
      </label>
      <label>
        <span>描述</span>
        <input v-model="form.description" name="description" maxlength="2000" :disabled="saving" />
      </label>
      <label class="pool-check"><input v-model="form.enabled" type="checkbox" :disabled="saving" /> 启用调度</label>
      <label class="pool-check"><input v-model="form.is_default" type="checkbox" :disabled="saving" /> 默认标记</label>
    </form>
    <div v-if="selected && !canEditPool" class="pool-description">
      <p>{{ selected.description || "暂无描述" }}</p>
      <p>调度{{ selected.enabled ? "已启用" : "已停用" }}{{ selected.is_default ? " · 默认池" : "" }}</p>
    </div>
    <p v-if="actionError" class="ap-field-error" role="alert">{{ actionError }}</p>
    <template v-if="!createMode && selected">
      <p v-if="candidatesLoading" role="status">正在加载可关联资源…</p>
      <div v-if="candidateError" class="pool-list-error" role="alert">
        <span>无法加载可关联资源。{{ candidateError }}</span>
        <button type="button" class="small" :disabled="saving" @click="loadCandidates">重试</button>
      </div>
      <section class="pool-group">
        <h4>已授权项目</h4>
        <div v-if="canEditPool && candidates?.projects.length" class="pool-choices">
          <label v-for="project in candidates.projects" :key="project.id" class="pool-check">
            <input type="checkbox" :disabled="saving" :checked="selected.project_ids.includes(project.id)"
              @change="toggleAssignment($event, selected!.project_ids.includes(project.id), (next) => setResourcePoolProject(selected!.id, project.id, next))" />
            <span>{{ project.name }}<small>{{ project.id }}</small></span>
          </label>
        </div>
        <p v-else>{{ selected.project_ids.join("、") || "尚未授权项目" }}</p>
      </section>
      <section class="pool-group">
        <h4>执行节点</h4>
        <div v-if="canEditPool && candidates?.runners.length" class="pool-choices">
          <label v-for="runner in candidates.runners" :key="runner.runner_id" class="pool-check">
            <input type="checkbox" :disabled="saving" :checked="selected.runner_ids.includes(runner.runner_id)"
              @change="toggleAssignment($event, selected!.runner_ids.includes(runner.runner_id), (next) => setResourcePoolMember(selected!.id, 'runners', runner.runner_id, next))" />
            <span>{{ runner.runner_id }}<small>{{ runner.online ? "在线" : "未心跳" }} · {{ runner.hostname }}</small></span>
          </label>
        </div>
        <p v-else>{{ selected.runner_ids.join("、") || "尚未绑定执行节点" }}</p>
      </section>
      <section class="pool-group">
        <h4>单设备成员</h4>
        <div v-if="canEditPool && candidates?.devices.length" class="pool-choices">
          <label v-for="device in candidates.devices" :key="device.id" class="pool-check">
            <input type="checkbox" :disabled="saving" :checked="selected.device_ids.includes(device.id)"
              @change="toggleAssignment($event, selected!.device_ids.includes(device.id), (next) => setResourcePoolMember(selected!.id, 'devices', device.id, next))" />
            <span>{{ device.name || device.udid }}<small>{{ device.platform }} · {{ device.runner_id }} · {{ device.udid }}</small></span>
          </label>
        </div>
        <p v-else>已绑定 {{ selected.device_ids.length }} 台设备</p>
      </section>
    </template>
    <template #actions>
      <button v-if="canEditPool && selected" type="button" class="danger pool-delete" :disabled="saving"
        @click="removePool(selected)">删除设备池</button>
      <button type="button" :disabled="saving" @click="closeEditor">关闭</button>
      <button v-if="canEditPool" type="submit" form="pool-edit-form" class="primary" :disabled="saving">
        {{ saving ? "处理中…" : "保存" }}
      </button>
    </template>
  </ApModal>
</template>

<style scoped>
.pool-panel, .pool-form, .pool-group, .pool-check span {
  min-width: 0;
}

.pool-scope, .pool-group p, .pool-description {
  margin: 0;
  color: var(--muted);
  font-size: var(--font-size-meta);
  overflow-wrap: anywhere;
}

.pool-name {
  min-width: 170px;
  max-width: 420px;
  overflow-wrap: anywhere;
}

.pool-name small, .pool-check small {
  display: block;
  color: var(--muted);
  font-size: var(--font-size-meta);
}

.pool-default {
  color: var(--muted);
  margin-inline-start: var(--space-2);
  font-size: var(--font-size-meta);
}

.pool-count {
  font-variant-numeric: tabular-nums;
}

.pool-form, .pool-choices {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-2) var(--space-4);
}

.pool-form > label:not(.pool-check) {
  display: grid;
  gap: var(--space-1);
}

.pool-group {
  padding-block: var(--space-3);
  border-top: 1px solid var(--line);
}

.pool-group h4 {
  margin: 0 0 var(--space-2);
}

.pool-check, .pool-list-error {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  overflow-wrap: anywhere;
}

.pool-check input {
  flex-shrink: 0;
}

.pool-list-error {
  flex-wrap: wrap;
  align-items: center;
  color: var(--danger-soft-fg);
}

.pool-delete {
  margin-inline-end: auto;
}

@media (max-width: 640px) {
  .pool-form, .pool-choices {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>

<script setup lang="ts">
import { computed, ref } from "vue";
import {
  createProjectInvite,
  listProjectInvitesPage,
  revokeProjectInvite,
  PROJECT_INVITE_PAGE_SIZE,
  type ProjectInvite,
} from "../../api/projectInvites";
import { apiErrorMessage } from "../../api";
import { storeToRefs } from "pinia";
import { useProjectsStore } from "../../stores/projectsStore";
import { useAdminStore } from "../../stores/adminStore";
import { usePagedList } from "../../composables/usePagedList";
import { confirmDialog, notify } from "../../composables/useNotify";
import ApSelect from "../common/ApSelect.vue";
import DataPager from "../common/DataPager.vue";
import { PROJECT_ROLE_LABEL, projectRoleLabel } from "./roleLabels";

const props = withDefaults(
  defineProps<{
    /** 固定项目上下文；不传则回退 store 当前选用 */
    projectId?: string;
    /** 嵌入工作台时去掉外层「表单卡」外壳 */
    embedded?: boolean;
  }>(),
  { projectId: "", embedded: false },
);

const projectsStore = useProjectsStore();
const admin = useAdminStore();
const { memberForm, filterProjectId } = storeToRefs(projectsStore);

const busy = ref(false);
const error = ref("");
const msg = ref("");
const role = ref("member");
const label = ref("");
const expiresHours = ref(168);
const maxUses = ref(0);

const resolvedProjectId = computed(() =>
  (props.projectId || memberForm.value.project_id || filterProjectId.value || "").trim(),
);

const inviteList = usePagedList<ProjectInvite>({
  pageSize: PROJECT_INVITE_PAGE_SIZE,
  immediate: true,
  resetSources: [resolvedProjectId],
  fetchPage: async ({ page, pageSize }) => {
    const pid = resolvedProjectId.value;
    if (!pid) return { items: [], total: 0, page: 1, page_size: pageSize };
    return listProjectInvitesPage(pid, { page, pageSize });
  },
});

const {
  items: invites,
  total: inviteTotal,
  page: invitePage,
  pageSize: invitePageSize,
  loading,
  hasLoaded,
  reload: reloadInvites,
  setPage: setInvitePage,
  setPageSize: setInvitePageSize,
} = inviteList;

const activeCount = computed(() => invites.value.filter((i) => !i.revoked).length);

async function reload() {
  await reloadInvites(true);
}

async function onCreate() {
  const pid = resolvedProjectId.value;
  if (!pid) {
    error.value = "请先选用项目空间";
    return;
  }
  busy.value = true;
  error.value = "";
  msg.value = "";
  try {
    const inv = await createProjectInvite(pid, {
      role: role.value,
      label: label.value,
      expires_hours: Number(expiresHours.value) || 0,
      max_uses: Number(maxUses.value) || 0,
    });
    msg.value = `已创建邀请：${window.location.origin}${inv.invite_path}`;
    label.value = "";
    await reload();
  } catch (e) {
    error.value = apiErrorMessage(e);
  } finally {
    busy.value = false;
  }
}

async function onRevoke(id: string) {
  const pid = resolvedProjectId.value;
  if (
    !pid ||
    !(await confirmDialog("撤销该邀请？", {
      danger: true,
    }))
  )
    return;
  busy.value = true;
  error.value = "";
  try {
    await revokeProjectInvite(pid, id);
    await reload();
    notify("已撤销邀请", "success");
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  } finally {
    busy.value = false;
  }
}

function copyLink(inv: ProjectInvite) {
  const url = `${window.location.origin}${inv.invite_path}`;
  admin.copyText(url);
}
</script>

<template>
  <div class="invite-block" :class="{ embedded }">
    <div class="card-title-row">
      <h4>邀请管理</h4>
      <span class="count-chip">{{ activeCount }} 有效</span>
    </div>
    <p class="hint">发给同事：已有账号可登录接受；新人可自助注册并加入（普通用户）。</p>

    <form class="invite-form" @submit.prevent="onCreate">
      <div class="form-row">
        <label>
          入项角色
          <ApSelect
            v-model="role"
            aria-label="入项角色"
            :options="[
              { value: 'member', label: PROJECT_ROLE_LABEL.member },
              { value: 'viewer', label: PROJECT_ROLE_LABEL.viewer },
            ]"
          />
        </label>
        <label>
          有效小时（0=不过期）
          <input v-model.number="expiresHours" type="number" min="0" />
        </label>
        <label>
          次数上限（0=不限）
          <input v-model.number="maxUses" type="number" min="0" />
        </label>
      </div>
      <label class="full">
        备注
        <input v-model="label" placeholder="可选，如「外包协作」" />
      </label>
      <button type="submit" class="primary" :disabled="busy || !resolvedProjectId">创建邀请链接</button>
    </form>
    <p v-if="msg" class="msg ok">{{ msg }}</p>
    <p v-if="error" class="msg bad">{{ error }}</p>

    <div class="table-wrap" style="margin-top: 0.85rem">
      <table>
        <thead>
          <tr>
            <th>角色</th>
            <th>备注</th>
            <th>使用</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!resolvedProjectId">
            <td class="empty" colspan="5">请先选用项目空间</td>
          </tr>
          <tr v-else-if="!hasLoaded">
            <td class="empty" colspan="5">加载中…</td>
          </tr>
          <tr v-else-if="!invites.length">
            <td class="empty" colspan="5">暂无邀请</td>
          </tr>
          <tr v-for="inv in invites" :key="inv.id">
            <td>{{ projectRoleLabel(inv.role) }}</td>
            <td>{{ inv.label || "—" }}</td>
            <td class="mono">{{ inv.use_count }}{{ inv.max_uses ? ` / ${inv.max_uses}` : "" }}</td>
            <td>
              <span class="pill" :class="inv.revoked ? 'bad' : 'ok'">
                {{ inv.revoked ? "已撤销" : "有效" }}
              </span>
            </td>
            <td class="row-actions">
              <button type="button" class="small" :disabled="inv.revoked" @click="copyLink(inv)">
                复制链接
              </button>
              <button
                type="button"
                class="small danger"
                :disabled="inv.revoked || busy"
                @click="onRevoke(inv.id)"
              >
                撤销
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <DataPager
      mode="page"
      :total="inviteTotal"
      :page="invitePage"
      :page-size="invitePageSize"
      :loading="loading"
      @update:page="setInvitePage"
      @update:page-size="setInvitePageSize"
    />
  </div>
</template>

<style scoped>
.invite-block:not(.embedded) {
  background: var(--surface-soft);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  padding: 1rem 1.05rem;
}

.card-title-row h4 {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--text);
}

.hint {
  font-size: 0.78rem;
  color: var(--muted);
  margin: 0.35rem 0 0.85rem;
  line-height: 1.45;
}

.invite-form {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  padding: 0.75rem 0.85rem;
  background: var(--surface-soft);
  border: 1px solid var(--border-weak);
  border-radius: var(--radius-md);
}

.embedded .invite-form {
  background: var(--control-bg);
}

.form-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.65rem;
}

.invite-form label {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--muted);
  min-width: 0;
}

.invite-form label.full {
  width: 100%;
}

.msg {
  margin: 0.55rem 0 0;
  font-size: 0.82rem;
}

.msg.bad {
  color: var(--bad);
}

.pill.bad {
  background: var(--danger-soft-bg);
  color: var(--danger-soft-fg);
}

@media (max-width: 720px) {
  .form-row {
    grid-template-columns: 1fr;
  }
}
</style>

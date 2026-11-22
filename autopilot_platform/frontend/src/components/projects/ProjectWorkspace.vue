<script setup lang="ts">
import { computed, ref, watch } from "vue";
import {
  listProjectMembersPage,
  PROJECT_MEMBER_PAGE_SIZE,
  type ProjectMember,
} from "../../api/projects";
import { storeToRefs } from "pinia";
import { useProjectsStore } from "../../stores/projectsStore";
import { useAdminStore } from "../../stores/adminStore";
import { useCapabilities } from "../../composables/useCapabilities";
import { usePagedList } from "../../composables/usePagedList";
import { PROJECT_ROLE_LABEL, projectRoleLabel } from "./roleLabels";
import ProjectInviteCard from "./ProjectInviteCard.vue";
import DataPager from "../common/DataPager.vue";
import ApSelect from "../common/ApSelect.vue";
import ApModal from "../ApModal.vue";

const projectsStore = useProjectsStore();
const admin = useAdminStore();
const { filterProjectId, projects, memberForm, memberMsg } = storeToRefs(projectsStore);

const caps = useCapabilities();
const memberOpen = ref(false);
const savingMember = ref(false);
const invitesOpen = ref(false);

const projectId = computed(() => (filterProjectId.value || memberForm.value.project_id || "").trim());

const currentProject = computed(() => {
  const pid = projectId.value;
  if (!pid) return null;
  return projects.value.find((p) => p.id === pid) || { id: pid, name: pid };
});

/** 仅项目 owner（+ 平台 admin）可管成员/邀请 */
const canManage = computed(() => Boolean(caps.canManageProject));

const memberList = usePagedList<ProjectMember>({
  pageSize: PROJECT_MEMBER_PAGE_SIZE,
  fetchPage: ({ page, pageSize }) => {
    const pid = projectId.value;
    if (!pid) {
      return Promise.resolve({ items: [], total: 0, page: 1, page_size: pageSize });
    }
    return listProjectMembersPage(pid, { page, pageSize });
  },
  resetSources: [projectId],
});

const {
  items: members,
  total: memberTotal,
  page: memberPage,
  pageSize: memberPageSize,
  loading: loadingMembers,
  hasLoaded: hasLoadedMembers,
  error: memberError,
  reload: reloadMembers,
  setPage: setMemberPage,
  setPageSize: setMemberPageSize,
} = memberList;

watch(
  projectId,
  (pid) => {
    memberOpen.value = false;
    invitesOpen.value = false;
    memberMsg.value = "";
    if (pid && memberForm.value.project_id !== pid) {
      memberForm.value.project_id = pid;
    }
  },
  { immediate: true },
);

watch(
  memberMsg,
  (msg) => {
    if (msg.startsWith("已")) void reloadMembers(false);
  },
);

function openMemberForm() {
  if (!canManage.value || !projectId.value) return;
  memberMsg.value = "";
  memberForm.value.username = "";
  memberForm.value.role = "member";
  memberOpen.value = true;
}

function closeMemberForm() {
  if (!savingMember.value) {
    memberOpen.value = false;
    if (!memberMsg.value.startsWith("已")) memberMsg.value = "";
  }
}

async function submitMember(event: Event) {
  if (!canManage.value || !projectId.value || savingMember.value) return;
  savingMember.value = true;
  memberMsg.value = "";
  try {
    await projectsStore.onAddMember(event);
    if (memberMsg.value.startsWith("已添加成员")) memberOpen.value = false;
  } finally {
    savingMember.value = false;
  }
}
</script>

<template>
  <section class="workspace" aria-label="项目工作区">
    <template v-if="!projectId">
      <div class="empty-state workspace-empty">
        <p class="empty-title">请选择项目</p>
        <p class="empty-desc">从项目列表选择。</p>
      </div>
    </template>

    <template v-else>
      <header class="ws-head">
        <div class="ws-head-copy">
          <h3>{{ currentProject?.name || "未命名" }}</h3>
          <p class="meta-line">
            项目 ID
            <button type="button" class="link-id mono" @click="admin.copyText(projectId)">
              {{ projectId }}
            </button>
          </p>
        </div>
      </header>

      <div class="ws-section">
        <div class="member-heading">
          <h4>项目成员</h4>
          <span v-if="hasLoadedMembers" class="meta-line">{{ memberTotal }} 人</span>
          <button
            v-if="canManage"
            type="button"
            class="primary"
            @click="openMemberForm"
          >添加成员</button>
        </div>

        <p v-if="!canManage" class="meta-line readonly-hint">
          当前角色为{{ projectRoleLabel(caps.currentProjectRole) }}，管理成员请联系项目负责人。
        </p>
        <p
          v-if="memberMsg && !memberOpen"
          class="msg"
          :class="memberMsg.startsWith('已') ? 'ok' : 'bad'"
          :role="memberMsg.startsWith('已') ? 'status' : 'alert'"
        >
          {{ memberMsg }}
        </p>
        <p v-if="memberError" class="msg bad" role="alert">
          {{ memberError }}
          <button type="button" class="linkish" @click="reloadMembers()">重试</button>
        </p>
        <div class="table-wrap member-table">
          <table aria-label="项目成员" :aria-busy="loadingMembers">
            <thead>
              <tr>
                <th>用户名</th>
                <th>角色</th>
                <th>用户 ID</th>
                <th v-if="canManage">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!members.length">
                <td class="empty" :colspan="canManage ? 4 : 3">
                  {{ !hasLoadedMembers ? "加载中…" : memberError ? "未能加载成员" : "暂无项目成员" }}
                </td>
              </tr>
              <tr v-for="m in members" :key="m.user_id">
                <td>{{ m.username }}</td>
                <td>
                  <span class="pill" :class="m.role === 'owner' ? 'ok' : ''">
                    {{ projectRoleLabel(m.role) }}
                  </span>
                </td>
                <td class="mono">
                  <button type="button" class="small" @click="admin.copyText(m.user_id)">
                    {{ m.user_id.length > 8 ? m.user_id.slice(0, 8) + "…" : m.user_id }}
                  </button>
                </td>
                <td v-if="canManage">
                  <button type="button" class="small danger" @click="projectsStore.onRemoveMember(m.user_id)">
                    移除
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <DataPager
          v-if="memberTotal > 0"
          :total="memberTotal"
          :page="memberPage"
          :page-size="memberPageSize"
          :loading="loadingMembers"
          @update:page="setMemberPage"
          @update:page-size="setMemberPageSize"
        />
      </div>

      <details v-if="canManage" class="invite-section" :open="invitesOpen" @toggle="invitesOpen = ($event.target as HTMLDetailsElement).open">
        <summary>邀请管理</summary>
        <ProjectInviteCard v-if="invitesOpen" :key="projectId" :project-id="projectId" embedded />
      </details>
    </template>
  </section>

  <ApModal
    v-if="memberOpen && canManage && projectId"
    title="添加项目成员"
    :description="currentProject?.name"
    :close-on-esc="!savingMember"
    :close-on-backdrop="!savingMember"
    @close="closeMemberForm"
  >
    <form class="member-form" :aria-busy="savingMember" @submit.prevent="submitMember">
      <label>
        用户名
        <input v-model="memberForm.username" name="username" required :disabled="savingMember" data-autofocus />
      </label>
      <label>
        角色
        <ApSelect
          v-model="memberForm.role"
          aria-label="项目成员角色"
          :disabled="savingMember"
          :options="[
            { value: 'member', label: PROJECT_ROLE_LABEL.member },
            { value: 'viewer', label: PROJECT_ROLE_LABEL.viewer },
            { value: 'owner', label: PROJECT_ROLE_LABEL.owner },
          ]"
        />
      </label>
      <p v-if="memberMsg" class="msg bad" role="alert">{{ memberMsg }}</p>
      <footer class="ap-modal-actions">
        <button type="button" class="ghost" :disabled="savingMember" @click="closeMemberForm">取消</button>
        <button type="submit" class="primary" :disabled="savingMember">{{ savingMember ? "正在添加…" : "添加成员" }}</button>
      </footer>
    </form>
  </ApModal>
</template>

<style scoped>
.workspace {
  min-width: 0;
  min-height: 280px;
  display: flex;
  flex-direction: column;
}

.workspace-empty {
  flex: 1;
  margin: 0;
  min-height: 12rem;
}

.ws-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--line);
}

.ws-head h3 {
  margin: 0 0 0.25rem;
  font-size: 1.05rem;
  font-weight: 700;
}

.link-id {
  appearance: none;
  border: none;
  background: none;
  padding: 0;
  margin-left: 0.35rem;
  color: var(--mono);
  cursor: pointer;
  font: inherit;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.ws-section h4 {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--text);
}

.member-heading {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.65rem;
}

.member-heading > button {
  margin-inline-start: auto;
}

.member-table {
  margin: 0.65rem 0 0;
}

.member-form {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.member-form label {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--muted);
  min-width: 0;
}

.msg {
  margin: 0.55rem 0 0;
  font-size: 0.82rem;
}

.msg.bad {
  color: var(--bad);
}

.readonly-hint {
  margin: 0.75rem 0 0;
}

.invite-section {
  margin-top: 1rem;
  border-top: 1px solid var(--line);
}

.invite-section > summary {
  cursor: pointer;
  padding: 0.75rem 0;
  font-weight: 650;
}
</style>

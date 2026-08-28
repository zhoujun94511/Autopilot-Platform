<script setup lang="ts">
import { computed, watch } from "vue";
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

const projectsStore = useProjectsStore();
const admin = useAdminStore();
const { filterProjectId, projects, memberForm, memberMsg } = storeToRefs(projectsStore);

const caps = useCapabilities();

const projectId = computed(() => (filterProjectId.value || memberForm.value.project_id || "").trim());

const currentProject = computed(() => {
  const pid = projectId.value;
  if (!pid) return null;
  return projects.value.find((p) => p.id === pid) || { id: pid, name: pid };
});

/** 仅项目 owner（+ 平台 admin）可管成员/邀请 */
const canManage = computed(() => Boolean(caps.canManageProject));

const memberList = usePagedList<ProjectMember>({
  immediate: false,
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
  reload: reloadMembers,
  setPage: setMemberPage,
  setPageSize: setMemberPageSize,
} = memberList;

watch(
  projectId,
  (pid) => {
    if (pid && memberForm.value.project_id !== pid) {
      memberForm.value.project_id = pid;
    }
    void reloadMembers(true);
  },
  { immediate: true },
);

watch(
  memberMsg,
  (msg) => {
    if (msg.startsWith("已")) void reloadMembers(false);
  },
);
</script>

<template>
  <section class="surface-card workspace">
    <template v-if="!projectId">
      <div class="empty-state workspace-empty">
        <p class="empty-title">先选用一个项目</p>
        <p class="empty-desc">
          请先在顶栏选好组织，再从左侧点一个项目，在这里管理成员和邀请。
        </p>
      </div>
    </template>

    <template v-else>
      <header class="ws-head">
        <div class="ws-head-copy">
          <p class="ws-kicker">项目工作台</p>
          <h3>{{ currentProject?.name || "未命名" }}</h3>
          <p class="meta-line">
            空间 ID
            <button type="button" class="link-id mono" @click="admin.copyText(projectId)">
              {{ projectId }}
            </button>
          </p>
        </div>
        <span class="pill ok">当前上下文</span>
      </header>

      <div class="ws-section">
        <div class="card-title-row">
          <h4>空间成员</h4>
          <span class="count-chip">{{ memberTotal || (loadingMembers ? "…" : 0) }}</span>
        </div>

        <form v-if="canManage" class="add-member-bar" @submit.prevent="projectsStore.onAddMember">
          <label>
            用户名 *
            <input v-model="memberForm.username" required placeholder="alice" />
          </label>
          <label>
            角色 *
            <ApSelect
              v-model="memberForm.role"
              aria-label="项目成员角色"
              :options="[
                { value: 'member', label: PROJECT_ROLE_LABEL.member },
                { value: 'viewer', label: PROJECT_ROLE_LABEL.viewer },
                { value: 'owner', label: PROJECT_ROLE_LABEL.owner },
              ]"
            />
          </label>
          <button type="submit" class="primary">添加成员</button>
        </form>
        <p v-else class="meta-line readonly-hint">
          仅项目负责人可添加或移除成员。你当前角色：{{ projectRoleLabel(caps.currentProjectRole) }}。
        </p>
        <p v-if="memberMsg" class="msg" :class="memberMsg.startsWith('已') ? 'ok' : 'bad'">
          {{ memberMsg }}
        </p>

        <div class="table-wrap" style="margin-top: 0.75rem">
          <table>
            <thead>
              <tr>
                <th>用户名</th>
                <th>角色</th>
                <th>用户 ID</th>
                <th v-if="canManage">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!members.length && hasLoadedMembers">
                <td class="empty" :colspan="canManage ? 4 : 3">该空间暂无成员记录</td>
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
                    {{ m.user_id.slice(0, 8) }}…
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

      <div class="ws-divider" />

      <div class="ws-section">
        <ProjectInviteCard v-if="canManage" :project-id="projectId" embedded />
        <p v-else class="meta-line readonly-hint">邀请链接仅项目负责人可创建。</p>
      </div>
    </template>
  </section>
</template>

<style scoped>
.workspace {
  min-width: 0;
  min-height: 280px;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.workspace-empty {
  flex: 1;
  margin: 0;
  min-height: 16rem;
}

.ws-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 1.15rem;
  padding-bottom: 0.95rem;
  border-bottom: 1px solid var(--line);
}

.ws-kicker {
  margin: 0 0 0.2rem;
  font-size: 0.72rem;
  font-weight: 650;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--accent-text);
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

.add-member-bar {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) auto;
  gap: 0.65rem;
  align-items: end;
  margin-top: 0.75rem;
  padding: 0.75rem 0.85rem;
  background: var(--surface-soft);
  border: 1px solid var(--border-weak);
  border-radius: var(--radius-md);
}

.add-member-bar label {
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

.ws-divider {
  height: 1px;
  background: var(--line);
  margin: 1.25rem 0;
}

@media (max-width: 720px) {
  .add-member-bar {
    grid-template-columns: 1fr;
  }
}
</style>

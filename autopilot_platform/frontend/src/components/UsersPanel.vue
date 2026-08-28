<script setup lang="ts">
defineOptions({ name: "UsersPanel" });

import { computed, watch } from "vue";
import { storeToRefs } from "pinia";
import { listUsersPage, OPS_LIST_PAGE_SIZE, type PlatformUser } from "../api/opsLists";
import { useProjectsStore } from "../stores/projectsStore";
import { useAuthStore } from "../stores/auth";
import { useCapabilities } from "../composables/useCapabilities";
import { usePagedList } from "../composables/usePagedList";
import { useAdminStore } from "../stores/adminStore";
import DataPager from "./common/DataPager.vue";
import ApSelect from "./common/ApSelect.vue";
import { platformRoleLabel } from "./projects/roleLabels";

/** 会话/门禁仍走门面；管理域状态与动作直连 Pinia */
const projectsStore = useProjectsStore();
const { filterOrgId, filterProjectId, orgs, projects } = storeToRefs(projectsStore);
const auth = useAuthStore();
const { canManageUsers } = storeToRefs(auth);
const admin = useAdminStore();
const { usersListVersion, userMsg, userMsgOk } = storeToRefs(admin);
const userForm = admin.userForm;
const caps = useCapabilities();

const list = usePagedList<PlatformUser>({
  immediate: false,
  pageSize: OPS_LIST_PAGE_SIZE,
  fetchPage: ({ page, pageSize }) => listUsersPage({ page, pageSize }),
});

const { items, total, page, pageSize, loading, hasLoaded, reload, setPage, setPageSize } = list;

watch(usersListVersion, () => void reload(false));
void reload(true);

const orgName = computed(() => {
  const oid = (filterOrgId.value || "").trim();
  if (!oid) return "";
  return orgs.value.find((o) => o.id === oid)?.name || oid;
});

const projectName = computed(() => {
  const pid = (filterProjectId.value || "").trim();
  if (!pid) return "";
  return projects.value.find((p) => p.id === pid)?.name || pid;
});

const dutyOptions = computed(() => {
  const opts: { value: string; label: string }[] = [];
  const oid = (filterOrgId.value || "").trim();
  const pid = (filterProjectId.value || "").trim();
  if (pid) {
    opts.push(
      { value: "project_member", label: `加入「${projectName.value}」做事` },
      { value: "project_owner", label: `管「${projectName.value}」这个项目` },
      { value: "project_viewer", label: `只能看「${projectName.value}」` },
    );
  }
  if (oid) {
    opts.push({
      value: "org_member",
      label: pid ? "只加入组织，先不进项目" : `加入「${orgName.value}」`,
    });
    opts.push({
      value: "org_admin",
      label: `管「${orgName.value}」整个组织`,
    });
  } else {
    opts.push({ value: "user", label: "普通用户（先建账号）" });
  }
  if (caps.canOps) {
    opts.push({ value: "sys_admin", label: "系统管理员（能管全站）" });
  }
  return opts;
});

watch(
  dutyOptions,
  (opts) => {
    if (!opts.some((o) => o.value === userForm.duty)) {
      userForm.duty = opts[0]?.value || "user";
    }
  },
  { immediate: true },
);

function dutySuccess(username: string, duty: string): string {
  if (duty === "sys_admin") return `已创建系统管理员 ${username}`;
  if (duty === "org_admin") return `已创建 ${username}，并设为组织管理员`;
  if (duty === "project_owner") return `已创建 ${username}，并设为当前项目负责人`;
  if (duty === "project_viewer") return `已创建 ${username}，并设为当前项目只读`;
  if (duty === "project_member") return `已创建 ${username}，并加入当前项目`;
  if (duty === "org_member") return `已创建 ${username}，并加入当前组织`;
  return `已创建用户 ${username}`;
}

async function onSubmit(ev: Event) {
  const username = userForm.username.trim();
  const duty = userForm.duty || "user";
  await admin.onCreateUser(ev, {
    orgId: (filterOrgId.value || "").trim(),
    projectId: (filterProjectId.value || "").trim(),
  });
  if (userMsgOk.value) {
    userMsg.value = dutySuccess(username, duty);
  }
}
</script>
<template>
  <section v-if="canManageUsers" class="panel page-stack">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2>用户</h2>
        <p v-if="!caps.canOps" class="lede">
          新建账号会加入当前组织。下面一次选好这个人来干什么。
        </p>
        <p v-else-if="filterOrgId" class="lede">
          列表只显示当前组织。新建时一次选好：进项目、管组织，还是当系统管理员。
        </p>
        <p v-else class="lede">
          先在顶栏选组织，才能一次把人加进组织和项目。系统管理员能管全站，和项目负责人不是一回事。
        </p>
      </div>
    </header>

    <details class="fold-card surface-card">
      <summary class="fold-summary">注册新账号</summary>
      <form class="user-creation-form" @submit.prevent="onSubmit">
        <div class="user-form-grid">
          <div class="u-field">
            <label>用户名 *</label>
            <input v-model="userForm.username" required placeholder="qa_lead" />
          </div>
          <div class="u-field">
            <label>初始密码 *</label>
            <input v-model="userForm.password" type="password" required />
          </div>
          <div class="u-field u-field-wide">
            <label>这个人来干什么 *</label>
            <ApSelect
              v-model="userForm.duty"
              aria-label="这个人来干什么"
              :options="dutyOptions"
            />
          </div>
          <div class="u-button-group">
            <button type="submit" class="primary">注册用户</button>
          </div>
        </div>
        <p class="hint">
          <template v-if="!filterOrgId">
            系统管理员能建组织、管所有人；普通用户只是能登录。要一次设好项目权限，请先在顶栏选组织。
          </template>
          <template v-else>
            「管这个项目」只管当前项目，不是系统管理员。管整个组织的人，本组织下的项目都能管。
          </template>
        </p>
      </form>
      <p v-if="userMsg" class="msg" :class="userMsgOk ? 'ok' : 'bad'">
        {{ userMsg }}
      </p>
    </details>

    <h3 class="section-title">
      {{ filterOrgId ? "组织成员账号" : "系统用户名册" }}
    </h3>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>用户名</th>
            <th>账号类型</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!items.length && hasLoaded">
            <td class="empty" colspan="5">暂无用户</td>
          </tr>
          <tr v-for="u in items" :key="u.id">
            <td class="mono">
              <button type="button" class="small" @click="admin.copyText(u.id)">
                {{ u.id.slice(0, 8) }}…
              </button>
            </td>
            <td class="username-cell">{{ u.username }}</td>
            <td>
              <span class="role-badge" :class="u.role === 'admin' ? 'admin' : 'operator'">
                {{ platformRoleLabel(u.role) }}
              </span>
            </td>
            <td>
              <span class="status-badge" :class="u.disabled ? 'disabled' : 'active'">
                {{ u.disabled ? "已禁用" : "正常" }}
              </span>
            </td>
            <td class="actions-cell">
              <button
                type="button"
                class="small"
                @click="admin.onResetUserPassword(u)"
              >
                重置密码
              </button>
              <button
                type="button"
                class="small"
                :class="u.disabled ? 'primary' : 'danger'"
                @click="admin.onToggleUserDisabled(u)"
              >
                {{ u.disabled ? "启用" : "禁用" }}
              </button>
              <button
                v-if="caps.canOps"
                type="button"
                class="small danger"
                @click="admin.onDeleteUser(u)"
              >
                删除
              </button>
            </td>
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
.user-form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(12rem, 16rem));
  gap: 0.75rem 1rem;
  align-items: end;
}
.u-field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  min-width: 0;
}
.u-field label {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--muted);
}
.u-field-wide {
  min-width: 16rem;
  max-width: 22rem;
}
.u-button-group {
  display: flex;
  align-items: flex-end;
}

.hint {
  font-size: 0.82rem;
  color: var(--muted);
  margin: 0.65rem 0 0;
  line-height: 1.45;
}

.section-title {
  margin: 1.25rem 0 0.65rem;
  font-size: 0.92rem;
}

.username-cell {
  font-weight: 600;
}

.role-badge {
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.12rem 0.4rem;
  border-radius: 4px;
}

.role-badge.admin {
  color: var(--purple-soft-fg);
  background: var(--purple-soft-bg);
}

.role-badge.operator {
  color: var(--muted);
  background: var(--chip-bg);
}

.status-badge {
  font-size: 0.72rem;
  font-weight: 600;
}

.status-badge.active {
  color: var(--ok-soft-fg);
}

.status-badge.disabled {
  color: var(--err-soft-fg, #c62828);
}

.actions-cell {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

td.empty {
  text-align: center;
}
</style>

<script setup lang="ts">
defineOptions({ name: "UsersPanel" });

import { computed, onDeactivated, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { listUsersPage, OPS_LIST_PAGE_SIZE, type PlatformUser } from "../api/opsLists";
import { useProjectsStore } from "../stores/projectsStore";
import { useAuthStore } from "../stores/auth";
import { useCapabilities } from "../composables/useCapabilities";
import { usePagedList } from "../composables/usePagedList";
import { useAdminStore } from "../stores/adminStore";
import DataPager from "./common/DataPager.vue";
import ApSelect from "./common/ApSelect.vue";
import ApModal from "./ApModal.vue";
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
const createOpen = ref(false);
const saving = ref(false);

const list = usePagedList<PlatformUser>({
  immediate: false,
  pageSize: OPS_LIST_PAGE_SIZE,
  fetchPage: ({ page, pageSize }) => listUsersPage({ page, pageSize }),
});

const { items, total, page, pageSize, loading, hasLoaded, error, reload, setPage, setPageSize } = list;

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
      { value: "project_member", label: `项目成员 · ${projectName.value}` },
      { value: "project_owner", label: `项目负责人 · ${projectName.value}` },
      { value: "project_viewer", label: `项目访客（只读） · ${projectName.value}` },
    );
  }
  if (oid) {
    opts.push({
      value: "org_member",
      label: `组织成员 · ${orgName.value}`,
    });
    opts.push({
      value: "org_admin",
      label: `组织管理员 · ${orgName.value}`,
    });
  } else {
    opts.push({ value: "user", label: "普通用户" });
  }
  if (caps.canOps) {
    opts.push({ value: "sys_admin", label: "系统管理员" });
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
  if (saving.value) return;
  const username = userForm.username.trim();
  const duty = userForm.duty || "user";
  saving.value = true;
  try {
    await admin.onCreateUser(ev, {
      orgId: (filterOrgId.value || "").trim(),
      projectId: (filterProjectId.value || "").trim(),
    });
  } finally {
    saving.value = false;
  }
  if (userMsgOk.value) {
    userMsg.value = dutySuccess(username, duty);
    createOpen.value = false;
  }
}

function openCreate() {
  userMsg.value = "";
  createOpen.value = true;
}

function closeCreate() {
  if (saving.value) return;
  createOpen.value = false;
  userForm.password = "";
  if (!userMsgOk.value) userMsg.value = "";
}

onDeactivated(closeCreate);
</script>
<template>
  <section v-if="canManageUsers" class="panel page-stack data-page">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2>用户</h2>
      </div>
      <div class="page-hero-actions">
        <button type="button" class="primary" @click="openCreate">注册新账号</button>
      </div>
    </header>

    <ApModal
      v-if="createOpen"
      title="注册新账号"
      variant="drawer"
      :close-on-esc="!saving"
      :close-on-backdrop="!saving"
      @close="closeCreate"
    >
      <form class="user-creation-form" :aria-busy="saving" @submit.prevent="onSubmit">
        <label class="u-field">
          用户名
          <input v-model="userForm.username" required autocomplete="off" :disabled="saving" data-autofocus />
        </label>
        <label class="u-field">
          初始密码
          <input v-model="userForm.password" type="password" required autocomplete="new-password" :disabled="saving" />
        </label>
        <div class="u-field">
          <span>账号角色</span>
          <ApSelect
            v-model="userForm.duty"
            aria-label="账号角色"
            :options="dutyOptions"
            :disabled="saving"
          />
        </div>
        <p v-if="userMsg && !userMsgOk" class="msg bad" role="alert">{{ userMsg }}</p>
        <footer class="ap-modal-actions">
          <button type="button" class="ghost" :disabled="saving" @click="closeCreate">取消</button>
          <button type="submit" class="primary" :disabled="saving">
            {{ saving ? "正在注册…" : "注册用户" }}
          </button>
        </footer>
      </form>
    </ApModal>

    <p v-if="userMsg && userMsgOk" class="msg ok" role="status">{{ userMsg }}</p>
    <p v-if="error" class="msg bad" role="alert">{{ error }}</p>
    <div class="table-wrap">
      <table :aria-label="filterOrgId ? '组织成员账号' : '系统用户名册'" :aria-busy="loading">
        <thead>
          <tr>
            <th scope="col">用户名</th>
            <th scope="col">账号类型</th>
            <th scope="col">状态</th>
            <th scope="col">ID</th>
            <th v-if="caps.canOps" scope="col">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!items.length && !error">
            <td class="empty" :colspan="caps.canOps ? 5 : 4">{{ loading || !hasLoaded ? "正在读取用户…" : "暂无用户" }}</td>
          </tr>
          <tr v-for="u in items" :key="u.id">
            <td class="username-cell">{{ u.username }}</td>
            <td>
              {{ platformRoleLabel(u.role) }}
            </td>
            <td>
              <span class="status-badge" :class="u.disabled ? 'disabled' : 'active'">
                {{ u.disabled ? "已禁用" : "正常" }}
              </span>
            </td>
            <td class="mono">
              <button type="button" class="linkish" :title="'复制 ' + u.id" @click="admin.copyText(u.id)">
                {{ u.id.slice(0, 8) }}…
              </button>
            </td>
            <td v-if="caps.canOps" class="actions-cell">
              <button
                type="button"
                class="linkish"
                @click="admin.onResetUserPassword(u)"
              >
                重置密码
              </button>
              <button
                type="button"
                class="linkish"
                @click="admin.onToggleUserDisabled(u)"
              >
                {{ u.disabled ? "启用" : "禁用" }}
              </button>
              <button
                type="button"
                class="linkish delete-action"
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
.user-creation-form {
  display: grid;
  gap: 0.875rem;
}
.u-field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  min-width: 0;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--muted);
}
.username-cell {
  font-weight: 600;
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
  white-space: nowrap;
}

.actions-cell button + button {
  margin-inline-start: 0.75rem;
}

.actions-cell .delete-action {
  color: var(--danger-soft-fg);
}

td.empty {
  text-align: center;
}
</style>

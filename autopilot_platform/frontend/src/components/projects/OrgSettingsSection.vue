<script setup lang="ts">
import { computed, ref, watch } from "vue";
import {
  addOrgMember,
  createOrg,
  listOrgMembersPage,
  orgPoliciesOf,
  ORG_MEMBER_PAGE_SIZE,
  patchOrgPolicies,
  type OrganizationMember,
} from "../../api/orgs";
import { apiErrorMessage } from "../../api";
import { storeToRefs } from "pinia";
import { useProjectsStore } from "../../stores/projectsStore";
import { useAdminStore } from "../../stores/adminStore";
import { useCapabilities } from "../../composables/useCapabilities";
import { usePagedList } from "../../composables/usePagedList";
import { ORG_ROLE_LABEL, orgRoleLabel } from "./roleLabels";
import DataPager from "../common/DataPager.vue";
import ApSelect from "../common/ApSelect.vue";
import ApModal from "../ApModal.vue";

const projectsStore = useProjectsStore();
const admin = useAdminStore();
const { filterOrgId, orgs } = storeToRefs(projectsStore);

const caps = useCapabilities();
const error = ref("");
const msg = ref("");
const busy = ref(false);
const dialog = ref<"organization" | "member" | "policies" | null>(null);
const form = ref({ id: "", name: "" });
const memberForm = ref({ username: "", role: "member" });

const orgId = () => (filterOrgId.value || "").trim();

const memberList = usePagedList<OrganizationMember>({
  pageSize: ORG_MEMBER_PAGE_SIZE,
  fetchPage: ({ page, pageSize }) => {
    const oid = orgId();
    if (!oid) {
      return Promise.resolve({ items: [], total: 0, page: 1, page_size: pageSize });
    }
    return listOrgMembersPage(oid, { page, pageSize });
  },
  resetSources: [() => filterOrgId.value],
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

const currentOrgName = () => {
  const oid = orgId();
  if (!oid) return "";
  const hit = orgs.value.find((o) => o.id === oid);
  return hit?.name || oid;
};

const currentPolicies = computed(() => {
  const oid = orgId();
  if (!oid) return orgPoliciesOf(null);
  const hit = orgs.value.find((o) => o.id === oid);
  return orgPoliciesOf(hit);
});

function openDialog(next: typeof dialog.value) {
  if (busy.value) return;
  error.value = "";
  msg.value = "";
  dialog.value = next;
}

function closeDialog() {
  if (busy.value) return;
  dialog.value = null;
  error.value = "";
}

async function onPolicyToggle(
  key: "members_can_create_projects" | "members_can_invite",
  event: Event,
) {
  const oid = orgId();
  if (!oid || !caps.canManageCurrentOrg) return;
  const checkbox = event.currentTarget as HTMLInputElement;
  const checked = checkbox.checked;
  checkbox.checked = currentPolicies.value[key];
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  msg.value = "";
  try {
    await patchOrgPolicies(oid, { [key]: checked });
    await projectsStore.refreshOrgs();
    if (oid === orgId()) msg.value = "已更新组织权限";
  } catch (e) {
    if (oid === orgId()) error.value = apiErrorMessage(e);
  } finally {
    busy.value = false;
  }
}

async function onCreate() {
  if (busy.value) return;
  if (!caps.canCreateOrg) {
    error.value = "仅系统管理员可创建组织";
    return;
  }
  if (!form.value.id.trim()) {
    error.value = "请填写组织 ID";
    return;
  }
  busy.value = true;
  error.value = "";
  msg.value = "";
  try {
    const out = await createOrg({
      id: form.value.id.trim(),
      name: form.value.name.trim() || form.value.id.trim(),
    });
    msg.value = `已创建组织 ${out.id}`;
    form.value = { id: "", name: "" };
    await projectsStore.refreshOrgs();
    dialog.value = null;
    projectsStore.selectOrg(out.id);
  } catch (e) {
    error.value = apiErrorMessage(e);
  } finally {
    busy.value = false;
  }
}

async function onAddMember() {
  if (busy.value) return;
  const oid = orgId();
  if (!oid) {
    error.value = "请先在顶部选择组织";
    return;
  }
  if (!caps.canInviteOrgMember) {
    error.value = "当前角色无权邀请该组织成员";
    return;
  }
  if (!memberForm.value.username.trim()) {
    error.value = "请填写用户名";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await addOrgMember(oid, {
      username: memberForm.value.username.trim(),
      role: caps.canManageCurrentOrg ? memberForm.value.role : "member",
    });
    if (oid === orgId()) {
      memberForm.value.username = "";
      msg.value = "已添加组织成员";
      dialog.value = null;
      await reloadMembers(true);
    }
  } catch (e) {
    if (oid === orgId()) error.value = apiErrorMessage(e);
  } finally {
    busy.value = false;
  }
}

watch(
  () => filterOrgId.value,
  () => {
    if (dialog.value !== "organization") {
      dialog.value = null;
      error.value = "";
    }
    memberForm.value = { username: "", role: "member" };
  },
);
</script>

<template>
  <section class="org-settings" aria-labelledby="org-members-heading">
    <header class="org-members-header">
      <div>
        <h3 id="org-members-heading">组织成员</h3>
        <p v-if="orgId()" class="meta-line">{{ currentOrgName() }}<template v-if="hasLoadedMembers"> · {{ memberTotal }} 人</template></p>
      </div>
      <div class="org-actions">
        <button v-if="caps.canCreateOrg" type="button" :class="{ primary: !orgId() }" @click="openDialog('organization')">
          新建组织
        </button>
        <button
          v-if="orgId() && caps.canManageCurrentOrg"
          type="button"
          @click="openDialog('policies')"
        >组织权限</button>
        <button
          v-if="orgId() && caps.canInviteOrgMember"
          type="button"
          class="primary"
          @click="openDialog('member')"
        >{{ caps.canManageCurrentOrg ? "添加组织成员" : "邀请同事加入组织" }}</button>
      </div>
    </header>
    <p v-if="msg && !dialog" class="msg ok" role="status">{{ msg }}</p>

    <template v-if="orgId()">
      <p v-if="memberError" class="msg bad" role="alert">
        {{ memberError }}
        <button type="button" class="linkish" @click="reloadMembers()">重试</button>
      </p>
      <div class="table-wrap org-members-table">
        <table aria-label="组织成员" :aria-busy="loadingMembers">
          <thead>
            <tr>
              <th scope="col">用户</th>
              <th scope="col">角色</th>
              <th scope="col">用户 ID</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!members.length">
              <td class="empty" colspan="3">
                {{ !hasLoadedMembers ? "加载中…" : memberError ? "未能加载成员" : "暂无成员" }}
              </td>
            </tr>
            <tr v-for="member in members" :key="member.user_id">
              <td>{{ member.username }}</td>
              <td>{{ orgRoleLabel(member.role) }}</td>
              <td class="mono">
                <button
                  type="button"
                  class="linkish"
                  :title="'复制 ' + member.user_id"
                  @click="admin.copyText(member.user_id)"
                >{{ member.user_id.length > 8 ? member.user_id.slice(0, 8) + "…" : member.user_id }}</button>
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
    </template>
    <div v-else class="empty-state">
      <p class="empty-title">尚未选定组织</p>
      <p class="empty-desc">在顶栏选择组织后查看成员。</p>
      <p v-if="!caps.canCreateOrg" class="empty-desc">无法自行创建组织。请联系管理员将你加入组织。</p>
    </div>
  </section>

  <ApModal
    v-if="dialog === 'organization' && caps.canCreateOrg"
    title="新建组织"
    :close-on-backdrop="!busy"
    :close-on-esc="!busy"
    @close="closeDialog"
  >
    <form class="org-form" :aria-busy="busy" @submit.prevent="onCreate">
      <label>
        组织 ID
        <input v-model="form.id" name="organization-id" required :disabled="busy" data-autofocus />
      </label>
      <label>
        名称
        <input v-model="form.name" name="organization-name" :disabled="busy" />
      </label>
      <p v-if="error" class="msg bad" role="alert">{{ error }}</p>
      <footer class="ap-modal-actions">
        <button type="button" class="ghost" :disabled="busy" @click="closeDialog">取消</button>
        <button type="submit" class="primary" :disabled="busy">{{ busy ? "正在创建…" : "创建组织" }}</button>
      </footer>
    </form>
  </ApModal>

  <ApModal
    v-if="dialog === 'member' && orgId() && caps.canInviteOrgMember"
    :title="caps.canManageCurrentOrg ? '添加组织成员' : '邀请同事加入组织'"
    :description="currentOrgName()"
    :close-on-backdrop="!busy"
    :close-on-esc="!busy"
    @close="closeDialog"
  >
    <form class="org-form" :aria-busy="busy" @submit.prevent="onAddMember">
      <label>
        用户名
        <input v-model="memberForm.username" name="username" required :disabled="busy" data-autofocus />
      </label>
      <label v-if="caps.canManageCurrentOrg">
        角色
        <ApSelect
          v-model="memberForm.role"
          aria-label="组织成员角色"
          :disabled="busy"
          :options="[
            { value: 'member', label: ORG_ROLE_LABEL.member },
            { value: 'admin', label: ORG_ROLE_LABEL.admin },
            { value: 'owner', label: ORG_ROLE_LABEL.owner },
          ]"
        />
      </label>
      <p v-else class="meta-line">新成员将获得普通成员角色。</p>
      <p v-if="error" class="msg bad" role="alert">{{ error }}</p>
      <footer class="ap-modal-actions">
        <button type="button" class="ghost" :disabled="busy" @click="closeDialog">取消</button>
        <button type="submit" class="primary" :disabled="busy">
          {{ busy ? "正在添加…" : caps.canManageCurrentOrg ? "添加组织成员" : "邀请加入" }}
        </button>
      </footer>
    </form>
  </ApModal>

  <ApModal
    v-if="dialog === 'policies' && orgId() && caps.canManageCurrentOrg"
    title="组织权限"
    :description="currentOrgName()"
    :close-on-backdrop="!busy"
    :close-on-esc="!busy"
    @close="closeDialog"
  >
    <div class="org-form" :aria-busy="busy">
      <label class="policy-row">
        <input
          type="checkbox"
          :checked="currentPolicies.members_can_create_projects"
          :aria-disabled="busy"
          @change="onPolicyToggle('members_can_create_projects', $event)"
        />
        允许普通成员创建项目
      </label>
      <label class="policy-row">
        <input
          type="checkbox"
          :checked="currentPolicies.members_can_invite"
          :aria-disabled="busy"
          @change="onPolicyToggle('members_can_invite', $event)"
        />
        <span>允许普通成员邀请同事<small>受邀账号加入为普通成员。</small></span>
      </label>
      <p v-if="msg" class="msg ok" role="status">{{ msg }}</p>
      <p v-if="error" class="msg bad" role="alert">{{ error }}</p>
    </div>
    <template #actions>
      <button type="button" :disabled="busy" @click="closeDialog">完成</button>
    </template>
  </ApModal>
</template>

<style scoped>
.org-settings {
  display: grid;
  gap: 0.75rem;
  min-width: 0;
}

.org-members-header,
.org-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 0.75rem;
}

.org-members-header {
  justify-content: space-between;
}

.org-members-header h3,
.org-members-header p,
.org-members-table,
.msg {
  margin: 0;
}

.org-members-header h3 {
  font-size: 1rem;
}

.org-form {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.org-form > label {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  font-size: 0.82rem;
  color: var(--text);
}

.org-form > .policy-row {
  flex-direction: row;
  align-items: flex-start;
  gap: 0.55rem;
  cursor: pointer;
}

.policy-row input {
  width: auto;
  margin-top: 0.125rem;
}

.policy-row small {
  display: block;
  margin-top: 0.2rem;
  color: var(--muted);
}
</style>

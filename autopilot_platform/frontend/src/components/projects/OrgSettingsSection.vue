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

const projectsStore = useProjectsStore();
const admin = useAdminStore();
const { filterOrgId, orgs } = storeToRefs(projectsStore);

const caps = useCapabilities();
const error = ref("");
const msg = ref("");
const busy = ref(false);
const form = ref({ id: "", name: "" });
const memberForm = ref({ username: "", role: "member" });

const orgId = () => (filterOrgId.value || "").trim();

const memberList = usePagedList<OrganizationMember>({
  immediate: false,
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

async function onPolicyToggle(
  key: "members_can_create_projects" | "members_can_invite",
  checked: boolean,
) {
  const oid = orgId();
  if (!oid || !caps.canManageCurrentOrg) return;
  busy.value = true;
  error.value = "";
  try {
    await patchOrgPolicies(oid, { [key]: checked });
    await projectsStore.refreshOrgs();
    msg.value = "已更新组织权限";
  } catch (e) {
    error.value = apiErrorMessage(e);
  } finally {
    busy.value = false;
  }
}

async function onCreate() {
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
    projectsStore.selectOrg(out.id);
  } catch (e) {
    error.value = apiErrorMessage(e);
  } finally {
    busy.value = false;
  }
}

async function onAddMember() {
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
    memberForm.value.username = "";
    msg.value = "已添加组织成员";
    await reloadMembers(true);
  } catch (e) {
    error.value = apiErrorMessage(e);
  } finally {
    busy.value = false;
  }
}

watch(
  () => filterOrgId.value,
  () => void reloadMembers(true),
);
void reloadMembers(true);
</script>

<template>
  <div class="org-settings page-stack">
    <section class="surface-card">
      <div class="card-title-row">
        <h3>组织 / 事业部</h3>
        <span v-if="orgId()" class="pill ok">当前：{{ currentOrgName() }}</span>
      </div>
      <p class="section-note">
        <template v-if="caps.canCreateOrg">
          组织是项目的父级上下文。可在此创建组织，或在顶栏选定组织后管理成员。
        </template>
        <template v-else-if="caps.canManageCurrentOrg">
          当前组织由你管理：可在下方调整权限开关、添加成员。顶栏「组织」用于切换上下文。
        </template>
        <template v-else-if="caps.canInviteOrgMember">
          本组织已允许普通成员邀请同事（仅普通成员角色）。如需创建项目或调整权限，请联系组织负责人。
        </template>
        <template v-else>
          组织由系统管理员创建。请在顶栏选择已加入的组织；如需加人，请联系组织负责人或组织管理员。
        </template>
      </p>

      <div class="org-grid">
        <form v-if="caps.canCreateOrg" class="org-form" @submit.prevent="onCreate">
          <h4>新建组织</h4>
          <div class="form-row">
            <label>
              组织 ID *
              <input v-model="form.id" required placeholder="bu-core" />
            </label>
            <label>
              名称
              <input v-model="form.name" placeholder="核心事业部" />
            </label>
          </div>
          <button type="submit" class="primary" :disabled="busy">创建组织</button>
        </form>

        <form
          v-if="caps.canManageCurrentOrg && orgId()"
          class="org-form"
          @submit.prevent
        >
          <h4>组织权限</h4>
          <p class="inline-hint">
            默认仅组织负责人/管理员可创建项目和邀请成员。打开开关后，普通成员获得对应能力。
          </p>
          <label class="policy-row">
            <input
              type="checkbox"
              :checked="currentPolicies.members_can_create_projects"
              :disabled="busy"
              @change="onPolicyToggle('members_can_create_projects', ($event.target as HTMLInputElement).checked)"
            />
            <span>
              <strong>允许普通成员创建项目</strong>
              <small>关闭时成员只能加入已有项目，不能新建空间。</small>
            </span>
          </label>
          <label class="policy-row">
            <input
              type="checkbox"
              :checked="currentPolicies.members_can_invite"
              :disabled="busy"
              @change="onPolicyToggle('members_can_invite', ($event.target as HTMLInputElement).checked)"
            />
            <span>
              <strong>允许普通成员邀请同事</strong>
              <small>成员只能邀请「普通成员」角色，不能授予管理员/负责人。</small>
            </span>
          </label>
        </form>

        <form
          v-if="caps.canInviteOrgMember"
          class="org-form"
          @submit.prevent="onAddMember"
        >
          <h4>{{ caps.canManageCurrentOrg ? "添加组织成员" : "邀请同事加入组织" }}</h4>
          <div class="form-row">
            <label>
              用户名
              <input v-model="memberForm.username" placeholder="alice" />
            </label>
            <label v-if="caps.canManageCurrentOrg">
              角色
              <ApSelect
                v-model="memberForm.role"
                aria-label="组织成员角色"
                :options="[
                  { value: 'member', label: ORG_ROLE_LABEL.member },
                  { value: 'admin', label: ORG_ROLE_LABEL.admin },
                  { value: 'owner', label: ORG_ROLE_LABEL.owner },
                ]"
              />
            </label>
            <p v-else class="inline-hint">将以普通成员加入，不能指定管理员。</p>
          </div>
          <button type="submit" :disabled="busy">
            {{ caps.canManageCurrentOrg ? "添加组织成员" : "邀请加入" }}
          </button>
        </form>

        <div v-else-if="orgId()" class="org-form readonly-hint">
          <h4>组织成员管理</h4>
          <p class="inline-hint">
            你在「{{ currentOrgName() }}」的角色为{{ orgRoleLabel(caps.currentOrgRole) }}（只读）。如需加人，请联系组织负责人或组织管理员。
          </p>
        </div>
      </div>

      <p v-if="msg" class="msg ok">{{ msg }}</p>
      <p v-if="error" class="msg bad">{{ error }}</p>
    </section>

    <section v-if="orgId()" class="surface-card">
      <div class="card-title-row">
        <h3>组织成员</h3>
        <span class="count-chip">{{ memberTotal || (loadingMembers ? "…" : 0) }}</span>
      </div>
      <div class="table-wrap" style="margin-top: 0">
        <table>
          <thead>
            <tr>
              <th>用户</th>
              <th>角色</th>
              <th>用户 ID</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!members.length && hasLoadedMembers">
              <td class="empty" colspan="3">暂无成员</td>
            </tr>
            <tr v-for="m in members" :key="m.user_id">
              <td>{{ m.username }}</td>
              <td>
                <span class="pill" :class="m.role === 'owner' || m.role === 'admin' ? 'ok' : ''">
                  {{ orgRoleLabel(m.role) }}
                </span>
              </td>
              <td class="mono">
                <button type="button" class="small" @click="admin.copyText(m.user_id)">
                  {{ m.user_id.slice(0, 8) }}…
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
    </section>

    <div v-else class="empty-state">
      <p class="empty-title">尚未选定组织</p>
      <p v-if="caps.canCreateOrg" class="empty-desc">
        在顶栏选择已有组织，或在上方创建新组织。选定后即可管理成员并在「项目协作」下创建项目。
      </p>
      <p v-else class="empty-desc">
        请在顶栏「组织」下拉中选择已加入的组织。若列表为空，请联系管理员将你加入组织，无法自行创建。
      </p>
    </div>
  </div>
</template>

<style scoped>
.section-note {
  margin: -0.35rem 0 1rem;
  color: var(--muted);
  font-size: 0.82rem;
  line-height: 1.5;
}

.org-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 1rem;
}

.org-form {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 0.9rem 1rem;
  background: var(--surface-soft);
  border: 1px solid var(--border-weak);
  border-radius: var(--radius-md);
}

.org-form h4 {
  margin: 0;
  font-size: 0.85rem;
  font-weight: 700;
  color: var(--text);
}

.form-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
}

.form-row label {
  flex: 1;
  min-width: 8rem;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--muted);
}

.inline-hint {
  margin: 0;
  font-size: 0.78rem;
  color: var(--muted);
  line-height: 1.45;
}

.policy-row {
  display: flex;
  align-items: flex-start;
  gap: 0.55rem;
  font-size: 0.82rem;
  color: var(--text);
  cursor: pointer;
}

.policy-row input {
  width: auto;
  margin-top: 0.2rem;
}

.policy-row span {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.policy-row strong {
  font-size: 0.82rem;
  font-weight: 650;
}

.policy-row small {
  color: var(--muted);
  font-size: 0.74rem;
  font-weight: 400;
  line-height: 1.4;
}

.msg {
  margin: 0.85rem 0 0;
  font-size: 0.82rem;
}

.msg.bad {
  color: var(--bad);
}
</style>

<script setup lang="ts">
defineOptions({ name: "SharePanel" });

import { storeToRefs } from "pinia";
import { computed, onDeactivated, ref, watch } from "vue";
import { useAuthStore } from "../stores/auth";
import { useShellStore } from "../stores/shellStore";
import { useCapabilities } from "../composables/useCapabilities";
import { useAdminStore } from "../stores/adminStore";
import { useOpsStore } from "../stores/opsStore";
import ApSelect from "./common/ApSelect.vue";
import ApModal from "./ApModal.vue";

const auth = useAuthStore();
const { canManageUsers } = storeToRefs(auth);
const shell = useShellStore();
const { activeTab } = storeToRefs(shell);
const ops = useOpsStore();
const admin = useAdminStore();
const { shareForm, shareMsg, aclRows, aclLoading, aclError } = storeToRefs(ops);
const { auditFilter } = storeToRefs(admin);
const caps = useCapabilities();
const grantOpen = ref(false);
const saving = ref(false);
const resourceOptions = [
  { value: "artifact", label: "工程制品" },
  { value: "app_build", label: "应用资源" },
  { value: "job", label: "批跑任务" },
  { value: "schedule", label: "定时计划" },
];
const permissionOptions = [
  { value: "read", label: "只读" },
  { value: "write", label: "读写" },
];

const readOnlyHint = computed(() => {
  if (caps.canShareWrite) return "";
  if (caps.isProjectViewer) return "只读项目，无法修改共享";
  return "无共享权限";
});

function openShareAudit() {
  if (!canManageUsers.value) return;
  auditFilter.value.action = "acl.";
  auditFilter.value.actor = "";
  activeTab.value = "audit";
  void admin.refreshAudits();
}

function openGrant() {
  if (!caps.canShareWrite || !shareForm.value.resource_id.trim()) return;
  shareMsg.value = "";
  grantOpen.value = true;
}

function closeGrant() {
  if (saving.value) return;
  grantOpen.value = false;
  shareMsg.value = "";
}

async function submitGrant(event: Event) {
  if (saving.value || !caps.canShareWrite || !shareForm.value.resource_id.trim()) return;
  shareMsg.value = "";
  saving.value = true;
  try {
    await ops.onShare(event);
    if (shareMsg.value.startsWith("已分享给 ")) grantOpen.value = false;
  } finally {
    saving.value = false;
  }
}

onDeactivated(() => { grantOpen.value = false; });
watch(
  [() => shareForm.value.resource_type, () => shareForm.value.resource_id.trim()],
  () => { grantOpen.value = false; },
  { flush: "sync" },
);
</script>

<template>
  <section class="panel page-stack data-page">
    <header class="page-hero">
      <h2>共享</h2>
      <div class="page-hero-actions">
        <button v-if="canManageUsers" type="button" class="ghost" @click="openShareAudit">查看共享记录</button>
        <button
          v-if="caps.canShareWrite"
          type="button"
          class="primary"
          :disabled="!shareForm.resource_id.trim()"
          @click="openGrant"
        >建立授权</button>
      </div>
    </header>

    <form class="share-toolbar" @submit.prevent="ops.refreshAcl">
      <div class="share-field">
        <span>资源类型</span>
        <ApSelect
          v-model="shareForm.resource_type"
          aria-label="资源类型"
          :options="resourceOptions"
          @change="ops.refreshAcl"
        />
      </div>
      <label class="share-field share-resource">
        资源 ID
        <input v-model="shareForm.resource_id" placeholder="输入资源 ID" @change="ops.refreshAcl" />
      </label>
      <button type="submit">刷新列表</button>
    </form>

    <p v-if="readOnlyHint" class="share-note">{{ readOnlyHint }}</p>
    <p v-if="shareMsg && !grantOpen" class="msg ok" role="status">{{ shareMsg }}</p>
    <p v-if="aclError" class="msg bad" role="alert">{{ aclError }}</p>
    <div class="table-wrap">
      <table aria-label="共享授权" :aria-busy="aclLoading">
        <thead>
          <tr>
            <th scope="col">用户</th>
            <th scope="col">权限</th>
            <th scope="col">资源</th>
            <th v-if="caps.canShareWrite" scope="col">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!aclRows.length">
            <td :colspan="caps.canShareWrite ? 4 : 3" class="empty">
              <template v-if="aclLoading">正在加载授权…</template>
              <template v-else-if="aclError">授权加载失败</template>
              <template v-else>{{ shareForm.resource_id.trim() ? "暂无共享授权" : "输入资源 ID 后查看授权" }}</template>
            </td>
          </tr>
          <tr v-for="grant in aclRows" :key="grant.id">
            <td class="share-user">{{ grant.username }}</td>
            <td>{{ grant.permission === "write" ? "读写" : "只读" }}</td>
            <td>
              {{ resourceOptions.find((option) => option.value === grant.resource_type)?.label || grant.resource_type }}
              <span class="mono" :title="grant.resource_id">{{ grant.resource_id }}</span>
            </td>
            <td v-if="caps.canShareWrite">
              <button type="button" class="linkish revoke" @click="ops.onRevokeAcl(grant.id)">撤销授权</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <ApModal
      v-if="grantOpen && caps.canShareWrite"
      title="建立授权"
      :description="shareForm.resource_id"
      :close-on-backdrop="!saving"
      :close-on-esc="!saving"
      @close="closeGrant"
    >
      <form class="share-grant-form" :aria-busy="saving" @submit.prevent="submitGrant">
        <label class="share-field">
          用户名
          <input v-model="shareForm.username" required :disabled="saving" data-autofocus />
        </label>
        <div class="share-field">
          <span>权限</span>
          <ApSelect
            v-model="shareForm.permission"
            aria-label="权限"
            :options="permissionOptions"
            :disabled="saving"
          />
        </div>
        <p v-if="shareMsg" class="msg bad" role="alert">{{ shareMsg }}</p>
        <footer class="ap-modal-actions">
          <button type="button" class="ghost" :disabled="saving" @click="closeGrant">取消</button>
          <button type="submit" class="primary" :disabled="saving">{{ saving ? "正在授权…" : "确认授权" }}</button>
        </footer>
      </form>
    </ApModal>
  </section>
</template>

<style scoped>
.share-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: end;
  gap: 0.625rem 1rem;
}

.share-field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
  color: var(--muted);
  font-size: var(--font-size-meta);
}

.share-toolbar .share-field:first-child {
  flex: 0 1 10rem;
}

.share-resource {
  flex: 1 1 12rem;
  max-width: 30rem;
}

.share-grant-form {
  display: grid;
  gap: 0.875rem;
}

.share-note {
  margin: 0;
  color: var(--muted);
}

.share-user {
  font-weight: 600;
}

.mono {
  color: var(--muted);
  margin-inline-start: 0.35rem;
}

.revoke {
  color: var(--danger-soft-fg);
  white-space: nowrap;
}
</style>

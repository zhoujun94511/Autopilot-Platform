<script setup lang="ts">
defineOptions({ name: "SharePanel" });

import { storeToRefs } from "pinia";
import { computed } from "vue";
import { useAuthStore } from "../stores/auth";
import { useShellStore } from "../stores/shellStore";
import { useCapabilities } from "../composables/useCapabilities";
import { useAdminStore } from "../stores/adminStore";
import { useOpsStore } from "../stores/opsStore";
import ApSelect from "./common/ApSelect.vue";

const auth = useAuthStore();
const { canManageUsers } = storeToRefs(auth);
const shell = useShellStore();
const { activeTab } = storeToRefs(shell);
const ops = useOpsStore();
const admin = useAdminStore();
const { shareForm, shareMsg, aclRows } = storeToRefs(ops);
const { auditFilter } = storeToRefs(admin);
const caps = useCapabilities();

const readOnlyHint = computed(() => {
  if (caps.canShareWrite) return "";
  if (caps.isProjectViewer) {
    return "当前项目为只读：可以查看已分享内容，但不能新增或取消分享。";
  }
  return "输入或点选资源后可以查看已有分享；建立或撤销共享需要该资源所属项目的写权限。";
});

function openShareAudit() {
  if (!canManageUsers.value) return;
  auditFilter.value.action = "acl.";
  auditFilter.value.actor = "";
  activeTab.value = "audit";
  void admin.refreshAudits();
}
</script>



<template>

  <section class="panel page-stack">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2>共享</h2>
        <p class="lede">
          把指定的制品、任务或计划分享给其他人。
        </p>
        <button
          v-if="canManageUsers"
          type="button"
          class="linkish lede-link"
          @click="openShareAudit"
        >
          查看共享记录
        </button>
      </div>
    </header>

    <p v-if="readOnlyHint" class="share-lead warn">

      {{ readOnlyHint }}

    </p>



    <div class="nested-form-card">

      <div class="share-grid share-lookup-row">

        <div class="share-field">

          <label>资源类型</label>

          <ApSelect
            v-model="shareForm.resource_type"
            aria-label="资源类型"
            :options="[
              { value: 'artifact', label: '工程制品' },
              { value: 'app_build', label: '应用资源' },
              { value: 'job', label: '任务' },
              { value: 'schedule', label: '计划' },
            ]"
            @change="ops.refreshAcl"
          />

        </div>

        <div class="share-field flex-two">

          <label>要分享的内容</label>

          <input

            v-model="shareForm.resource_id"

            placeholder="从上表点选，或粘贴编号"

            @change="ops.refreshAcl"

          />

        </div>

        <div class="share-button-group">

          <button type="button" @click="ops.refreshAcl" title="同步当前资源的共享列表">

            刷新列表

          </button>

        </div>

      </div>



      <form v-if="caps.canShareWrite" class="share-creation-form" @submit.prevent="ops.onShare">

        <div class="share-grid">

          <div class="share-field">

            <label>被授权用户名 *</label>

            <input v-model="shareForm.username" required placeholder="例如: developer_a" />

          </div>

          <div class="share-field">

            <label>授予级别 *</label>

            <ApSelect
              v-model="shareForm.permission"
              aria-label="授予级别"
              :options="[
                { value: 'read', label: '只读' },
                { value: 'write', label: '读写' },
              ]"
            />

          </div>

          <div class="share-button-group">

            <button type="submit" class="primary">

              <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="2.5" fill="none">

                <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8" />

                <polyline points="16 6 12 2 8 6" />

                <line x1="12" y1="2" x2="12" y2="15" />

              </svg>

              建立授权

            </button>

          </div>

        </div>

      </form>

      <p v-if="shareMsg" class="msg ok">{{ shareMsg }}</p>

    </div>



    <h3 class="section-title">已共享</h3>

    <div class="table-wrap">

      <table>

        <thead>

          <tr>

            <th>被授权协作用户</th>

            <th>获得授权等级</th>

            <th>授权目标资源类型与 ID</th>

            <th>管理操作</th>

          </tr>

        </thead>

        <tbody>

          <tr v-if="!shareForm.resource_id.trim()">

            <td class="empty" colspan="4">先从上表点选要分享的内容，或粘贴编号</td>

          </tr>

          <tr v-else-if="!aclRows.length">

            <td class="empty" colspan="4">
              <div class="empty-stack">
                <span>这条内容还没有分享给任何人。</span>
                <span v-if="caps.canShareWrite">填写用户名后点「建立授权」即可。</span>
              </div>
            </td>

          </tr>

          <tr v-for="g in aclRows" :key="g.id">

            <td>

              <span class="user-badge">{{ g.username }}</span>

            </td>

            <td>

              <span class="pill" :class="g.permission === 'write' ? 'ok' : ''">

                {{ g.permission === 'write' ? '读写' : '只读' }}

              </span>

            </td>

            <td class="mono resource-cell">

              <span class="type-tag">{{ g.resource_type }}</span>

              <span class="id-val">{{ g.resource_id.slice(0, 8) }}…</span>

            </td>

            <td>

              <button

                v-if="caps.canShareWrite"

                type="button"

                class="small danger"

                @click="ops.onRevokeAcl(g.id)"

                title="撤销此条共享规则"

              >

                <svg viewBox="0 0 24 24" width="11" height="11" stroke="currentColor" stroke-width="2.5" fill="none">

                  <polyline points="3 6 5 6 21 6" />

                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />

                </svg>

                撤销授权

              </button>

              <span v-else class="meta-line">只读</span>

            </td>

          </tr>

        </tbody>

      </table>

    </div>

  </section>

</template>



<style scoped>

.share-lead {

  margin: -0.25rem 0 1rem;

  color: var(--muted);

  font-size: 0.85rem;

}

.share-lead.warn {

  color: var(--warning-soft-fg, var(--muted));

  margin-top: 0;

  line-height: 1.45;

}

.share-lead .linkish {
  margin-left: 0.5rem;
  border: none;
  background: none;
  padding: 0;
  color: var(--accent, #2563eb);
  cursor: pointer;
  font: inherit;
  text-decoration: underline;
}



.nested-form-card {

  background-color: var(--surface-soft);

  border: 1px solid var(--line-soft);

  border-radius: 8px;

  padding: 1.25rem;

  margin-bottom: 1.5rem;

  width: 100%;

}



.share-creation-form {

  width: 100%;

  margin-top: 1rem;

  padding-top: 1rem;

  border-top: 1px dashed var(--line-soft);

}



.share-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  width: 100%;
  align-items: flex-end;
}



.share-field {

  display: flex;

  flex-direction: column;

  gap: 0.4rem;

  flex: 1;

  min-width: 150px;

}



.share-field label {

  font-size: 0.78rem;

  font-weight: 600;

  color: var(--muted);

}



.flex-two {

  flex: 2;

  min-width: 250px;

}



.share-button-group {

  display: flex;

  gap: 0.5rem;

  height: 38px;

  margin-bottom: 2px;

}



.section-title {

  margin: 1.5rem 0 0.5rem !important;

  font-size: 1rem !important;

  font-weight: 700;

  color: var(--text);

}



.user-badge {

  font-weight: 600;

  background-color: var(--control-bg);

  padding: 0.15rem 0.5rem;

  border-radius: 4px;

  border: 1px solid var(--line);

}



.resource-cell {

  display: flex;

  align-items: center;

  gap: 0.45rem;

}



.type-tag {

  font-family: var(--font);

  font-size: 0.72rem;

  font-weight: 700;

  text-transform: uppercase;

  color: var(--accent-text);

  background-color: var(--info-soft-bg);

  padding: 0.05rem 0.35rem;

  border-radius: 3px;

  border: 1px solid var(--info-soft-border);

}



.id-val {

  color: var(--mono);

}



@media (max-width: 768px) {

  .share-grid {

    flex-direction: column;

    align-items: stretch;

  }

  .share-button-group {

    width: 100%;

  }

  .share-button-group button {

    flex: 1;

  }

}

</style>



<script setup lang="ts">
import { computed, watch } from "vue";
import { storeToRefs } from "pinia";
import { useProjectsStore } from "../../stores/projectsStore";

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: []; created: [id: string] }>();

const projectsStore = useProjectsStore();
const { filterOrgId, orgs, projectForm, projectMsg } = storeToRefs(projectsStore);


const orgId = computed(() => (filterOrgId.value || "").trim());
const orgLabel = computed(() => {
  const oid = orgId.value;
  if (!oid) return "";
  const hit = orgs.value.find((o) => o.id === oid);
  return hit?.name ? `${hit.name}（${oid}）` : oid;
});

watch(
  () => props.open,
  (v) => {
    if (v) {
      projectMsg.value = "";
      projectForm.value.id = "";
      projectForm.value.name = "";
    }
  },
);

async function onSubmit(ev: Event) {
  if (!orgId.value) {
    projectMsg.value = "请先在顶栏选择组织 / 事业部，再创建项目";
    return;
  }
  const createdId = projectForm.value.id.trim();
  await projectsStore.onCreateProject(ev);
  if (String(projectMsg.value || "").startsWith("已创建") && createdId) {
    emit("created", createdId);
    emit("close");
  }
}

function onBackdrop() {
  emit("close");
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-mask" @click.self="onBackdrop">
      <section class="modal-card" role="dialog" aria-modal="true" aria-labelledby="create-project-title">
        <header class="modal-head">
          <div>
            <h3 id="create-project-title">新建项目空间</h3>
            <p class="modal-sub">
              <template v-if="orgId">
                将归属组织 <code>{{ orgLabel }}</code>，创建后自动选用该空间。
              </template>
              <template v-else>
                创建项目前须选定组织 / 事业部。请先关闭此对话框，在顶栏选择或前往「组织 / 事业部」配置。
              </template>
            </p>
          </div>
          <button type="button" class="icon-btn" aria-label="关闭" @click="emit('close')">✕</button>
        </header>

        <form class="modal-body" @submit.prevent="onSubmit">
          <label class="field-label">
            空间 ID *
            <input
              v-model="projectForm.id"
              required
              autofocus
              placeholder="team-core"
              autocomplete="off"
              :disabled="!orgId"
            />
          </label>
          <label class="field-label">
            显示名称
            <input
              v-model="projectForm.name"
              placeholder="核心业务自动化"
              :disabled="!orgId"
            />
          </label>
          <p v-if="projectMsg" class="msg" :class="projectMsg.startsWith('已') ? 'ok' : 'bad'">
            {{ projectMsg }}
          </p>
          <footer class="modal-actions">
            <button type="button" class="ghost" @click="emit('close')">取消</button>
            <button type="submit" class="primary" :disabled="!orgId">创建项目</button>
          </footer>
        </form>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.25rem;
  background: var(--overlay);
}

.modal-card {
  width: min(440px, 100%);
  background: var(--surface-elevated);
  border: 1px solid var(--border-medium);
  border-radius: var(--radius-lg);
  box-shadow: var(--elevated-shadow);
}

.modal-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1.1rem 1.2rem 0.85rem;
  border-bottom: 1px solid var(--line);
}

.modal-head h3 {
  margin: 0 0 0.3rem;
  font-size: 1rem;
  font-weight: 700;
  color: var(--text);
}

.modal-sub {
  margin: 0;
  font-size: 0.78rem;
  color: var(--muted);
  line-height: 1.45;
}

.modal-sub code {
  font-size: 0.75rem;
  color: var(--mono);
}

.icon-btn {
  appearance: none;
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 1rem;
  padding: 0.2rem 0.4rem;
  border-radius: var(--radius-sm);
}

.icon-btn:hover {
  color: var(--text);
  background: var(--action-hover);
}

.modal-body {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  padding: 1.1rem 1.2rem 1.2rem;
}

.field-label {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--muted);
}

.msg.bad {
  color: var(--bad);
  margin: 0;
  font-size: 0.82rem;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 0.25rem;
}
</style>

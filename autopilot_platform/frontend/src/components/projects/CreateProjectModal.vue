<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useProjectsStore } from "../../stores/projectsStore";
import ApModal from "../ApModal.vue";

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: []; created: [id: string] }>();

const projectsStore = useProjectsStore();
const { filterOrgId, orgs, projectForm, projectMsg } = storeToRefs(projectsStore);
const saving = ref(false);

const orgId = computed(() => (filterOrgId.value || "").trim());
const orgLabel = computed(() => {
  const org = orgs.value.find((item) => item.id === orgId.value);
  return org?.name || orgId.value;
});
const description = computed(() =>
  orgId.value ? `将创建到 ${orgLabel.value}` : "请先在顶栏选择组织。",
);

watch(
  () => props.open,
  (open) => {
    if (open) {
      projectMsg.value = "";
      projectForm.value.id = "";
      projectForm.value.name = "";
    }
  },
);

function close() {
  if (!saving.value) emit("close");
}

async function onSubmit(event: Event) {
  if (!orgId.value || saving.value) return;
  const createdId = projectForm.value.id.trim();
  projectMsg.value = "";
  saving.value = true;
  try {
    await projectsStore.onCreateProject(event);
  } finally {
    saving.value = false;
  }
  if (createdId && projectMsg.value.startsWith("已创建")) {
    emit("created", createdId);
    close();
  }
}
</script>

<template>
  <ApModal
    v-if="open"
    title="新建项目"
    :description="description"
    :close-on-backdrop="!saving"
    :close-on-esc="!saving"
    @close="close"
  >
    <form class="project-form" :aria-busy="saving" @submit.prevent="onSubmit">
      <label class="field-label">
        空间 ID *
        <input
          v-model="projectForm.id"
          name="project-id"
          required
          :data-autofocus="orgId ? '' : undefined"
          placeholder="team-core"
          autocomplete="off"
          spellcheck="false"
          :disabled="!orgId || saving"
        />
      </label>
      <label class="field-label">
        显示名称
        <input
          v-model="projectForm.name"
          name="project-name"
          placeholder="核心业务自动化"
          autocomplete="off"
          :disabled="!orgId || saving"
        />
      </label>
      <p v-if="projectMsg" class="msg bad" role="alert">{{ projectMsg }}</p>
      <footer class="ap-modal-actions">
        <button type="button" class="ghost" :disabled="saving" @click="close">取消</button>
        <button type="submit" class="primary" :disabled="!orgId || saving">
          {{ saving ? "正在创建…" : "创建项目" }}
        </button>
      </footer>
    </form>
  </ApModal>
</template>

<style scoped>
.project-form {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
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
</style>

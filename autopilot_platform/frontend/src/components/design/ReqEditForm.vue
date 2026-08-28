<script setup lang="ts">
import { ref, watch } from "vue";
import type { Requirement } from "../../api/designRequirements";
import ApSelect from "../common/ApSelect.vue";

const props = defineProps<{
  item: Requirement | null;
  busy?: boolean;
}>();

const emit = defineEmits<{
  save: [payload: { title: string; content: string; req_key: string; priority: string }];
  cancel: [];
}>();

const title = ref("");
const content = ref("");
const reqKey = ref("");
const priority = ref("medium");

watch(
  () => props.item,
  (it) => {
    if (!it) return;
    title.value = it.title || "";
    content.value = it.content || "";
    reqKey.value = it.req_key || "";
    priority.value = it.priority || "medium";
  },
  { immediate: true },
);

function submit() {
  emit("save", {
    title: title.value,
    content: content.value,
    req_key: reqKey.value,
    priority: priority.value,
  });
}
</script>

<template>
  <section v-if="item" class="surface-card edit">
    <h3>编辑需求</h3>
    <div class="field-stack">
      <label class="field-label">
        编号
        <input v-model="reqKey" placeholder="REQ-…" />
      </label>
      <label class="field-label">
        标题
        <input v-model="title" placeholder="需求标题" />
      </label>
      <label class="field-label">
        内容
        <textarea v-model="content" rows="4" placeholder="需求描述" />
      </label>
      <div class="inline-tools">
        <label class="field-label" style="max-width: 10rem; margin: 0">
          优先级
          <ApSelect
            v-model="priority"
            size="compact"
            aria-label="优先级"
            :options="[
              { value: 'high', label: '高' },
              { value: 'medium', label: '中' },
              { value: 'low', label: '低' },
            ]"
          />
        </label>
        <span class="spacer" />
        <button type="button" :disabled="busy" @click="emit('cancel')">取消</button>
        <button type="button" class="primary" :disabled="busy" @click="submit">保存</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.edit {
  border-color: color-mix(in srgb, var(--accent) 40%, var(--line));
}
</style>

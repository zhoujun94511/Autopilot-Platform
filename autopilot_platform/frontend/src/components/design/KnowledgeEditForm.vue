<script setup lang="ts">
import { ref, watch } from "vue";
import type { KnowledgeItem } from "../../api/designKnowledge";
import ApSelect from "../common/ApSelect.vue";

const props = defineProps<{
  item: KnowledgeItem | null;
  busy?: boolean;
}>();

const emit = defineEmits<{
  save: [payload: { title: string; content: string; category: string; confirmed: boolean }];
  cancel: [];
}>();

const title = ref("");
const content = ref("");
const category = ref("best_practices");
const confirmed = ref(true);

const categories = [
  { value: "best_practices", label: "最佳实践" },
  { value: "business_rules", label: "业务规则" },
  { value: "requirements", label: "需求补充" },
  { value: "test_cases", label: "用例参考" },
  { value: "other", label: "其他" },
];

watch(
  () => props.item,
  (it) => {
    if (!it) return;
    title.value = it.title;
    content.value = it.content;
    category.value = it.category || "other";
    confirmed.value = !!it.confirmed;
  },
  { immediate: true },
);

function submit() {
  emit("save", {
    title: title.value,
    content: content.value,
    category: category.value,
    confirmed: confirmed.value,
  });
}
</script>

<template>
  <section v-if="item" class="surface-card edit">
    <h3>编辑知识</h3>
    <div class="field-stack">
      <label class="field-label">
        标题
        <input v-model="title" />
      </label>
      <label class="field-label">
        正文
        <textarea v-model="content" rows="4" />
      </label>
      <div class="inline-tools">
        <label class="field-label" style="flex: 1; min-width: 10rem; margin: 0">
          分类
          <ApSelect v-model="category" size="compact" aria-label="分类" :options="categories" />
        </label>
        <label class="check-line">
          <input v-model="confirmed" type="checkbox" />
          已确认可用
        </label>
        <span class="spacer" />
        <button type="button" :disabled="busy" @click="emit('cancel')">取消</button>
        <button type="button" class="primary" :disabled="busy" @click="submit">保存修改</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.edit {
  border-color: color-mix(in srgb, var(--accent) 40%, var(--line));
}
.check-line {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
  color: var(--muted);
  cursor: pointer;
  user-select: none;
  padding-top: 1.35rem;
}
.check-line input {
  width: auto;
  margin: 0;
}
</style>

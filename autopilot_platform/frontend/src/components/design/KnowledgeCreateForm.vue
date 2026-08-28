<script setup lang="ts">
import { ref } from "vue";
import ApSelect from "../common/ApSelect.vue";

const props = defineProps<{ busy?: boolean }>();
const emit = defineEmits<{
  create: [payload: { title: string; content: string; category: string; confirmed: boolean }];
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

function submit() {
  emit("create", {
    title: title.value,
    content: content.value,
    category: category.value,
    confirmed: confirmed.value,
  });
}

function clear() {
  title.value = "";
  content.value = "";
}

defineExpose({ clear });
</script>

<template>
  <section class="surface-card">
    <h3>新增知识</h3>
    <div class="field-stack">
      <label class="field-label">
        标题
        <input v-model="title" placeholder="例如：iOS 首次安装系统弹框处理" />
      </label>
      <label class="field-label">
        正文
        <textarea v-model="content" rows="4" placeholder="写清场景、约束与建议处理方式…" />
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
        <button type="button" class="primary" :disabled="props.busy" @click="submit">保存</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
textarea {
  resize: vertical;
  min-height: 5.5rem;
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

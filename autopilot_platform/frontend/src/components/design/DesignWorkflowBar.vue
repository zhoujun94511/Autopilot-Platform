<script setup lang="ts">
/**
 * 设计域工作流条：高亮「建议进度步」，不是「当前打开的页」。
 * 主路径：意图用例（粘贴/勾选生成 → 人审）；
 * 旁路：需求文档（有材料）、知识库（可选增强）。
 */
import { computed, onMounted, ref, watch } from "vue";
import { ensureFreshSession } from "../../api";
import { fetchDesignStats, type DesignDomainStats } from "../../api/designStats";
import { storeToRefs } from "pinia";
import { useProjectsStore } from "../../stores/projectsStore";
import { useShellStore } from "../../stores/shellStore";
import { useAuthStore } from "../../stores/auth";
import { useExecStore } from "../../stores/execution";
import { deriveDesignNextAction } from "./designWorkflowProgress";

export type DesignWorkflowPage = "knowledge" | "docs" | "cases" | "dashboard";

const props = withDefaults(
  defineProps<{
    page?: DesignWorkflowPage;
    compact?: boolean;
  }>(),
  { page: "dashboard", compact: false },
);

const auth = useAuthStore();
const shell = useShellStore();
const projectsStore = useProjectsStore();
const { filterProjectId } = storeToRefs(projectsStore);
const { loggedIn } = storeToRefs(auth);
const exec = useExecStore();
const { artifacts } = storeToRefs(exec);

const stats = ref<DesignDomainStats | null>(null);
const loading = ref(false);

const nextAction = computed(() =>
  deriveDesignNextAction(stats.value, {
    artifacts: artifacts.value,
    projectId: filterProjectId.value || "",
  }),
);
const focusHint = computed(() => nextAction.value.hint);

async function loadStats() {
  if (!loggedIn.value) {
    stats.value = null;
    return;
  }
  loading.value = true;
  try {
    const ready = await ensureFreshSession();
    if (!ready || !loggedIn.value) {
      stats.value = null;
      return;
    }
    stats.value = await fetchDesignStats(filterProjectId.value || undefined);
    await shell.refreshScopes(["artifacts"]);
  } catch {
    stats.value = null;
  } finally {
    loading.value = false;
  }
}

function go(tab: string) {
  shell.activeTab = tab;
}

onMounted(() => void loadStats());
watch(
  () => [filterProjectId.value, loggedIn.value, shell.activeTab] as const,
  () => void loadStats(),
);
</script>

<template>
  <nav
    class="design-workflow"
    :class="{ compact: props.compact }"
    aria-label="设计域工作流"
  >
    <div class="workflow-row">
      <ol class="steps">
        <li
          class="step"
          :class="{
            focus: nextAction.focus === 'cases' && !nextAction.done.has('cases'),
            done: nextAction.done.has('cases'),
            here: props.page === 'cases',
          }"
        >
          <button
            type="button"
            class="step-btn"
            title="粘贴需求或勾选文档 → 生成草稿 → 审核通过"
            :aria-current="nextAction.focus === 'cases' ? 'step' : undefined"
            @click="go('design-cases')"
          >
            <span class="idx">1</span>
            <span class="label">意图用例</span>
          </button>
        </li>
        <li class="step-sep" aria-hidden="true">→</li>
        <li
          class="step"
          :class="{
            focus: nextAction.focus === 'run',
            done: nextAction.done.has('run'),
          }"
        >
          <button
            type="button"
            class="step-btn"
            title="在 IDE 上传工程 → 选设备 → 加入批跑"
            :aria-current="nextAction.focus === 'run' ? 'step' : undefined"
            @click="go('design-cases')"
          >
            <span class="idx">2</span>
            <span class="label">批跑入队</span>
          </button>
        </li>
      </ol>
      <div class="side-links">
        <button
          type="button"
          class="side-link"
          :class="{ here: props.page === 'docs', ready: nextAction.hasDocs }"
          title="有 Word/PDF/PRD 等材料时批量导入分析"
          @click="go('design-docs')"
        >
          有材料：需求文档
        </button>
        <button
          type="button"
          class="side-link"
          :class="{ here: props.page === 'knowledge', ready: nextAction.hasKnowledge }"
          title="记下常用规则，生成用例时可以用"
          @click="go('design-knowledge')"
        >
          可选：知识库
        </button>
      </div>
    </div>
    <p v-if="!props.compact" class="hint">
      <span v-if="loading && !stats">正在读取进度…</span>
      <template v-else>{{ focusHint }}</template>
      <button
        v-if="props.page !== 'dashboard'"
        type="button"
        class="linkish"
        @click="go('design-dashboard')"
      >
        设计总览
      </button>
    </p>
  </nav>
</template>

<style scoped>
.design-workflow {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 0.55rem 0.75rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
}
.design-workflow.compact {
  padding: 0.35rem 0.5rem;
}
.workflow-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem 0.75rem;
}
.steps {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.15rem;
  margin: 0;
  padding: 0;
  list-style: none;
}
.step {
  display: inline-flex;
  align-items: center;
  gap: 0.15rem;
}
.step-sep {
  color: var(--muted);
  font-size: 0.75rem;
  user-select: none;
}
.step-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0;
  padding: 0.3rem 0.55rem;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: 0.82rem;
  cursor: pointer;
}
.step-btn:hover {
  color: var(--text);
  background: var(--nav-hover);
}
.step.focus .step-btn {
  color: var(--accent-text, var(--text));
  border-color: var(--accent);
  background: var(--nav-active-bg, rgba(127, 127, 127, 0.12));
  font-weight: 600;
}
.step.focus .idx {
  border-color: var(--accent);
  background: var(--accent);
  color: var(--panel);
}
.step.done .step-btn {
  color: var(--text);
}
.step.done .idx {
  border-color: var(--ok-soft-border, var(--line));
  background: var(--ok-soft-bg, transparent);
}
.step.here:not(.focus) .step-btn {
  border-color: var(--line);
  color: var(--text);
}
.idx {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.25rem;
  height: 1.25rem;
  border-radius: 999px;
  border: 1px solid var(--line);
  font-size: 0.72rem;
  font-weight: 600;
}
.side-links {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}
.side-link {
  margin: 0;
  padding: 0.25rem 0.45rem;
  border: 1px dashed var(--line);
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: 0.75rem;
  cursor: pointer;
}
.side-link:hover {
  color: var(--text);
  border-color: var(--border-strong, var(--line));
}
.side-link.here {
  color: var(--text);
  border-style: solid;
}
.side-link.ready {
  border-color: var(--ok-soft-border, var(--line));
}
.hint {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.25rem;
  margin: 0;
  font-size: 0.78rem;
  color: var(--muted);
  line-height: 1.45;
  white-space: normal;
  overflow-wrap: break-word;
}
.here-note {
  opacity: 0.85;
}
.linkish {
  margin-left: 0.5rem;
  padding: 0;
  border: none;
  background: none;
  color: var(--accent);
  font: inherit;
  font-size: inherit;
  cursor: pointer;
  text-decoration: underline;
}
.compact .hint {
  display: none;
}
.compact .label {
  font-size: 0.78rem;
}
</style>

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

const nextAction = computed(() =>
  deriveDesignNextAction(stats.value, {
    artifacts: artifacts.value,
    projectId: filterProjectId.value || "",
  }),
);
async function loadStats() {
  if (!loggedIn.value) {
    stats.value = null;
    return;
  }
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
            title="生成与审核"
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
            title="选择设备后入队"
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
          title="导入需求文档"
          @click="go('design-docs')"
        >
          需求文档
        </button>
        <button
          type="button"
          class="side-link"
          :class="{ here: props.page === 'knowledge', ready: nextAction.hasKnowledge }"
          title="知识库"
          @click="go('design-knowledge')"
        >
          知识库
        </button>
      </div>
    </div>
  </nav>
</template>

<style scoped>
.design-workflow {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 0.55rem 0.75rem;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
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
  border-radius: var(--radius-md);
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
  border-radius: var(--radius-sm);
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
  border-radius: var(--radius-md);
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
.compact .label {
  font-size: 0.78rem;
}
</style>

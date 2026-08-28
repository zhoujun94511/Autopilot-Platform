<script setup lang="ts">
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useShellStore } from "../../stores/shellStore";
import { useOpsStore } from "../../stores/opsStore";
import {
  DEFAULT_DESIGN_WEBHOOK_URL,
  IDE_WEBHOOK_ALTERNATIVES,
  IDE_WEBHOOK_SETUP_STEPS,
} from "./ideWebhookGuide";

const props = withDefaults(
  defineProps<{
    approvedCount?: number;
    compact?: boolean;
  }>(),
  { approvedCount: 0, compact: false },
);

const shell = useShellStore();
const ops = useOpsStore();
const { opsConfig } = storeToRefs(ops);


/** 优先读运维配置；未配置时展示本机 IDE 默认回调地址作示例。 */
const webhookUrl = computed(() => {
  const configured = String(opsConfig.value?.MC_DESIGN_WEBHOOK_URL || "").trim();
  return configured || DEFAULT_DESIGN_WEBHOOK_URL;
});

const webhookConfigured = computed(() =>
  Boolean(String(opsConfig.value?.MC_DESIGN_WEBHOOK_URL || "").trim()),
);

function goOpsWebhook() {
  shell.openOpsConfig("webhook_alert");
}
</script>

<template>
  <section
    v-if="approvedCount > 0"
    class="surface-card ide-webhook-guide"
    :class="{ compact: props.compact }"
    aria-labelledby="ide-webhook-guide-title"
  >
    <h3 id="ide-webhook-guide-title">高级可选：审核通过后自动导入 IDE</h3>
    <p class="lede">
      已有 {{ approvedCount }} 条审核通过的用例。若希望审核后自动写回本机工程，按下面步骤配置。
    </p>
    <ol>
      <li v-for="(step, i) in IDE_WEBHOOK_SETUP_STEPS" :key="i">{{ step }}</li>
    </ol>
    <p class="meta-line">
      <template v-if="webhookConfigured">当前通知地址：</template>
      <template v-else>示例本机地址（尚未在运维里配置）：</template>
      <code>{{ webhookUrl }}</code>
      <button type="button" class="linkish" @click="goOpsWebhook">去运维配置</button>
    </p>
    <details v-if="!compact">
      <summary>不配自动导入时，也可以这样</summary>
      <ul>
        <li v-for="(alt, i) in IDE_WEBHOOK_ALTERNATIVES" :key="i">{{ alt }}</li>
      </ul>
    </details>
  </section>
</template>

<style scoped>
.ide-webhook-guide {
  padding: 0.85rem 1rem;
}
.lede {
  margin: 0 0 0.55rem;
  font-size: 0.78rem;
  color: var(--muted);
  line-height: 1.45;
}
.ide-webhook-guide ol,
.ide-webhook-guide ul {
  margin: 0.35rem 0 0.55rem;
  padding-left: 1.25rem;
  font-size: 0.78rem;
  line-height: 1.45;
  color: var(--muted);
}
.meta-line {
  margin: 0;
  font-size: 0.76rem;
  color: var(--muted);
}
.linkish {
  margin-left: 0.45rem;
  padding: 0;
  border: none;
  background: none;
  color: var(--accent);
  font: inherit;
  font-size: inherit;
  cursor: pointer;
  text-decoration: underline;
}
.compact .lede {
  display: none;
}
</style>

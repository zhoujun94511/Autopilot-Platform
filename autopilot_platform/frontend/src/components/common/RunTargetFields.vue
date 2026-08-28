<script setup lang="ts">
/**
 * 执行目标：设备 / Web 浏览器与引擎 / 并行 / 后端 / WDA。
 * JobCreate、入队、计划共用，避免三处字段漂移。
 */
import { computed, watch } from "vue";
import type { Device } from "../../api";
import {
  applyPlatformSideEffects,
  isHttpPlatform,
  isWebPlatform,
  MOBILE_BACKEND_OPTIONS,
  WEB_BROWSER_OPTIONS,
  WEB_ENGINE_OPTIONS,
  type RunTargetModel,
} from "../../composables/runTargetOptions";
import DevicePicker from "../DevicePicker.vue";
import ApSelect from "./ApSelect.vue";

const props = withDefaults(
  defineProps<{
    model: RunTargetModel;
    devices?: readonly Device[];
    disabled?: boolean;
    compact?: boolean;
    idPrefix?: string;
  }>(),
  {
    devices: () => [],
    disabled: false,
    compact: false,
    idPrefix: "run-target",
  },
);

const isWeb = computed(() => isWebPlatform(props.model.platform));
const isHttp = computed(() => isHttpPlatform(props.model.platform));
const selectSize = computed(() => (props.compact ? "compact" : "default"));

watch(
  () => props.model.platform,
  (p) => applyPlatformSideEffects(props.model, p || ""),
);
</script>

<template>
  <div class="run-target" :class="{ compact }">
    <template v-if="isWeb">
      <h3 v-if="!compact" class="run-target-title">
        执行节点
        <span class="title-optional">可选 · 留空由任意具备 Web 能力的节点领取</span>
      </h3>
      <p class="run-target-hint">
        网页用例不需要手机。由带浏览器的执行节点来跑；打开哪个网站由用例里的步骤决定。
      </p>
      <div class="run-target-grid">
        <div class="run-field">
          <label :for="`${idPrefix}-web-browser`">浏览器类型</label>
          <ApSelect
            :id="`${idPrefix}-web-browser`"
            v-model="model.backend_mode"
            aria-label="浏览器类型"
            :disabled="disabled"
            :size="selectSize"
            :options="WEB_BROWSER_OPTIONS"
          />
          <p class="run-target-hint">选了具体浏览器后，用例里没写浏览器类型的步骤会用这个。</p>
        </div>
        <div class="run-field">
          <label :for="`${idPrefix}-web-engine`">Web 引擎</label>
          <ApSelect
            :id="`${idPrefix}-web-engine`"
            v-model="model.web_engine"
            aria-label="Web 引擎"
            :disabled="disabled"
            :size="selectSize"
            :options="WEB_ENGINE_OPTIONS"
          />
          <p class="run-target-hint">和上面的浏览器分开选。用 Playwright 时，执行节点需要已安装。</p>
        </div>
        <div class="run-field">
          <label :for="`${idPrefix}-runner-web`">指定执行节点</label>
          <input
            :id="`${idPrefix}-runner-web`"
            v-model="model.preferred_runner_id"
            :disabled="disabled"
            placeholder="可选：留空自动选具备 Web 能力的节点"
          />
        </div>
      </div>
    </template>

    <template v-else-if="isHttp">
      <h3 v-if="!compact" class="run-target-title">
        执行节点
        <span class="title-optional">可选 · 留空由任意具备 HTTP 能力的节点领取</span>
      </h3>
      <p class="run-target-hint">
        接口用例不需要手机或浏览器。环境来自工程里的 api_env.yaml；也可在步骤里用「切换API环境」。
      </p>
      <div class="run-target-grid">
        <div class="run-field">
          <label :for="`${idPrefix}-http-profile`">API 环境 profile</label>
          <input
            :id="`${idPrefix}-http-profile`"
            v-model="model.backend_mode"
            :disabled="disabled"
            placeholder="auto 或 api_env.yaml 中的名称，如 dev"
          />
          <p class="run-target-hint">
            auto = 不预注入，由用例步骤切换。填了名称后会写入 base_url 等变量。
          </p>
        </div>
        <div class="run-field">
          <label :for="`${idPrefix}-runner-http`">指定执行节点</label>
          <input
            :id="`${idPrefix}-runner-http`"
            v-model="model.preferred_runner_id"
            :disabled="disabled"
            placeholder="可选：留空自动选具备 HTTP 能力的节点"
          />
        </div>
      </div>
    </template>

    <template v-else>
      <DevicePicker
        v-model="model.device_udids"
        :devices="devices"
        :platform="model.platform"
        :backend-mode="model.backend_mode"
        :disabled="disabled"
        :compact="compact"
        :input-id="`${idPrefix}-udids`"
      />
      <div class="run-target-mobile-extras">
        <div class="run-field flex-one">
          <label :for="`${idPrefix}-runner`">指定执行节点</label>
          <input
            :id="`${idPrefix}-runner`"
            v-model="model.preferred_runner_id"
            :disabled="disabled"
            placeholder="可选"
          />
        </div>
        <div class="run-field checkbox-field">
          <label class="checkbox-label">
            <input v-model="model.parallel" type="checkbox" :disabled="disabled" />
            <span>多设备并行</span>
          </label>
        </div>
        <div class="run-field workers-field">
          <label :for="`${idPrefix}-workers`">并发数</label>
          <input
            :id="`${idPrefix}-workers`"
            v-model.number="model.parallel_workers"
            type="number"
            min="0"
            max="64"
            :disabled="disabled || !model.parallel"
            placeholder="自动"
          />
          <p class="run-target-hint">0 = 按设备数全开</p>
        </div>
      </div>
      <p v-if="!compact" class="run-target-hint">
        占用中的设备不可提交；手填未知设备或留空设备列表时会二次确认。
      </p>
      <details class="run-target-advanced">
        <summary>高级选项：执行后端 / iOS 参数</summary>
        <div class="run-target-grid advanced-grid">
          <div class="run-field">
            <label :for="`${idPrefix}-backend`">设备后端模式</label>
            <ApSelect
              :id="`${idPrefix}-backend`"
              v-model="model.backend_mode"
              aria-label="设备后端模式"
              :disabled="disabled"
              :size="selectSize"
              :options="MOBILE_BACKEND_OPTIONS"
            />
            <p class="run-target-hint">默认「自动」即可；仅在需要强制某后端时更改。</p>
          </div>
          <div class="run-field">
            <label :for="`${idPrefix}-wda`">iOS 驱动包名（一般不用填）</label>
            <input
              :id="`${idPrefix}-wda`"
              v-model="model.wda_bundle"
              :disabled="disabled"
              placeholder="仅直连 iOS 驱动时需要"
            />
          </div>
        </div>
      </details>
    </template>
  </div>
</template>

<style scoped>
.run-target-title {
  margin: 0 0 0.4rem;
  font-size: 0.92rem;
  font-weight: 650;
}

.title-optional {
  margin-left: 0.4rem;
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--muted);
}

.run-target-hint {
  margin: 0.15rem 0 0;
  font-size: 0.75rem;
  color: var(--muted);
  font-style: italic;
  line-height: 1.4;
}

.run-target-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
  gap: 0.75rem 1rem;
  margin-top: 0.75rem;
  max-width: 48rem;
}

.run-target-mobile-extras {
  display: grid;
  grid-template-columns: 2fr 1fr auto 6.5rem;
  gap: 1rem;
  align-items: end;
  margin-top: 0.75rem;
}

.run-field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  min-width: 0;
}

.run-field label {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--muted);
}

.run-field input {
  font-weight: 400;
}

.flex-one {
  min-width: 0;
}

.checkbox-field {
  padding-bottom: 0.55rem;
  justify-content: flex-end;
}

.checkbox-label {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text);
}

.workers-field input:disabled {
  opacity: 0.55;
}

.run-target-advanced {
  margin-top: 0.85rem;
  font-size: 0.82rem;
}

.run-target-advanced summary {
  cursor: pointer;
  color: var(--muted);
  font-weight: 600;
}

.advanced-grid {
  max-width: none;
}

.compact .run-target-mobile-extras {
  grid-template-columns: 1fr;
  gap: 0.65rem;
}

.compact .run-target-grid {
  margin-top: 0.5rem;
  max-width: none;
}

@media (max-width: 720px) {
  .run-target-mobile-extras {
    grid-template-columns: 1fr;
  }
}
</style>

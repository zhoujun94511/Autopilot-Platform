<script setup lang="ts">
import { computed } from "vue";
import { useRemoteDeviceLogs } from "../../composables/remote/useRemoteDeviceLogs";
import ApSelect from "../common/ApSelect.vue";

const props = defineProps<{ platform: string; readonly?: boolean }>();
const {
  android,
  androidLevels,
  iosLevels,
  sessionReady,
  level,
  tag,
  grep,
  regexOn,
  proc,
  wrap,
  showTs,
  streaming,
  autoscroll,
  atBottom,
  error,
  status,
  copied,
  searchErr,
  viewEl,
  visibleLines,
  totalCount,
  visibleCount,
  displayMsg,
  toggleStream,
  clearAll,
  save,
  copyLines,
  onScroll,
  jumpBottom,
} = useRemoteDeviceLogs(props.platform, Boolean(props.readonly));

const androidLevelOptions = computed(() =>
  androidLevels.map((item) => ({
    value: item.value,
    label: item.label,
    title: item.hint,
  })),
);
const iosLevelOptions = computed(() =>
  iosLevels.map((item) => ({ value: item.value, label: item.label })),
);
</script>

<template>
  <section class="remote-tool-panel remote-log-panel">
    <header>
      <div>
        <h3>{{ android ? "Logcat" : "设备日志" }}</h3>
        <p class="remote-log-sub">
          {{
            android
              ? "最低级别和 Tag 发给设备；内容过滤只在本页生效。"
              : "文本 / 正则 / 进程 / 级别只在本页过滤。"
          }}
        </p>
      </div>
      <span class="remote-log-pill" :class="streaming ? 'on' : 'off'">{{ status }}</span>
    </header>

    <div class="remote-log-toolbar remote-log-actions">
      <button
        type="button"
        class="small remote-log-action"
        :class="{ primary: !streaming && sessionReady }"
        :disabled="!sessionReady"
        :title="streaming ? '暂停接收' : '开始接收设备日志'"
        @click="toggleStream"
      >
        {{ streaming ? "暂停" : sessionReady ? "继续" : "等待会话" }}
      </button>
      <button type="button" class="small" :disabled="!visibleCount" @click="copyLines">
        {{ copied ? "已复制" : "复制" }}
      </button>
      <button type="button" class="small" :disabled="!sessionReady" @click="clearAll">
        清空
      </button>
      <button type="button" class="small" :disabled="android ? !visibleCount : !totalCount" @click="save">
        {{ android ? "保存" : "导出" }}
      </button>
    </div>

    <div class="remote-log-toolbar remote-log-filters">
      <template v-if="android">
        <label class="remote-log-field">
          <span>最低级别</span>
          <ApSelect
            v-model="level"
            stack
            size="toolbar"
            :disabled="!sessionReady"
            :options="androidLevelOptions"
            title="传给 logcat 的最低级别，低于此级的行不会从设备拉上来"
            aria-label="最低级别"
          />
        </label>
        <label class="remote-log-field remote-log-field-grow">
          <span>Tag</span>
          <input
            v-model="tag"
            type="text"
            placeholder="单个 tag，例如 ActivityManager"
            :disabled="!sessionReady"
          />
        </label>
        <label class="remote-log-field remote-log-field-grow">
          <span>内容过滤</span>
          <input v-model="grep" type="text" placeholder="子串过滤（仅本页）" />
        </label>
      </template>
      <template v-else>
        <label class="remote-log-field remote-log-field-grow">
          <span>内容过滤</span>
          <input
            v-model="grep"
            type="text"
            :class="{ bad: searchErr }"
            :placeholder="regexOn ? '正则，例如 SpringBoard|locationd' : '过滤文本…'"
          />
        </label>
        <button
          type="button"
          class="small remote-log-toggle"
          :class="{ primary: regexOn }"
          title="使用正则"
          @click="regexOn = !regexOn"
        >
          .*
        </button>
        <label class="remote-log-field">
          <span>进程</span>
          <input v-model="proc" type="text" placeholder="例如 SpringBoard" />
        </label>
        <label class="remote-log-field">
          <span>级别</span>
          <ApSelect
            v-model="level"
            stack
            size="toolbar"
            :options="iosLevelOptions"
            title="按 syslog 级别筛选"
            aria-label="级别"
          />
        </label>
      </template>
    </div>

    <div class="remote-log-opts">
      <label v-if="android" class="remote-switch">
        <input v-model="autoscroll" type="checkbox" />
        自动滚动
      </label>
      <label v-if="!android" class="remote-switch">
        <input v-model="showTs" type="checkbox" />
        时间戳
      </label>
      <label class="remote-switch">
        <input v-model="wrap" type="checkbox" />
        自动换行
      </label>
      <span class="muted remote-log-counter">{{ visibleCount }} / {{ totalCount }}</span>
    </div>

    <div class="remote-log-wrap">
      <div
        ref="viewEl"
        class="remote-log-view"
        :class="{ nowrap: !wrap, android: android }"
        @scroll="onScroll"
      >
        <div v-if="!sessionReady" class="muted remote-log-empty">远控会话尚未就绪。</div>
        <div v-else-if="!visibleLines.length && totalCount" class="muted remote-log-empty">
          无匹配日志。
        </div>
        <div v-else-if="!visibleLines.length" class="muted remote-log-empty">
          {{ streaming ? "等待设备输出…" : "已暂停，点「继续」恢复。" }}
        </div>
        <div
          v-for="line in visibleLines"
          :key="line.k"
          class="remote-log-line"
          :class="'lvl-' + line.lvl"
          :title="line.raw"
        >{{ displayMsg(line) }}</div>
      </div>
      <button
        v-if="!atBottom && visibleCount"
        type="button"
        class="remote-log-jump"
        title="跳到底部"
        @click="jumpBottom"
      >
        ↓
      </button>
    </div>
    <p v-if="error" class="remote-log-error">{{ error }}</p>
  </section>
</template>

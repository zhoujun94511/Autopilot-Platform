<script setup lang="ts">
import { computed } from "vue";
import {
  PAGE_SIZE_OPTIONS,
  buildPageNav,
  rangeLabel,
  totalPages,
} from "../../utils/pagination";
import ApSelect from "./ApSelect.vue";

/**
 * 统一分页组件
 *
 * - page：页码翻页（管理台表格默认）
 * - more：仅「加载更多」（聊天会话等时间线）
 *
 * 边界交互：
 * - 仅 1 页时整条隐藏（避免「共 3 条 · 当前第 1–3」加一颗死页码）
 * - 多页时始终显示，首尾页置灰 disabled（避免翻页布局跳动）
 */
const props = withDefaults(
  defineProps<{
    mode?: "page" | "more";
    loading?: boolean;
    disabled?: boolean;
    total?: number;
    page?: number;
    pageSize?: number;
    /** more 模式 */
    loaded?: number;
    hasMore?: boolean;
    loadMoreLabel?: string;
  }>(),
  {
    mode: "page",
    loading: false,
    disabled: false,
    total: 0,
    page: 1,
    pageSize: 50,
    loaded: 0,
    hasMore: false,
    loadMoreLabel: "加载更多",
  },
);

const emit = defineEmits<{
  "update:page": [page: number];
  "update:pageSize": [size: number];
  "load-more": [];
}>();

const pages = computed(() => totalPages(props.total, props.pageSize));
const multiPage = computed(() => pages.value > 1);
const pageLabel = computed(() => rangeLabel(props.total, props.page, props.pageSize));
const navItems = computed(() => buildPageNav(props.total, props.page, props.pageSize));
const canPrev = computed(() => props.page > 1 && !props.loading && !props.disabled);
const canNext = computed(() => props.page < pages.value && !props.loading && !props.disabled);

const moreLabel = computed(() => {
  if (props.loading && props.loaded <= 0) return "加载中…";
  if (props.loaded <= 0) return "暂无数据";
  return props.hasMore
    ? `已加载 ${props.loaded} 条 · 还有更多`
    : `共 ${props.loaded} 条 · 已全部加载`;
});

function go(p: number) {
  const next = Math.min(pages.value, Math.max(1, p));
  if (next !== props.page) emit("update:page", next);
}

const pageSizeOptions = PAGE_SIZE_OPTIONS.map((n) => ({
  value: String(n),
  label: String(n),
}));

function onPageSize(v: string) {
  const n = Number(v) || props.pageSize;
  emit("update:pageSize", n);
}
</script>

<template>
  <div v-if="mode === 'page' && multiPage" class="list-pager">
    <span class="list-pager-meta">{{ loading ? "加载中…" : pageLabel }}</span>
    <div class="list-pager-controls">
      <label class="list-pager-size">
        每页
        <ApSelect
          size="compact"
          aria-label="每页条数"
          :model-value="String(pageSize)"
          :options="pageSizeOptions"
          :disabled="disabled || loading"
          @update:model-value="onPageSize"
        />
      </label>
      <button
        v-if="multiPage"
        type="button"
        class="small pager-nav"
        :disabled="!canPrev"
        :aria-disabled="!canPrev"
        aria-label="上一页"
        @click="go(page - 1)"
      >
        上一页
      </button>
      <div class="pager-nums" role="navigation" aria-label="页码">
        <template v-for="(item, idx) in navItems" :key="`${item.kind}-${idx}`">
          <span v-if="item.kind === 'ellipsis'" class="pager-ellipsis" aria-hidden="true">…</span>
          <button
            v-else
            type="button"
            class="small pager-num"
            :class="{ active: item.active }"
            :disabled="disabled || loading || item.active"
            :aria-current="item.active ? 'page' : undefined"
            :aria-label="`第 ${item.page} 页`"
            @click="go(item.page)"
          >
            {{ item.page }}
          </button>
        </template>
      </div>
      <button
        v-if="multiPage"
        type="button"
        class="small pager-nav"
        :disabled="!canNext"
        :aria-disabled="!canNext"
        aria-label="下一页"
        @click="go(page + 1)"
      >
        下一页
      </button>
    </div>
  </div>
  <div v-else-if="mode === 'more' && (loaded > 0 || hasMore)" class="list-pager list-pager-more">
    <span class="list-pager-meta">{{ loading ? "加载中…" : moreLabel }}</span>
    <div v-if="hasMore" class="list-pager-controls">
      <button type="button" class="small" :disabled="loading || disabled" @click="emit('load-more')">
        {{ loadMoreLabel }}
      </button>
    </div>
  </div>
</template>

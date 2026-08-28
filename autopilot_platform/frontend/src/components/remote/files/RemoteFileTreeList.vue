<script setup lang="ts">
import { computed } from "vue";
import { canPreviewFile } from "../../../composables/remote/files/filePreviewKind";
import { formatFileSize } from "../../../composables/remote/files/formatFileSize";
import {
  collapseAndroidLazyTree,
  flattenAndroidLazyTree,
  androidLazyTreeAnyExpanded,
  type AndroidLazyTreeNode,
} from "../../../composables/remote/files/androidLazyTree";
import {
  collapseIosFsyncTree,
  flattenIosFsyncTree,
  iosTreeAnyExpanded,
  type IosFsyncTreeNode,
} from "../../../composables/remote/files/parseIosFsyncTree";
import RemoteFileIconBtn from "./RemoteFileIconBtn.vue";

type TreeVariant = "ios" | "android";

const props = defineProps<{
  variant: TreeVariant;
  iosNodes?: IosFsyncTreeNode[];
  androidNodes?: AndroidLazyTreeNode[];
  loading?: boolean;
  readonly?: boolean;
  canMutate?: boolean;
}>();

const emit = defineEmits<{
  toggle: [node: IosFsyncTreeNode | AndroidLazyTreeNode];
  download: [node: IosFsyncTreeNode | AndroidLazyTreeNode];
  preview: [node: IosFsyncTreeNode | AndroidLazyTreeNode];
  rename: [node: IosFsyncTreeNode | AndroidLazyTreeNode];
  remove: [node: IosFsyncTreeNode | AndroidLazyTreeNode];
}>();

const visibleRows = computed(() =>
  props.variant === "ios"
    ? flattenIosFsyncTree(props.iosNodes || [])
    : flattenAndroidLazyTree(props.androidNodes || []),
);

const hasNodes = computed(() =>
  props.variant === "ios"
    ? (props.iosNodes?.length || 0) > 0
    : (props.androidNodes?.length || 0) > 0,
);

const anyExpanded = computed(() =>
  props.variant === "ios"
    ? iosTreeAnyExpanded(props.iosNodes || [])
    : androidLazyTreeAnyExpanded(props.androidNodes || []),
);

function onRow(node: IosFsyncTreeNode | AndroidLazyTreeNode) {
  if (node.isDir) {
    emit("toggle", node);
    return;
  }
  if (canPreviewFile(node.name)) emit("preview", node);
  else emit("download", node);
}

function collapseAll() {
  if (props.variant === "ios") collapseIosFsyncTree(props.iosNodes || []);
  else collapseAndroidLazyTree(props.androidNodes || []);
}

function nodeSize(node: IosFsyncTreeNode | AndroidLazyTreeNode): string {
  if (node.isDir) return "";
  const size = "size" in node ? node.size : undefined;
  return size != null ? formatFileSize(size) : "";
}

function isNodeLoading(node: IosFsyncTreeNode | AndroidLazyTreeNode): boolean {
  return "loading" in node && Boolean(node.loading);
}
</script>

<template>
  <div class="remote-file-tree-wrap">
    <div v-if="hasNodes" class="remote-file-tree-head">
      <span class="muted">点击行展开目录或打开文件；右侧按钮可直接操作</span>
      <button v-if="anyExpanded" type="button" class="link-btn" @click="collapseAll">
        全部收起
      </button>
    </div>
    <div v-if="hasNodes" class="remote-file-tree" role="tree">
      <div
        v-for="row in visibleRows"
        :key="row.node.path"
        class="remote-file-tree-row"
        :class="{ dir: row.node.isDir, loading: isNodeLoading(row.node) }"
        role="treeitem"
        :style="{ paddingLeft: `${4 + row.depth * 14}px` }"
        @click="onRow(row.node)"
      >
        <span class="remote-file-tree-twist" aria-hidden="true">
          {{
            row.node.isDir
              ? isNodeLoading(row.node)
                ? "…"
                : row.node.expanded
                  ? "▾"
                  : "▸"
              : ""
          }}
        </span>
        <span class="remote-file-tree-kind" aria-hidden="true">
          {{ row.node.isDir ? "📁" : "📄" }}
        </span>
        <span class="remote-file-tree-name" :title="row.node.path">{{ row.node.name }}</span>
        <span class="remote-file-tree-size muted">{{ nodeSize(row.node) }}</span>
        <span class="remote-file-tree-actions" @click.stop>
          <RemoteFileIconBtn
            v-if="row.node.isDir"
            :title="row.node.expanded ? '收起' : '展开'"
            :label="row.node.expanded ? '收起目录' : '展开目录'"
            @click="emit('toggle', row.node)"
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              aria-hidden="true"
              class="remote-file-tree-chevron"
              :class="{ expanded: row.node.expanded && !isNodeLoading(row.node) }"
            >
              <path d="M9 6l6 6-6 6" />
            </svg>
          </RemoteFileIconBtn>
          <template v-else>
            <RemoteFileIconBtn
              v-if="canPreviewFile(row.node.name)"
              title="预览"
              label="预览"
              @click="emit('preview', row.node)"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
            </RemoteFileIconBtn>
            <RemoteFileIconBtn title="下载" label="下载" @click="emit('download', row.node)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                <path d="M12 3v12" />
                <path d="m7 12 5 5 5-5" />
                <path d="M5 21h14" />
              </svg>
            </RemoteFileIconBtn>
          </template>
          <RemoteFileIconBtn
            v-if="canMutate"
            title="重命名"
            label="重命名"
            @click="emit('rename', row.node)"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path d="M12 20h9" />
              <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
            </svg>
          </RemoteFileIconBtn>
          <RemoteFileIconBtn
            v-if="canMutate"
            variant="danger"
            :title="row.node.isDir ? '删除目录' : '删除文件'"
            label="删除"
            @click="emit('remove', row.node)"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path d="M3 6h18" />
              <path d="M8 6V4h8v2" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
              <path d="M10 11v6" />
              <path d="M14 11v6" />
            </svg>
          </RemoteFileIconBtn>
        </span>
      </div>
    </div>
    <p v-else-if="!loading" class="muted remote-file-empty">目录为空</p>
  </div>
</template>

<style scoped>
.remote-file-tree-wrap {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: 0.45rem;
}

.remote-file-tree-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
  flex-shrink: 0;
  font-size: 0.75rem;
  line-height: 1.35;
}

.link-btn {
  padding: 0;
  border: none;
  background: transparent;
  color: var(--brand, var(--accent-text));
  font-size: 0.75rem;
  cursor: pointer;
  flex-shrink: 0;
}

.link-btn:hover {
  text-decoration: underline;
}

.remote-file-tree {
  flex: 1;
  min-height: 10rem;
  overflow: auto;
  padding: 0.35rem;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md, 6px);
  background: var(--surface-soft);
}

.remote-file-tree-row {
  display: grid;
  grid-template-columns: 0.85rem 1.15rem minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 0.35rem;
  padding: 0.32rem 0.4rem;
  border-radius: var(--radius-md, 6px);
  font-size: 0.82rem;
  cursor: pointer;
  color: var(--text);
}

.remote-file-tree-row:hover {
  background: var(--action-hover);
}

.remote-file-tree-row:focus-within {
  background: var(--action-selected);
  outline: none;
}

.remote-file-tree-row.loading {
  opacity: 0.7;
}

.remote-file-tree-twist {
  color: var(--muted);
  font-size: 0.68rem;
  text-align: center;
}

.remote-file-tree-kind {
  font-size: 0.85rem;
  line-height: 1;
}

.remote-file-tree-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.remote-file-tree-size {
  flex-shrink: 0;
  min-width: 3.25rem;
  font-size: 0.72rem;
  text-align: right;
  white-space: nowrap;
}

.remote-file-tree-actions {
  display: flex;
  flex-shrink: 0;
  gap: 0.2rem;
  align-items: center;
}

.remote-file-tree-actions :deep(.remote-file-tree-chevron) {
  transition: transform 0.12s ease;
}

.remote-file-tree-actions :deep(.remote-file-tree-chevron.expanded) {
  transform: rotate(90deg);
}

.remote-file-empty {
  margin: 0;
  font-size: 0.82rem;
}
</style>

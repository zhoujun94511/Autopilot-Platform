<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { confirmDialog, promptDialog, toast } from "../../composables/useNotify";
import type { AndroidLazyTreeNode } from "../../composables/remote/files/androidLazyTree";
import type { IosFsyncTreeNode } from "../../composables/remote/files/parseIosFsyncTree";
import { useRemoteFiles } from "../../composables/remote/useRemoteFiles";
import {
  asUploadDirRemote,
  displayUploadDestination,
  joinUploadRemote,
} from "../../composables/remote/files/remoteUploadPath";
import RemoteFileDropOverlay from "./files/RemoteFileDropOverlay.vue";
import RemoteFileIosAppSelector from "./files/RemoteFileIosAppSelector.vue";
import RemoteFilePreviewModal, {
  type RemoteFilePreviewTarget,
} from "./files/RemoteFilePreviewModal.vue";
import RemoteFileToolbar from "./files/RemoteFileToolbar.vue";
import RemoteFileTreeList from "./files/RemoteFileTreeList.vue";
import RemoteFileUploadBar from "./files/RemoteFileUploadBar.vue";

const props = defineProps<{ readonly?: boolean; platform?: string }>();

const files = useRemoteFiles();
const {
  path,
  treeNodes,
  androidTreeNodes,
  treeView,
  listed,
  loading,
  progress,
  transferLabel,
  transferPhase,
  uploadPath,
  iosApp,
  error,
} = files;

const pathInput = ref("");
const fileInput = ref<HTMLInputElement | null>(null);
const dragOver = ref(false);
const previewOpen = ref(false);
const previewTarget = ref<RemoteFilePreviewTarget | null>(null);

const isIos = computed(() => props.platform === "ios");
const canMutate = computed(() => !props.readonly);
const uploading = computed(
  () => transferPhase.value === "sending" || transferPhase.value === "writing",
);
const uploadDestination = computed(() =>
  displayUploadDestination(uploadPath.value, path.value, props.platform),
);

function isAndroidInstallPackage(name: string): boolean {
  const lower = name.toLowerCase();
  return lower.endsWith(".apk") || lower.endsWith(".xapk");
}
const homePath = computed(() => {
  if (!isIos.value) return "/sdcard";
  return iosApp.value ? "/Documents" : ".";
});

const parentPath = computed(() => {
  const current = path.value.replace(/\/+$/, "");
  if (isIos.value) {
    if (!current || current === ".") return ".";
    const index = current.lastIndexOf("/");
    return index <= 0 ? "." : current.slice(0, index);
  }
  const index = current.lastIndexOf("/");
  return index <= 0 ? "/" : current.slice(0, index);
});

onMounted(() => {
  path.value = isIos.value ? homePath.value : "/sdcard";
  pathInput.value = path.value;
  void refreshListing();
});

watch(iosApp, async (next, prev) => {
  if (!isIos.value || next === prev) return;
  path.value = next ? "/Documents" : ".";
  pathInput.value = path.value;
  uploadPath.value = next ? "/Documents" : "";
  await files.list(path.value, next);
});

function syncPathInput(next: string) {
  pathInput.value = next;
}

async function refreshListing() {
  if (isIos.value) await files.list();
  else await files.listAndroidTree();
}

async function navigate(nextPath: string) {
  const trimmed = nextPath.trim() || homePath.value;
  syncPathInput(trimmed);
  if (isIos.value) await files.list(trimmed);
  else await files.listAndroidTree(trimmed);
}

async function goUp() {
  await navigate(parentPath.value);
}

async function goHome() {
  await navigate(homePath.value);
}

async function toggleTreeNode(node: IosFsyncTreeNode | AndroidLazyTreeNode) {
  if (isIos.value) {
    (node as IosFsyncTreeNode).expanded = !(node as IosFsyncTreeNode).expanded;
    return;
  }
  await files.toggleAndroidTreeNode(node as AndroidLazyTreeNode);
}

function toastError(cause: unknown) {
  const message = cause instanceof Error ? cause.message : String(cause);
  toast(message, "error");
}

async function downloadTreeNode(node: IosFsyncTreeNode | AndroidLazyTreeNode) {
  if (node.isDir) {
    await toggleTreeNode(node);
    return;
  }
  try {
    await files.download(node.path, node.name);
    toast(`已下载 ${node.name}`, "success");
  } catch (cause) {
    toastError(cause);
  }
}

async function removeTreeNode(node: IosFsyncTreeNode | AndroidLazyTreeNode) {
  const ok = await confirmDialog(`确定删除 ${node.path}？`, {
    title: "删除设备文件",
    okText: "删除",
    danger: true,
  });
  if (!ok) return;
  try {
    await files.remove(node.path, node.isDir);
    toast(`已删除 ${node.name}`, "success");
  } catch (cause) {
    toastError(cause);
  }
}

async function renameTreeNode(node: IosFsyncTreeNode | AndroidLazyTreeNode) {
  const next = await promptDialog(`路径：${node.path}`, {
    title: "重命名",
    defaultValue: node.name,
    placeholder: "新名称",
  });
  if (!next || next.trim() === node.name) return;
  const parent = node.path.slice(0, node.path.length - node.name.length);
  const dst = `${parent}${next.trim()}`;
  try {
    await files.rename(node.path, dst);
    toast(`已重命名为 ${next.trim()}`, "success");
  } catch (cause) {
    toastError(cause);
  }
}

async function createFolder() {
  const name = await promptDialog(`将在 ${path.value} 下创建`, {
    title: "新建目录",
    placeholder: "目录名称",
  });
  if (!name?.trim()) return;
  const base = path.value.replace(/\/+$/, "") || homePath.value;
  const sep = base.endsWith("/") || base === "." ? "" : "/";
  try {
    await files.mkdir(`${base}${sep}${name.trim()}`);
    toast(`已创建 ${name.trim()}`, "success");
  } catch (cause) {
    toastError(cause);
  }
}

function openPreview(target: RemoteFilePreviewTarget) {
  previewTarget.value = target;
  previewOpen.value = true;
}

function openPreviewFromTree(node: IosFsyncTreeNode | AndroidLazyTreeNode) {
  openPreview({
    name: node.name,
    path: node.path,
    size: "size" in node ? node.size : undefined,
  });
}

async function fetchPreviewBlob(target: RemoteFilePreviewTarget) {
  return files.pullForPreview(target.path, target.name, { size: target.size });
}

function closePreview() {
  previewOpen.value = false;
  previewTarget.value = null;
}

function triggerUploadPick() {
  fileInput.value?.click();
}

async function uploadOne(file: File, installApk = false, forceInstall = false) {
  if (isIos.value) {
    const remote = joinUploadRemote(uploadDestination.value, file.name);
    await files.uploadToPath(file, remote, { installApk, forceInstall });
    return;
  }
  await files.upload(file, {
    remote: asUploadDirRemote(uploadPath.value, path.value),
    installApk,
    forceInstall,
  });
}

async function uploadFiles(selected: File[]) {
  for (const file of selected) {
    let installApk = false;
    if (!isIos.value && isAndroidInstallPackage(file.name)) {
      const kind = file.name.toLowerCase().endsWith(".xapk") ? "XAPK" : "APK";
      installApk = await confirmDialog(
        `检测到 ${kind}「${file.name}」。\n\n确定：安装到设备\n取消：仅上传到当前目录`,
        { title: `${kind} 处理`, okText: "安装", cancelText: "仅上传" },
      );
    }
    try {
      await uploadOne(file, installApk);
      toast(installApk ? `已安装 ${file.name}` : `已上传 ${file.name}`, "success");
    } catch (cause) {
      const err = cause as Error & { errorCode?: string; existingPackage?: string };
      if (err.errorCode === "signature_mismatch") {
        const pkg = err.existingPackage || "已安装应用";
        const force = await confirmDialog(
          `签名冲突：${pkg} 已存在且签名不一致。\n是否卸载后覆盖安装？`,
          { title: "APK 签名冲突", okText: "覆盖安装", cancelText: "取消", danger: true },
        );
        if (force) {
          await uploadOne(file, true, true);
          toast(`已覆盖安装 ${file.name}`, "success");
          continue;
        }
      }
      const message = err.message || String(cause);
      toast(message, "error");
    }
  }
}

async function onPick(event: Event) {
  const input = event.target as HTMLInputElement;
  const picked = Array.from(input.files || []);
  input.value = "";
  if (!picked.length) return;
  await uploadFiles(picked);
}

function onDragOver() {
  if (!props.readonly) dragOver.value = true;
}

function onDragLeave() {
  dragOver.value = false;
}

async function onDrop(event: DragEvent) {
  dragOver.value = false;
  if (props.readonly) return;
  const dropped = Array.from(event.dataTransfer?.files || []);
  if (!dropped.length) return;
  await uploadFiles(dropped);
}
</script>

<template>
  <section
    class="remote-tool-panel remote-files-panel"
    @dragover.prevent="onDragOver"
    @dragleave="onDragLeave"
    @drop.prevent="onDrop"
  >
    <header>
      <h3>文件</h3>
    </header>

    <RemoteFileIosAppSelector
      v-if="isIos"
      v-model="iosApp"
      :readonly="readonly"
    />

    <RemoteFileToolbar
      v-model:path-input="pathInput"
      :loading="loading"
      :uploading="uploading"
      :readonly="readonly"
      :platform="platform"
      :can-mutate="canMutate"
      @navigate="navigate"
      @refresh="refreshListing()"
      @mkdir="createFolder"
      @upload="triggerUploadPick"
      @home="goHome"
      @up="goUp"
    />

    <RemoteFileUploadBar
      :destination="uploadDestination"
      :progress="progress"
      :transfer-label="transferLabel"
      :phase="transferPhase"
      :readonly="readonly"
      :platform="platform"
      @cancel="files.cancelActiveUpload()"
    />

    <div class="remote-files-tree-host">
      <RemoteFileTreeList
        v-if="treeView === 'ios-eager'"
        variant="ios"
        :ios-nodes="treeNodes"
        :loading="loading"
        :readonly="readonly"
        :can-mutate="canMutate"
        @toggle="toggleTreeNode"
        @download="downloadTreeNode"
        @preview="openPreviewFromTree"
        @rename="renameTreeNode"
        @remove="removeTreeNode"
      />
      <RemoteFileTreeList
        v-else-if="treeView === 'android-lazy'"
        variant="android"
        :android-nodes="androidTreeNodes"
        :loading="loading"
        :readonly="readonly"
        :can-mutate="canMutate"
        @toggle="toggleTreeNode"
        @download="downloadTreeNode"
        @preview="openPreviewFromTree"
        @rename="renameTreeNode"
        @remove="removeTreeNode"
      />
    </div>

    <p
      v-if="listed && !loading && treeView && !(treeView === 'ios-eager' ? treeNodes.length : androidTreeNodes.length)"
      class="muted"
    >
      当前目录为空，可上传文件或切换路径。
    </p>

    <input ref="fileInput" type="file" multiple hidden @change="onPick" />

    <RemoteFileDropOverlay :visible="dragOver && !readonly" />

    <RemoteFilePreviewModal
      :open="previewOpen"
      :target="previewTarget"
      :fetch-preview-blob="fetchPreviewBlob"
      @close="closePreview"
      @download="(target) => files.download(target.path, target.name)"
    />

    <p v-if="error" class="bad">{{ error }}</p>
  </section>
</template>

<style scoped>
.remote-files-panel {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.remote-files-tree-host {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
</style>

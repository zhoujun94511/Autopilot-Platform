import { ref } from "vue";
import {
  sendRemoteCommand,
  sendRemoteCommandUntil,
} from "./useRemoteCommands";
import {
  parseIosFsyncTree,
  type IosFsyncTreeNode,
} from "./files/parseIosFsyncTree";
import {
  entriesToLazyTreeNodes,
  type AndroidLazyTreeNode,
} from "./files/androidLazyTree";
import {
  pullRemoteFileBlob,
  pullRemoteFileBlobRaw,
  statRemoteFileEntry,
} from "./remoteFilePull";
import {
  asUploadDirRemote,
  normalizeUploadDir,
} from "./files/remoteUploadPath";

export type RemoteFileEntry = {
  name: string;
  path: string;
  is_dir: boolean;
  is_link?: boolean;
  size: number;
  mtime?: number;
  mode?: number;
};

const CHUNK_SIZE = 32 * 1024;

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

function syncUploadPath(nextPath: string, uploadPath: { value: string }) {
  uploadPath.value = normalizeUploadDir(nextPath);
}

export type RemoteFilesTreeView = "ios-eager" | "android-lazy" | null;
export type RemoteUploadPhase = "idle" | "sending" | "writing";

export function useRemoteFiles() {
  const path = ref("/sdcard");
  const entries = ref<RemoteFileEntry[]>([]);
  const treeNodes = ref<IosFsyncTreeNode[]>([]);
  const androidTreeNodes = ref<AndroidLazyTreeNode[]>([]);
  const treeView = ref<RemoteFilesTreeView>(null);
  const listed = ref(false);
  const loading = ref(false);
  const progress = ref(0);
  const transferLabel = ref("");
  const transferPhase = ref<RemoteUploadPhase>("idle");
  const activeTransferId = ref<string | null>(null);
  const uploadPath = ref("");
  let transferGeneration = 0;
  const iosApp = ref("");
  const error = ref("");

  function resolveApp(explicit?: string): string {
    return explicit ?? iosApp.value;
  }

  async function list(nextPath = path.value, app = resolveApp()): Promise<void> {
    loading.value = true;
    error.value = "";
    try {
      const result = await sendRemoteCommand({
        t: "file.list",
        path: nextPath,
        app,
      });
      path.value = String(result.path || nextPath);
      syncUploadPath(path.value, uploadPath);

      if (Array.isArray(result.entries) && result.entries.length) {
        entries.value = result.entries as RemoteFileEntry[];
        treeNodes.value = [];
        androidTreeNodes.value = [];
        treeView.value = null;
      } else if (typeof result.tree === "string" && result.tree.trim()) {
        treeNodes.value = parseIosFsyncTree(result.tree, path.value);
        androidTreeNodes.value = [];
        entries.value = [];
        treeView.value = "ios-eager";
      } else {
        entries.value = [];
        treeNodes.value = [];
        androidTreeNodes.value = [];
        treeView.value = null;
      }
      listed.value = true;
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause);
    } finally {
      loading.value = false;
    }
  }

  async function listAndroidTree(nextPath = path.value): Promise<void> {
    loading.value = true;
    error.value = "";
    try {
      const result = await sendRemoteCommand({
        t: "file.list",
        path: nextPath,
      });
      path.value = String(result.path || nextPath);
      syncUploadPath(path.value, uploadPath);
      const items = Array.isArray(result.entries)
        ? (result.entries as RemoteFileEntry[])
        : [];
      androidTreeNodes.value = entriesToLazyTreeNodes(items);
      treeNodes.value = [];
      entries.value = [];
      treeView.value = "android-lazy";
      listed.value = true;
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause);
    } finally {
      loading.value = false;
    }
  }

  async function toggleAndroidTreeNode(node: AndroidLazyTreeNode): Promise<void> {
    if (!node.isDir) return;
    if (node.loaded) {
      node.expanded = !node.expanded;
      if (node.expanded) syncUploadPath(node.path, uploadPath);
      return;
    }
    node.loading = true;
    error.value = "";
    try {
      const result = await sendRemoteCommand({
        t: "file.list",
        path: node.path,
      });
      node.children = entriesToLazyTreeNodes(
        Array.isArray(result.entries)
          ? (result.entries as RemoteFileEntry[])
          : [],
      );
      node.loaded = true;
      node.expanded = true;
      syncUploadPath(node.path, uploadPath);
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause);
    } finally {
      node.loading = false;
    }
  }

  async function refreshCurrentView(): Promise<void> {
    if (treeView.value === "android-lazy") await listAndroidTree();
    else await list(path.value, resolveApp());
  }

  async function mkdir(nextPath: string, app = resolveApp()): Promise<void> {
    await sendRemoteCommand({ t: "file.mkdir", path: nextPath, app });
    await refreshCurrentView();
  }

  async function rename(src: string, dst: string, app = resolveApp()): Promise<void> {
    await sendRemoteCommand({ t: "file.rename", src, dst, app });
    await refreshCurrentView();
  }

  async function remove(target: string, recursive = false, app = resolveApp()): Promise<void> {
    await sendRemoteCommand({ t: "file.delete", path: target, recursive, app });
    await refreshCurrentView();
  }

  async function finishUpload(
    id: string,
    options?: { installApk?: boolean; forceInstall?: boolean },
  ): Promise<void> {
    const endResult = await sendRemoteCommandUntil(
      {
        t: "file.end",
        id,
        request_id: id,
        install: Boolean(options?.installApk),
        force: Boolean(options?.forceInstall),
      },
      (message) => message.t === "file.done" || message.t === "file.error",
      10 * 60_000,
    );
    if (endResult.t === "file.error") {
      const err = new Error(String(endResult.error || "文件传输失败")) as Error & {
        errorCode?: string;
        existingPackage?: string;
      };
      err.errorCode = String(endResult.error_code || "");
      err.existingPackage = String(endResult.existing_package || "");
      throw err;
    }
  }

  function resetTransfer(): void {
    activeTransferId.value = null;
    transferLabel.value = "";
    transferPhase.value = "idle";
    progress.value = 0;
  }

  async function upload(
    file: File,
    options?: {
      remote?: string;
      app?: string;
      installApk?: boolean;
      forceInstall?: boolean;
    },
  ): Promise<void> {
    const id = crypto.randomUUID();
    const generation = ++transferGeneration;
    activeTransferId.value = id;
    progress.value = 0;
    transferLabel.value = file.name;
    transferPhase.value = "sending";
    error.value = "";
    const remote = options?.remote ?? asUploadDirRemote(uploadPath.value, path.value);
    const app = resolveApp(options?.app);
    try {
      await sendRemoteCommandUntil(
        {
          t: "file.push",
          id,
          name: file.name,
          size: file.size,
          remote,
          app,
          request_id: id,
        },
        (message) => message.t === "file.ready",
      );
      if (generation !== transferGeneration) return;
      const buffer = new Uint8Array(await file.arrayBuffer());
      let sequence = 0;
      const total = Math.max(file.size, buffer.length);
      for (let offset = 0; offset < buffer.length; offset += CHUNK_SIZE) {
        if (generation !== transferGeneration) return;
        const chunk = buffer.subarray(offset, offset + CHUNK_SIZE);
        const expectedReceived = offset + chunk.length;
        await sendRemoteCommandUntil(
          {
            t: "file.chunk",
            id,
            seq: sequence,
            data: bytesToBase64(chunk),
            request_id: id,
          },
          (message) =>
            message.t === "file.progress" &&
            Number(message.received || 0) >= expectedReceived,
          30_000,
        );
        sequence += 1;
        progress.value = total
          ? Math.min(0.99, expectedReceived / total)
          : 0.99;
        await new Promise((resolve) => window.setTimeout(resolve, 0));
      }
      if (generation !== transferGeneration) return;
      transferPhase.value = "writing";
      progress.value = 0.99;
      await finishUpload(id, {
        installApk: options?.installApk,
        forceInstall: options?.forceInstall,
      });
      if (generation !== transferGeneration) return;
      progress.value = 1;
      await refreshCurrentView();
    } catch (cause) {
      if (generation !== transferGeneration) return;
      throw cause;
    } finally {
      if (generation === transferGeneration) resetTransfer();
    }
  }

  async function uploadToPath(
    file: File,
    remotePath: string,
    options?: { app?: string; installApk?: boolean; forceInstall?: boolean },
  ): Promise<void> {
    await upload(file, { remote: remotePath, ...options });
  }

  async function cancel(transferId: string): Promise<void> {
    await sendRemoteCommand({
      t: "file.cancel",
      id: transferId,
    });
  }

  async function cancelActiveUpload(): Promise<void> {
    const id = activeTransferId.value;
    if (!id) return;
    transferGeneration += 1;
    resetTransfer();
    try {
      await cancel(id);
    } catch {
      // 写入设备阶段 transfer 可能已从 runner 弹出，取消失败可忽略
    }
  }

  async function pullForPreview(
    remotePath: string,
    filename: string,
    options?: { size?: number; app?: string },
  ): Promise<Blob> {
    return pullRemoteFileBlob(remotePath, filename, {
      size: options?.size,
      app: resolveApp(options?.app),
    });
  }

  async function pullAsBlob(remotePath: string, app = resolveApp()): Promise<Blob> {
    return pullRemoteFileBlobRaw(remotePath, app);
  }

  async function statRemoteFile(path: string, app = resolveApp()): Promise<RemoteFileEntry | null> {
    return statRemoteFileEntry(path, app);
  }

  async function download(
    remotePath: string,
    filename: string,
    app = resolveApp(),
  ): Promise<void> {
    const blob = await pullAsBlob(remotePath, app);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return {
    path,
    entries,
    treeNodes,
    androidTreeNodes,
    treeView,
    listed,
    loading,
    progress,
    transferLabel,
    transferPhase,
    activeTransferId,
    uploadPath,
    iosApp,
    error,
    list,
    listAndroidTree,
    toggleAndroidTreeNode,
    refreshCurrentView,
    mkdir,
    rename,
    remove,
    upload,
    uploadToPath,
    cancel,
    cancelActiveUpload,
    statRemoteFile,
    pullForPreview,
    pullAsBlob,
    download,
  };
}

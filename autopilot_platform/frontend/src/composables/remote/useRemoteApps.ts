import { ref, watch } from "vue";
import {
  remoteStreamControlReady,
  sendRemoteCommand,
  sendRemoteCommandUntil,
  subscribeRemoteCommands,
} from "./useRemoteCommands";

export type RemoteApp = {
  package: string;
  bundle_id?: string;
  name?: string;
  version_name?: string;
  version_code?: number;
  system?: boolean;
  size?: number;
  export_supported?: boolean;
};

export type AppListScope = "all" | "third_party" | "system";

const CHUNK_SIZE = 32 * 1024;
const APP_LIST_TIMEOUT_MS = 90_000;
const CONTROL_READY_WAIT_MS = 120_000;

function base64(bytes: Uint8Array): string {
  let raw = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    raw += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(raw);
}

function filterByScope(items: RemoteApp[], scope: AppListScope): RemoteApp[] {
  if (scope === "system") return items.filter((app) => Boolean(app.system));
  if (scope === "third_party") return items.filter((app) => !app.system);
  return items;
}

function waitForStreamControl(maxMs = CONTROL_READY_WAIT_MS): Promise<boolean> {
  if (remoteStreamControlReady.value) return Promise.resolve(true);
  return new Promise((resolve) => {
    const stop = watch(
      remoteStreamControlReady,
      (ready) => {
        if (!ready) return;
        window.clearTimeout(timer);
        stop();
        resolve(true);
      },
      { immediate: true },
    );
    const timer = window.setTimeout(() => {
      stop();
      resolve(remoteStreamControlReady.value);
    }, maxMs);
  });
}

export function useRemoteApps(platform: string) {
  const apps = ref<RemoteApp[]>([]);
  const scope = ref<AppListScope>("third_party");
  const loading = ref(false);
  const progress = ref(0);
  const error = ref("");
  let listGeneration = 0;

  async function list(): Promise<void> {
    const generation = ++listGeneration;
    const requestedScope = scope.value;
    loading.value = true;
    error.value = "";
    apps.value = [];
    try {
      if (platform.toLowerCase() === "android") {
        const controlReady = await waitForStreamControl();
        if (generation !== listGeneration) return;
        if (!controlReady) {
          error.value = "等待视频流与控制通道就绪超时，请稍后再试";
          return;
        }
      }
      const result = await sendRemoteCommand(
        {
          t: "app.list",
          scope: requestedScope,
          system: requestedScope === "system",
        },
        APP_LIST_TIMEOUT_MS,
      );
      if (generation !== listGeneration) return;
      const raw = Array.isArray(result.packages)
        ? (result.packages as RemoteApp[])
        : [];
      apps.value = filterByScope(raw, requestedScope);
    } catch (cause) {
      if (generation !== listGeneration) return;
      error.value = cause instanceof Error ? cause.message : String(cause);
      apps.value = [];
    } finally {
      if (generation === listGeneration) loading.value = false;
    }
  }

  async function action(
    name: "app.launch" | "app.stop" | "app.uninstall",
    packageName: string,
  ): Promise<void> {
    await sendRemoteCommand({ t: name, package: packageName }, 120_000);
    if (name === "app.uninstall") await list();
  }

  async function install(file: File, force = false): Promise<void> {
    const id = crypto.randomUUID();
    const isIos = platform.toLowerCase() === "ios";
    const lower = file.name.toLowerCase();
    const installPackage =
      !isIos && (lower.endsWith(".apk") || lower.endsWith(".xapk"));
    const begin = isIos ? "app.install.begin" : "file.push";
    const chunk = isIos ? "app.install.chunk" : "file.chunk";
    const end = isIos ? "app.install.end" : "file.end";
    progress.value = 0;
    await sendRemoteCommandUntil(
      {
        t: begin,
        id,
        request_id: id,
        name: file.name,
        size: file.size,
      },
      (message) =>
        message.t === (isIos ? "app.install.ready" : "file.ready"),
    );
    const buffer = new Uint8Array(await file.arrayBuffer());
    let sequence = 0;
    for (let offset = 0; offset < buffer.length; offset += CHUNK_SIZE) {
      const piece = buffer.subarray(offset, offset + CHUNK_SIZE);
      const expectedReceived = offset + piece.length;
      await sendRemoteCommandUntil(
        {
          t: chunk,
          id,
          request_id: id,
          seq: sequence,
          data: base64(piece),
        },
        (message) =>
          message.t ===
            (isIos ? "app.install.progress" : "file.progress") &&
          Number(message.received || 0) >= expectedReceived,
        30_000,
      );
      sequence += 1;
      progress.value = Math.min(0.99, (offset + piece.length) / file.size);
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    }
    const endResult = await sendRemoteCommandUntil(
      {
        t: end,
        id,
        request_id: id,
        force,
        install: installPackage,
      },
      (message) =>
        message.t === (isIos ? "app.install.done" : "file.done") ||
        message.t === (isIos ? "app.install.error" : "file.error"),
      15 * 60_000,
    );
    if (endResult.t === "file.error") {
      const err = new Error(String(endResult.error || "安装失败")) as Error & {
        errorCode?: string;
        existingPackage?: string;
      };
      err.errorCode = String(endResult.error_code || "");
      err.existingPackage = String(endResult.existing_package || "");
      throw err;
    }
    progress.value = 1;
    await list();
  }

  async function exportPackage(app: RemoteApp): Promise<void> {
    if (platform.toLowerCase() === "ios") {
      throw new Error("iOS 平台不支持导出已安装 IPA");
    }
    const requestId = crypto.randomUUID();
    const chunks = new Map<number, string>();
    let filename = `${app.package}.apk`;
    const stop = subscribeRemoteCommands((message) => {
      if (String(message.request_id || "") !== requestId) return;
      if (message.t === "app.export.ready" && message.filename) {
        filename = String(message.filename);
      }
      if (message.t === "app.export.chunk") {
        chunks.set(Number(message.seq || 0), String(message.data || ""));
      }
    });
    try {
      await sendRemoteCommand(
        {
          t: "app.export",
          package: app.package,
          id: requestId,
          request_id: requestId,
        },
        10 * 60_000,
      );
      const parts = [...chunks.entries()]
        .sort(([left], [right]) => left - right)
        .map(([, encoded]) => {
          const raw = atob(encoded);
          return Uint8Array.from(raw, (char) => char.charCodeAt(0));
        });
      const url = URL.createObjectURL(new Blob(parts));
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } finally {
      stop();
    }
  }

  return {
    apps,
    scope,
    loading,
    progress,
    error,
    list,
    action,
    install,
    exportPackage,
  };
}

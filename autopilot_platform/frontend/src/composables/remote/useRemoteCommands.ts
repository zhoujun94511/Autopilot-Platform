import { ref, watch } from "vue";
import { remoteDialogState } from "../useRemoteSession";

export type RemoteCommandMessage = Record<string, unknown> & {
  t?: string;
  request_id?: string;
  name?: string;
};

/** 与后端 sessions._VIEWER_READONLY_COMMANDS 对齐。 */
export const VIEWER_READONLY_COMMANDS = new Set([
  "device.info",
  "file.list",
  "file.stat",
  "file.pull",
  "app.list",
  "clipboard.get",
  "stream.stats",
]);

function isViewerSession(): boolean {
  const state = remoteDialogState.value;
  if (!state) return false;
  if (state.session?.participant_role === "controller") return false;
  if (state.session?.participant_role === "viewer") return true;
  return state.mode === "viewer";
}

function assertViewerMaySend(command: RemoteCommandMessage): void {
  if (!isViewerSession()) return;
  const name = String(command.t || command.name || "").trim();
  if (!VIEWER_READONLY_COMMANDS.has(name)) {
    throw new Error("旁观模式为只读，无法执行该操作");
  }
}

type Sender = (message: RemoteCommandMessage) => boolean | Promise<boolean>;
type Listener = (message: RemoteCommandMessage) => void;

const listeners = new Set<Listener>();
let sender: Sender | null = null;

export const remoteCommandReady = ref(false);
/** 视频 + 控制通道就绪（与 RemoteDeviceDialog stageStreaming 对齐） */
export const remoteStreamControlReady = ref(false);

export function configureRemoteCommandSender(next: Sender | null): void {
  sender = next;
  remoteCommandReady.value = Boolean(next);
  if (!next) {
    remoteStreamControlReady.value = false;
  }
}

export function setRemoteStreamControlReady(ready: boolean): void {
  remoteStreamControlReady.value = ready;
}

export function waitForRemoteStreamControl(maxMs = 120_000): Promise<boolean> {
  if (remoteStreamControlReady.value) return Promise.resolve(true);
  return new Promise((resolve) => {
    let timer = 0;
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
    timer = window.setTimeout(() => {
      stop();
      resolve(remoteStreamControlReady.value);
    }, maxMs);
  });
}

export function emitRemoteCommandMessage(message: RemoteCommandMessage): void {
  for (const listener of listeners) listener(message);
}

export function subscribeRemoteCommands(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export async function dispatchRemoteCommand(
  command: RemoteCommandMessage,
): Promise<boolean> {
  if (!sender) return false;
  return Boolean(await sender(command));
}

export async function sendRemoteCommand(
  command: RemoteCommandMessage,
  timeoutMs = 15_000,
): Promise<RemoteCommandMessage> {
  return sendRemoteCommandUntil(
    command,
    (message) => {
      const type = String(message.t || "");
      return !(
        type.endsWith(".progress") ||
        type.endsWith(".ready") ||
        type.endsWith(".chunk")
      );
    },
    timeoutMs,
  );
}

export async function sendRemoteCommandUntil(
  command: RemoteCommandMessage,
  isTerminal: (message: RemoteCommandMessage) => boolean,
  timeoutMs = 15_000,
): Promise<RemoteCommandMessage> {
  assertViewerMaySend(command);
  if (!sender) throw new Error("远控可靠命令通道未就绪");
  const requestId = String(command.request_id || crypto.randomUUID());
  const outgoing = { ...command, request_id: requestId };
  return new Promise<RemoteCommandMessage>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      stop();
      reject(new Error(`远控命令超时：${String(command.t || "")}`));
    }, timeoutMs);
    const stop = subscribeRemoteCommands((message) => {
      if (String(message.request_id || "") !== requestId) return;
      const type = String(message.t || "");
      const isGenericError = type === "error";
      const isTypedError = type.endsWith(".error");
      // 通用 error 必须立刻结束等待：file.end 失败时 runner 回 t=error，
      // 若只认 file.done/file.error 会卡在 99% 直到超时。
      if (!isGenericError && !isTypedError && !isTerminal(message)) return;
      window.clearTimeout(timer);
      stop();
      if (isGenericError || (isTypedError && !isTerminal(message))) {
        reject(new Error(String(message.error || "远控命令失败")));
        return;
      }
      resolve(message);
    });
    void dispatchRemoteCommand(outgoing).then((accepted) => {
      if (!accepted) {
        window.clearTimeout(timer);
        stop();
        reject(new Error("远控命令通道发送失败"));
      }
    });
  });
}

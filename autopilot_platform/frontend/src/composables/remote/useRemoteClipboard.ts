import { computed, ref } from "vue";
import { remoteCommandReady } from "./useRemoteCommands";
import { sendRemoteCommand } from "./useRemoteCommands";

export type ClipboardAction =
  | "read-device"
  | "write-device"
  | "write-paste"
  | "read-browser"
  | "write-browser"
  | null;

function friendlyError(cause: unknown, fallback: string): string {
  if (cause instanceof Error) {
    if (cause.message.includes("远控可靠命令通道未就绪")) {
      return "可靠命令通道尚未就绪，请等待 WebRTC/WS 连接完成后再试";
    }
    if (cause.message.includes("远控命令超时")) {
      return `${cause.message}。若刚建立连接，请稍候重试；持续失败请查看「流质量」页`;
    }
    if (cause.name === "NotAllowedError") {
      return "浏览器拒绝访问剪贴板，请在地址栏允许剪贴板权限";
    }
    return cause.message;
  }
  return fallback;
}

export function useRemoteClipboard() {
  const text = ref("");
  const loading = ref(false);
  const error = ref("");
  const success = ref("");
  const activeAction = ref<ClipboardAction>(null);

  const charCount = computed(() => text.value.length);
  const commandReady = remoteCommandReady;

  function clearFeedback() {
    error.value = "";
    success.value = "";
  }

  async function readDevice(): Promise<string> {
    if (!remoteCommandReady.value) {
      error.value = "可靠命令通道尚未就绪，请等待连接完成";
      return "";
    }
    loading.value = true;
    activeAction.value = "read-device";
    clearFeedback();
    try {
      const result = await sendRemoteCommand({ t: "clipboard.get" });
      text.value = String(result.text || "");
      success.value = text.value
        ? `已从设备读取 ${text.value.length} 个字符`
        : "设备剪贴板为空";
      return text.value;
    } catch (cause) {
      error.value = friendlyError(cause, "读取设备剪贴板失败");
      return "";
    } finally {
      loading.value = false;
      activeAction.value = null;
    }
  }

  async function writeDevice(paste = false): Promise<boolean> {
    if (!remoteCommandReady.value) {
      error.value = "可靠命令通道尚未就绪，请等待连接完成";
      return false;
    }
    loading.value = true;
    activeAction.value = paste ? "write-paste" : "write-device";
    clearFeedback();
    try {
      await sendRemoteCommand({
        t: "clipboard.set",
        text: text.value,
        paste,
      });
      success.value = paste ? "已写入设备剪贴板并尝试粘贴" : "已写入设备剪贴板";
      return true;
    } catch (cause) {
      error.value = friendlyError(cause, "写入设备剪贴板失败");
      return false;
    } finally {
      loading.value = false;
      activeAction.value = null;
    }
  }

  async function readBrowser(): Promise<void> {
    loading.value = true;
    activeAction.value = "read-browser";
    clearFeedback();
    try {
      text.value = await navigator.clipboard.readText();
      success.value = text.value
        ? `已从本机剪贴板读取 ${text.value.length} 个字符`
        : "本机剪贴板为空";
    } catch (cause) {
      error.value = friendlyError(cause, "读取浏览器剪贴板失败");
    } finally {
      loading.value = false;
      activeAction.value = null;
    }
  }

  async function writeBrowser(): Promise<void> {
    loading.value = true;
    activeAction.value = "write-browser";
    clearFeedback();
    try {
      await navigator.clipboard.writeText(text.value);
      success.value = "已复制到本机剪贴板，可在电脑上 Ctrl+V";
    } catch (cause) {
      error.value = friendlyError(cause, "复制到浏览器剪贴板失败");
    } finally {
      loading.value = false;
      activeAction.value = null;
    }
  }

  return {
    text,
    loading,
    error,
    success,
    activeAction,
    charCount,
    commandReady,
    readDevice,
    writeDevice,
    readBrowser,
    writeBrowser,
  };
}

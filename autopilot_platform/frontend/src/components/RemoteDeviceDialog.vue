<script setup lang="ts">
/**
 * Platform Web 远控面板：Android WebRTC / iOS MJPEG + 触控。
 * DataChannel 对齐 WebAppFlaskscrcpy：Runner 创建 input，浏览器 ondatachannel 接收。
 */
import { computed, onBeforeUnmount, ref, watch } from "vue";
import ApModal from "./ApModal.vue";
import RemoteSideDrawer from "./remote/RemoteSideDrawer.vue";
import RemoteStage from "./remote/RemoteStage.vue";
import RemoteToolbar from "./remote/RemoteToolbar.vue";
import {
  closeRemoteSession,
  createRemoteSession,
  getRemoteSession,
  joinRemoteSession,
  pollMedia,
  pollSignaling,
  postMedia,
  postSignaling,
  prefersMjpeg,
  remoteDialogState,
  type RemoteSessionInfo,
} from "../composables/useRemoteSession";
import { loadPlatformBootstrap } from "../api/bootstrap";
import { displayName } from "../utils/deviceDisplay";
import { notify } from "../composables/useNotify";
import {
  connectRemoteTransport,
  type RemoteTransport,
} from "../composables/remote/useRemoteTransport";
import {
  configureRemoteCommandSender,
  dispatchRemoteCommand,
  emitRemoteCommandMessage,
  setRemoteStreamControlReady,
  VIEWER_READONLY_COMMANDS,
  type RemoteCommandMessage,
} from "../composables/remote/useRemoteCommands";
import { remoteStreamStats } from "../composables/remote/useRemoteStream";
import { toDataChannelEvent } from "../composables/remote/scrcpyInputProtocol";
import {
  jpegB64ToBytes,
  unpackBinaryFrame,
} from "../composables/remote/jpegBinaryFrame";
import {
  markRemoteCold,
  markRunnerConnectedOnce,
  resetRemoteColdTrace,
  summaryRemoteCold,
} from "../composables/remote/remoteColdTrace";
import { apiLeaveRemoteParticipant, apiPostRemoteCommand } from "../api/remote";
import { setOverlayBusy } from "../composables/mcPolling";

const RTC_CONFIG: RTCConfiguration = {
  iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
  bundlePolicy: "max-bundle",
  rtcpMuxPolicy: "require",
};

const statusText = ref("准备中…");
const errorText = ref("");
const stageEl = ref<InstanceType<typeof RemoteStage> | null>(null);
const connecting = ref(false);
const useMjpeg = ref(false);
const frameUrl = ref("");
const transportMode = ref("http");
/** 须为 ref：pc 为普通变量，computed 无法追踪 connectionState。 */
const webrtcConnected = ref(false);
const inputReady = ref(false);
const videoWidth = ref(1080);
const videoHeight = ref(1920);

let pc: RTCPeerConnection | null = null;
let inputChannel: RTCDataChannel | null = null;
let adbChannel: RTCDataChannel | null = null;
let pollTimer: number | null = null;
let offerRetryTimer: number | null = null;
let offerRetryCount = 0;
const MAX_OFFER_RETRIES = 5;
/** 首次 handle_offer 冷启动约 5–8s；12s 首重试避免抢跑。 */
const FIRST_OFFER_RETRY_MS = 12000;
const OFFER_RETRY_INTERVAL_MS = 4000;
let pcRenegotiating = false;
/** startWebRtc 进行中：避免 transport.onOpen 抢先 resend offer。 */
let webrtcBootstrapPending = false;
let pcRecoverTimer: number | null = null;
let inputRecoverTimer: number | null = null;
const INPUT_CHANNEL_RECOVERY_MS = 2500;
let statusTimer: number | null = null;
let statsTimer: number | null = null;
let transport: RemoteTransport | null = null;
let sessionId = "";
let lastStatsBytes = 0;
let lastStatsTs = 0;
let pendingMjpeg: { bytes: Uint8Array; mime: string } | null = null;
let mjpegPaintScheduled = false;
let mjpegConnectedHint = false;
/** 仅 HTTP 降级：move 节流，避免 iOS(MJPEG)/Android 兜底路径刷屏 POST。 */
let lastTouchMoveAt = 0;
const TOUCH_MOVE_INTERVAL_MS = 50;

/** 对齐 Flask：右侧抽屉默认收起，底栏「更多」切换。 */
const drawerOpen = ref(false);

const readonlySession = computed(
  () => remoteDialogState.value?.session?.participant_role === "viewer",
);

const stageStreaming = computed(() => {
  if (connecting.value) return false;
  if (useMjpeg.value) return Boolean(frameUrl.value);
  if (readonlySession.value) return webrtcConnected.value;
  // WebRTC：画面与控制通道分离就绪；未 open 前禁止触控，避免「能看不能点」。
  return webrtcConnected.value && inputReady.value;
});

watch(
  stageStreaming,
  (ready) => setRemoteStreamControlReady(ready),
  { immediate: true },
);

function webrtcStatusText(controlReady = inputReady.value): string {
  const viaWs = transportMode.value === "ws";
  if (readonlySession.value) {
    if (webrtcConnected.value || controlReady) {
      return viaWs ? "已连接 · WebSocket · 旁观中" : "已连接 · 旁观中";
    }
    return viaWs ? "已连接 · WebSocket" : "已连接 · HTTP";
  }
  if (controlReady) {
    return viaWs ? "已连接 · WebSocket · 控制就绪" : "已连接 · 控制就绪";
  }
  if (webrtcConnected.value) {
    return viaWs
      ? "画面已就绪，控制通道建立中… · WebSocket"
      : "画面已就绪，控制通道建立中…";
  }
  return viaWs ? "已连接 · WebSocket" : "已连接 · HTTP";
}

const title = computed(() => {
  const d = remoteDialogState.value?.device;
  const state = remoteDialogState.value;
  const role = state?.session?.participant_role;
  const prefix =
    role === "viewer" || (!state?.session && state?.mode === "viewer")
      ? "旁观"
      : "远程调试";
  return d ? `${prefix} · ${displayName(d)}` : prefix;
});

let sessionEnding = false;

function handleRemoteSessionEnded(reason: string) {
  if (sessionEnding) return;
  sessionEnding = true;
  statusText.value = reason;
  notify(reason, "warn");
  void onClose();
}

function ownParticipantId(): string {
  return String(remoteDialogState.value?.session?.participant_id || "").trim();
}

function isSignalingForThisPeer(msg: Record<string, unknown>): boolean {
  const mine = ownParticipantId();
  const pid = String(msg.participant_id || "").trim();
  if (!mine || !pid) return true;
  return pid === mine;
}

watch(
  () => Boolean(remoteDialogState.value),
  (open) => setOverlayBusy(open),
  { immediate: true },
);

watch(
  () => remoteDialogState.value,
  async (s) => {
    drawerOpen.value = false;
    await teardown();
    if (!s) return;
    sessionEnding = false;
    await loadPlatformBootstrap();
    connecting.value = true;
    errorText.value = "";
    statusText.value =
      s.mode === "viewer" ? "加入旁观会话…" : "创建远控会话…";
    try {
      resetRemoteColdTrace("pending");
      markRemoteCold("ui.api.create.begin");
      const tApi = performance.now();
      const session =
        s.mode === "viewer"
          ? await joinRemoteSession(s.device)
          : await createRemoteSession(s.device);
      resetRemoteColdTrace(session.id);
      markRemoteCold("ui.session.created", {
        platform: session.platform,
        api_ms: Math.round(performance.now() - tApi),
      });
      s.session = session;
      sessionId = session.id;
      useMjpeg.value = prefersMjpeg(session);
      startTransport(session);
      configureRemoteCommandSender(sendReliableCommand);
      startStatusWatch(session.id);
      if (useMjpeg.value) {
        statusText.value = "等待 Runner 准备 WDA/MJPEG…";
        await startMjpeg(session);
      } else {
        statusText.value = "等待 Runner 就绪并协商 WebRTC…";
        await startWebRtc(session);
      }
    } catch (e) {
      errorText.value = e instanceof Error ? e.message : String(e);
      statusText.value = "失败";
      notify(errorText.value, "error");
      if (s.mode === "viewer") {
        s.resolve();
        return;
      }
    } finally {
      connecting.value = false;
    }
  },
);

const STATUS_WATCH_CONNECTING_MS = 1_500;
const STATUS_WATCH_CONNECTED_MS = 10_000;

function applyParticipantRole(next: "controller" | "viewer") {
  const state = remoteDialogState.value;
  const current = state?.session;
  if (!current) return;
  const prev = current.participant_role;
  current.participant_role = next;
  if (prev === next || connecting.value) return;
  if (useMjpeg.value) {
    statusText.value = next === "viewer" ? "已连接 · 旁观中" : statusText.value;
    return;
  }
  void renegotiateWebRtc(current, true);
}

function startStatusWatch(sid: string) {
  if (statusTimer != null) window.clearInterval(statusTimer);
  let intervalMs = STATUS_WATCH_CONNECTING_MS;

  const tick = async () => {
    try {
      const info = await getRemoteSession(sid);
      const current = remoteDialogState.value?.session;
      if (current) {
        if (info.participant_id) current.participant_id = info.participant_id;
        current.viewer_count = info.viewer_count;
        applyParticipantRole(
          info.participant_role === "controller" ? "controller" : "viewer",
        );
      }
      if (
        info.status === "ready" &&
        (statusText.value === "等待 Runner 就绪并协商 WebRTC…" ||
          statusText.value === "创建远控会话…" ||
          statusText.value === "加入旁观会话…" ||
          statusText.value === "等待 Runner 准备 WDA/MJPEG…" ||
          statusText.value === "WebSocket 已连接，等待 WDA/MJPEG…" ||
          statusText.value === "WebSocket 已连接，协商 WebRTC…" ||
          statusText.value === "正在连接 WebSocket…")
      ) {
        markRemoteCold("ui.runner.ready");
        statusText.value = useMjpeg.value
          ? "Runner 已就绪，等待首帧…"
          : "Runner 已就绪，等待 WebRTC…";
      }
      if (info.status === "connected") {
        markRunnerConnectedOnce();
      }
      if (
        info.status === "connected" &&
        !useMjpeg.value &&
        webrtcConnected.value &&
        !inputReady.value &&
        !statusText.value.includes("重协商")
      ) {
        statusText.value = webrtcStatusText(false);
      }
      if (info.status === "failed") {
        statusText.value = "会话 failed";
        errorText.value = "远控会话失败，请关闭后重试";
      }
      if (info.status === "closed") {
        handleRemoteSessionEnded("远控会话已结束");
        return;
      }
      const next =
        info.status === "connected" || info.status === "failed"
          ? STATUS_WATCH_CONNECTED_MS
          : STATUS_WATCH_CONNECTING_MS;
      if (next !== intervalMs && statusTimer != null) {
        intervalMs = next;
        window.clearInterval(statusTimer);
        statusTimer = window.setInterval(() => void tick(), intervalMs);
      }
    } catch {
      /* ignore */
    }
  };

  statusTimer = window.setInterval(() => void tick(), intervalMs);
}

function startTransport(session: RemoteSessionInfo) {
  transport?.close();
  transport = connectRemoteTransport(session, {
    onMessage: handleTransportMessage,
    onState: (state) => {
      if (state === "connecting") {
        statusText.value = "正在连接 WebSocket…";
        syncFallbackPoll(session.id);
      } else if (state === "open") {
        transportMode.value = "ws";
        markRemoteCold("ui.transport.open", { mode: "ws" });
        statusText.value = useMjpeg.value
          ? "WebSocket 已连接，等待 WDA/MJPEG…"
          : "WebSocket 已连接，协商 WebRTC…";
        syncFallbackPoll(session.id);
        void drainSignaling(session.id);
        if (!useMjpeg.value) {
          void recoverWebRtcAfterTransport(session);
        }
      } else if (state === "fallback") {
        transportMode.value = "http";
        markRemoteCold("ui.transport.fallback", { mode: "http" });
        statusText.value = useMjpeg.value
          ? "WebSocket 不可用，HTTP 降级等待 MJPEG…"
          : "WebSocket 不可用，HTTP 降级…";
        syncFallbackPoll(session.id);
        void drainSignaling(session.id);
        if (!useMjpeg.value) {
          void recoverWebRtcAfterTransport(session);
        }
      }
    },
  });
  startFallbackPoll(session.id);
}

/** WS 恢复后：无远端 SDP、连接未就绪、或画面有了但 input DC 未开 → 重协商。 */
async function recoverWebRtcAfterTransport(session: RemoteSessionInfo) {
  if (useMjpeg.value) return;
  if (webrtcBootstrapPending) return;
  if (!pc) {
    await resendWebRtcOfferIfNeeded(session.id);
    return;
  }
  const st = pc.connectionState;
  if (st === "connected" && pc.remoteDescription) {
    if (remoteStreamStats.framesDecoded > 0 && inputReady.value) return;
    if (remoteStreamStats.framesDecoded > 0 && !inputReady.value) {
      statusText.value = "画面已就绪，正在建立控制通道…";
      scheduleInputChannelRecovery(session);
      return;
    }
    statusText.value = "连接已建立但无画面，正在重协商…";
    await renegotiateWebRtc(session);
    return;
  }
  if (st === "disconnected") {
    statusText.value = "连接波动，等待恢复…";
    schedulePcRecovery(session);
    return;
  }
  await renegotiateWebRtc(session);
}

function scheduleInputChannelRecovery(session: RemoteSessionInfo) {
  if (inputRecoverTimer != null) window.clearTimeout(inputRecoverTimer);
  inputRecoverTimer = window.setTimeout(() => {
    inputRecoverTimer = null;
    if (useMjpeg.value || !pc || pc.connectionState !== "connected") return;
    if (inputReady.value && inputChannel?.readyState === "open") return;
    statusText.value = "控制通道未就绪，正在重协商…";
    void renegotiateWebRtc(session);
  }, INPUT_CHANNEL_RECOVERY_MS);
}

function clearInputRecoverTimer() {
  if (inputRecoverTimer != null) {
    window.clearTimeout(inputRecoverTimer);
    inputRecoverTimer = null;
  }
}

function schedulePcRecovery(session: RemoteSessionInfo) {
  if (pcRecoverTimer != null) window.clearTimeout(pcRecoverTimer);
  pcRecoverTimer = window.setTimeout(() => {
    pcRecoverTimer = null;
    if (!pc || pc.connectionState === "connected") return;
    if (pc.connectionState === "disconnected") {
      void renegotiateWebRtc(session);
      return;
    }
    if (pc.connectionState === "failed") {
      void renegotiateWebRtc(session);
    }
  }, 2500);
}

function clearPcRecoveryTimer() {
  if (pcRecoverTimer != null) {
    window.clearTimeout(pcRecoverTimer);
    pcRecoverTimer = null;
  }
}

async function renegotiateWebRtc(session: RemoteSessionInfo, force = false) {
  if (useMjpeg.value || pcRenegotiating) return;
  if (
    !force &&
    inputReady.value &&
    webrtcConnected.value &&
    remoteStreamStats.framesDecoded > 0 &&
    pc?.remoteDescription
  ) {
    return;
  }
  pcRenegotiating = true;
  clearPcRecoveryTimer();
  clearInputRecoverTimer();
  stopOfferRetry();
  statusText.value = "正在重协商 WebRTC…";
  try {
    if (statsTimer != null) {
      window.clearInterval(statsTimer);
      statsTimer = null;
    }
    try {
      inputChannel?.close();
    } catch {
      /* ignore */
    }
    inputChannel = null;
    inputReady.value = false;
    try {
      adbChannel?.close();
    } catch {
      /* ignore */
    }
    adbChannel = null;
    try {
      pc?.close();
    } catch {
      /* ignore */
    }
    pc = null;
    stageEl.value?.clearMediaStream();
    await startWebRtc(session);
  } finally {
    pcRenegotiating = false;
  }
}

async function waitForRunnerReady(sid: string, timeoutMs = 65000): Promise<boolean> {
  const t0 = performance.now();
  while (performance.now() - t0 < timeoutMs) {
    try {
      const info = await getRemoteSession(sid);
      if (info.status === "ready" || info.status === "connected") {
        markRemoteCold("ui.runner.ready.wait", {
          waited_ms: Math.round(performance.now() - t0),
        });
        return true;
      }
      if (info.status === "failed") return false;
    } catch {
      /* ignore */
    }
    await new Promise((resolve) => window.setTimeout(resolve, 300));
  }
  return false;
}

async function resendWebRtcOfferIfNeeded(sid: string) {
  if (!pc || useMjpeg.value || pc.remoteDescription) return;
  const desc = pc.localDescription;
  if (!desc?.sdp) return;
  const offerBody = {
    type: "offer",
    sdp: desc.sdp,
    from_role: "browser",
    participant_id: ownParticipantId(),
    participant_role: readonlySession.value ? "viewer" : "controller",
  };
  if (!sendWsEnvelope("signaling", "offer", offerBody)) {
    await postSignaling(sid, "offer", offerBody).catch(() => undefined);
  }
  markRemoteCold("ui.offer.resend", { sdp_bytes: desc.sdp.length });
}

function stopOfferRetry() {
  if (offerRetryTimer != null) {
    window.clearTimeout(offerRetryTimer);
    offerRetryTimer = null;
  }
  offerRetryCount = 0;
}

function scheduleOfferRetry(sid: string, delayMs: number) {
  if (offerRetryTimer != null) {
    window.clearTimeout(offerRetryTimer);
  }
  offerRetryTimer = window.setTimeout(() => {
    offerRetryTimer = null;
    if (!pc || useMjpeg.value || pc.remoteDescription) {
      return;
    }
    if (offerRetryCount >= MAX_OFFER_RETRIES) {
      if (!pc.remoteDescription) {
        errorText.value = "WebRTC 协商超时，请关闭后重新打开远控";
        statusText.value = "协商失败";
      }
      return;
    }
    offerRetryCount += 1;
    void resendWebRtcOfferIfNeeded(sid);
    scheduleOfferRetry(sid, OFFER_RETRY_INTERVAL_MS);
  }, delayMs);
}

function startOfferRetry(sid: string) {
  stopOfferRetry();
  scheduleOfferRetry(sid, FIRST_OFFER_RETRY_MS);
}

function stopFallbackPoll() {
  if (pollTimer != null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

/** WS 在线时仍须 drain DB 信令队列，直至 answer 落地（Platform 重启后 answer 常先入队）。 */
function needsSignalingDrain(): boolean {
  if (useMjpeg.value || !pc) return false;
  if (!pc.remoteDescription) return true;
  const st = pc.connectionState;
  return st !== "connected" && st !== "closed";
}

/** WS 在线时不 poll；WebRTC 协商完成前仍 HTTP drain 信令；HTTP 模式全量 poll。 */
function syncFallbackPoll(sid: string) {
  stopFallbackPoll();
  const intervalMs = useMjpeg.value ? 200 : 400;
  pollTimer = window.setInterval(() => {
    if (useMjpeg.value) {
      if (transportMode.value !== "ws") void drainMedia(sid);
      return;
    }
    if (transportMode.value !== "ws" || needsSignalingDrain()) {
      void drainSignaling(sid);
    }
    if (transportMode.value !== "ws") void drainMedia(sid);
  }, intervalMs);
}

function startFallbackPoll(sid: string) {
  syncFallbackPoll(sid);
}

async function handleTransportMessage(message: Record<string, unknown>) {
  if (message.binary instanceof ArrayBuffer) {
    applyBinaryMjpegFrame(message.binary);
    return;
  }
  if (String(message.name || "") === "transport.ready") return;
  const channel = String(message.channel || "");
  const nested =
    message.payload && typeof message.payload === "object"
      ? (message.payload as Record<string, unknown>)
      : message;
  if (channel === "media") {
    await processMediaMessage(nested);
  } else if (channel === "command") {
    const command =
      nested.payload && typeof nested.payload === "object"
        ? (nested.payload as RemoteCommandMessage)
        : (nested as RemoteCommandMessage);
    emitRemoteCommandMessage(command);
  } else if (channel === "signaling" || message.type === "answer" || message.type === "ice") {
    const envPid = String(message.participant_id || "").trim();
    const msg =
      envPid && !String(nested.participant_id || "").trim()
        ? { ...nested, participant_id: envPid }
        : nested;
    await processSignalingMessage(msg);
  } else if (channel === "event") {
    const eventName = String(message.name || nested.name || nested.type || "");
    if (eventName === "session.closed") {
      handleRemoteSessionEnded("远控会话已结束");
    } else if (eventName === "participant.left") {
      const left = String(nested.participant_id || message.participant_id || "").trim();
      if (left && left === ownParticipantId()) {
        handleRemoteSessionEnded("已离开旁观");
      }
    } else if (eventName === "control.transferred") {
      const controllerId = String(
        nested.controller_participant_id || nested.participant_id || "",
      ).trim();
      applyParticipantRole(
        controllerId && controllerId === ownParticipantId() ? "controller" : "viewer",
      );
    }
  }
}

function sendWsEnvelope(
  channel: "signaling" | "media" | "command",
  name: string,
  payload: Record<string, unknown>,
): boolean {
  return Boolean(
    transport?.send({
      channel,
      type: channel === "command" ? "request" : "event",
      name,
      request_id: String(payload.request_id || ""),
      participant_id: remoteDialogState.value?.session?.participant_id || "",
      payload,
    }),
  );
}

async function startWebRtc(session: RemoteSessionInfo) {
  const sid = session.id;
  webrtcBootstrapPending = true;
  try {
  const iceServers = session.ice_servers.length
    ? session.ice_servers
    : RTC_CONFIG.iceServers;
  pc = new RTCPeerConnection({ ...RTC_CONFIG, iceServers });
  pc.addTransceiver("video", { direction: "recvonly" });
  // 对齐 WebAppFlaskscrcpy：浏览器只建 bootstrap；input 由 Runner 创建。
  const bootstrap = pc.createDataChannel("client-bootstrap", { ordered: true });
  bootstrap.addEventListener("open", () => {
    try {
      bootstrap.close();
    } catch {
      /* ignore */
    }
  });
  pc.ondatachannel = (ev) => {
    const ch = ev.channel;
    if (ch.label === "input") {
      inputChannel = ch;
      ch.addEventListener("open", () => {
        inputReady.value = true;
        clearInputRecoverTimer();
        errorText.value = "";
        markRemoteCold("ui.input_dc.open");
        if (pc?.connectionState === "connected") {
          statusText.value = webrtcStatusText(true);
          summaryRemoteCold("control_ready");
        }
      });
      ch.addEventListener("close", () => {
        if (inputChannel === ch) {
          inputChannel = null;
          inputReady.value = false;
        }
      });
    }
    if (ch.label === "adb") {
      adbChannel = ch;
      ch.addEventListener("message", (message) => {
        try {
          const parsed = JSON.parse(String(message.data || "{}"));
          if (parsed && typeof parsed === "object") {
            emitRemoteCommandMessage(parsed as RemoteCommandMessage);
          }
        } catch {
          /* ignore invalid adb payload */
        }
      });
    }
  };

  pc.ontrack = (ev) => {
    const stream = ev.streams[0] || new MediaStream([ev.track]);
    stageEl.value?.setMediaStream(stream);
    webrtcConnected.value = true;
    markRemoteCold("ui.ontrack", { framesDecoded: remoteStreamStats.framesDecoded });
    statusText.value = webrtcStatusText();
    const session = remoteDialogState.value?.session;
    if (session && !useMjpeg.value && !inputReady.value && !readonlySession.value) {
      scheduleInputChannelRecovery(session);
    }
  };

  pc.onicecandidate = (ev) => {
    if (!ev.candidate || !sid) return;
    const body = {
      type: "ice",
      candidate: ev.candidate.toJSON() as Record<string, unknown>,
      from_role: "browser",
      participant_id: ownParticipantId(),
    };
    if (!sendWsEnvelope("signaling", "ice", body)) {
      void postSignaling(sid, "ice", body).catch(() => undefined);
    }
  };

  pc.onconnectionstatechange = () => {
    const st = pc?.connectionState || "";
    const session = remoteDialogState.value?.session;
    webrtcConnected.value = st === "connected";
    if (st === "connected") {
      markRemoteCold("ui.pc.connected");
      statusText.value = webrtcStatusText();
      clearPcRecoveryTimer();
      stopOfferRetry();
    }
    if (st === "disconnected") {
      statusText.value = "连接波动，等待恢复…";
      if (session) schedulePcRecovery(session);
    }
    if (st === "failed") {
      statusText.value = "媒体连接失败，正在重协商…";
      if (session) void renegotiateWebRtc(session);
    }
  };
  statsTimer = window.setInterval(() => void collectWebRtcStats(), 2000);

  statusText.value = "等待 Runner 就绪…";
  const runnerReady = await waitForRunnerReady(sid);
  if (!runnerReady) {
    errorText.value = "Runner 未在时限内就绪，请关闭后重试";
    statusText.value = "Runner 未就绪";
    return;
  }

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  const offerBody = {
    type: "offer",
    sdp: offer.sdp || "",
    from_role: "browser",
    participant_id: ownParticipantId(),
    participant_role: readonlySession.value ? "viewer" : "controller",
  };
  if (!sendWsEnvelope("signaling", "offer", offerBody)) {
    await postSignaling(sid, "offer", offerBody);
  }
  markRemoteCold("ui.offer.sent", { sdp_bytes: (offer.sdp || "").length });
  startOfferRetry(sid);
  void drainSignaling(sid);
  } finally {
    webrtcBootstrapPending = false;
  }
}

async function collectWebRtcStats() {
  if (!pc) return;
  const report = await pc.getStats();
  const candidates = new Map<string, Record<string, unknown>>();
  let selectedPair: Record<string, unknown> | null = null;
  report.forEach((raw) => {
    const stat = raw as unknown as Record<string, unknown>;
    const type = String(stat.type || "");
    if (type === "local-candidate" || type === "remote-candidate") {
      candidates.set(String(stat.id || ""), stat);
    }
    if (
      type === "candidate-pair" &&
      (stat.selected === true ||
        (stat.nominated === true && String(stat.state || "") === "succeeded"))
    ) {
      selectedPair = stat;
    }
    if (type === "inbound-rtp" && String(stat.kind || stat.mediaType || "") === "video") {
      const now = Number(stat.timestamp || performance.now());
      const bytes = Number(stat.bytesReceived || 0);
      if (lastStatsTs > 0 && now > lastStatsTs && bytes >= lastStatsBytes) {
        remoteStreamStats.bitrateKbps =
          ((bytes - lastStatsBytes) * 8) / (now - lastStatsTs);
      }
      lastStatsBytes = bytes;
      lastStatsTs = now;
      remoteStreamStats.fps = Number(stat.framesPerSecond || 0);
      remoteStreamStats.framesDecoded = Number(stat.framesDecoded || 0);
      remoteStreamStats.framesDropped = Number(stat.framesDropped || 0);
      remoteStreamStats.packetsLost = Number(stat.packetsLost || 0);
    }
    if (type === "remote-inbound-rtp") {
      remoteStreamStats.rttMs = Number(stat.roundTripTime || 0) * 1000;
    }
  });
  if (selectedPair) {
    const pair = selectedPair as Record<string, unknown>;
    const local = candidates.get(String(pair.localCandidateId || ""));
    const remote = candidates.get(String(pair.remoteCandidateId || ""));
    remoteStreamStats.iceType = String(local?.candidateType || "");
    remoteStreamStats.candidatePair = [
      local?.candidateType,
      local?.protocol,
      remote?.candidateType,
    ]
      .filter(Boolean)
      .join(" / ");
    if (pair.currentRoundTripTime) {
      remoteStreamStats.rttMs = Number(pair.currentRoundTripTime) * 1000;
    }
  }
}

async function startMjpeg(session: RemoteSessionInfo) {
  startFallbackPoll(session.id);
}

async function processSignalingMessage(msg: Record<string, unknown>) {
  if (!pc) return;
  if (!isSignalingForThisPeer(msg)) return;
  const type = String(msg.type || msg.name || "");
  if (type === "answer" && msg.sdp) {
    if (pc.remoteDescription?.type === "answer") return;
    try {
      await pc.setRemoteDescription({
        type: "answer",
        sdp: String(msg.sdp),
      });
      markRemoteCold("ui.answer.received", { sdp_bytes: String(msg.sdp).length });
      stopOfferRetry();
      errorText.value = "";
      statusText.value = "已收到 Answer，等待媒体…";
    } catch (e) {
      errorText.value = e instanceof Error ? e.message : String(e);
    }
  } else if (type === "ice" && msg.candidate) {
    const cand = msg.candidate as RTCIceCandidateInit;
    if (cand.candidate) {
      await pc.addIceCandidate(cand).catch(() => undefined);
    }
  }
}

async function drainSignaling(sid: string) {
  if (!pc) return;
  try {
    const { messages, session_status } = await pollSignaling(sid);
    if (session_status === "failed" || session_status === "closed") {
      handleRemoteSessionEnded(
        session_status === "closed" ? "远控会话已结束" : `会话 ${session_status}`,
      );
      return;
    }
    for (const msg of messages) {
      await processSignalingMessage(msg);
    }
  } catch {
    /* poll 失败不打断会话 */
  }
}

function applyBinaryMjpegFrame(buf: ArrayBuffer) {
  const unpacked = unpackBinaryFrame(buf);
  if (!unpacked || unpacked.bytes.byteLength < 2) return;
  if (unpacked.width > 0) videoWidth.value = unpacked.width;
  if (unpacked.height > 0) videoHeight.value = unpacked.height;
  pendingMjpeg = { bytes: unpacked.bytes, mime: unpacked.mime };
  if (!mjpegPaintScheduled) {
    mjpegPaintScheduled = true;
    requestAnimationFrame(paintLatestMjpegFrame);
  }
}

function paintLatestMjpegFrame() {
  mjpegPaintScheduled = false;
  const pending = pendingMjpeg;
  pendingMjpeg = null;
  if (!pending) return;
  void stageEl.value?.applyMjpegFrame(pending.bytes, pending.mime).then((ok) => {
    if (!ok) return;
    frameUrl.value = "canvas";
    if (!mjpegConnectedHint) {
      mjpegConnectedHint = true;
      statusText.value = "已连接";
    }
  });
}

async function processMediaMessage(msg: Record<string, unknown>) {
  const type = String(msg.type || msg.name || "");
  const frame =
    type === "frame"
      ? msg
      : msg.payload && typeof msg.payload === "object"
        ? (msg.payload as Record<string, unknown>)
        : msg;
  if (type === "command_reply") {
    emitRemoteCommandMessage(frame as RemoteCommandMessage);
    return;
  }
  if (type !== "frame") return;
  const b64 = String(frame.data_b64 || "");
  if (!b64) return;
  const w = Number(frame.width || 0);
  const h = Number(frame.height || 0);
  if (w > 0) videoWidth.value = w;
  if (h > 0) videoHeight.value = h;
  pendingMjpeg = {
    bytes: jpegB64ToBytes(b64),
    mime: String(frame.mime || "image/jpeg"),
  };
  if (!mjpegPaintScheduled) {
    mjpegPaintScheduled = true;
    requestAnimationFrame(paintLatestMjpegFrame);
  }
}

function sendReliableCommand(message: RemoteCommandMessage): boolean | Promise<boolean> {
  if (readonlySession.value) {
    const name = String(message.t || message.name || "").trim();
    if (!VIEWER_READONLY_COMMANDS.has(name)) return false;
  }
  if (adbChannel?.readyState === "open") {
    adbChannel.send(JSON.stringify(message));
    return true;
  }
  if (sendWsEnvelope("command", String(message.t || "command"), message)) {
    return true;
  }
  if (!sessionId) return false;
  const requestId = String(message.request_id || crypto.randomUUID());
  const name = String(message.t || "command");
  const { t: _t, request_id: _r, ...payload } = message;
  return apiPostRemoteCommand(sessionId, name, payload, requestId)
    .then(() => true)
    .catch(() => false);
}

async function drainMedia(sid: string) {
  try {
    const { messages, session_status } = await pollMedia(sid);
    if (session_status === "failed" || session_status === "closed") {
      handleRemoteSessionEnded(
        session_status === "closed" ? "远控会话已结束" : `会话 ${session_status}`,
      );
      return;
    }
    for (const msg of messages) {
      await processMediaMessage(msg);
    }
  } catch {
    /* ignore */
  }
}

/**
 * 与 WebAppFlaskscrcpy useScrcpySession.emitTo 相同：触控/滚轮/按键走 input DataChannel。
 * Platform 仅在 DC 不可写时经 WS media 中继（非每帧 HTTP POST）。
 */
function emitTo(type: string, payload: Record<string, unknown> = {}): boolean {
  if (readonlySession.value) return false;
  const dcEvent = toDataChannelEvent(type, payload);
  if (!dcEvent) return false;
  if (
    !useMjpeg.value &&
    webrtcConnected.value &&
    inputReady.value &&
    inputChannel?.readyState === "open"
  ) {
    try {
      inputChannel.send(JSON.stringify(dcEvent));
      return true;
    } catch {
      /* fall through */
    }
  }
  return emitInputFallback(dcEvent);
}

/** Platform 兜底：WS media → 最后才 HTTP poll（WebApp 无此层，因无 Platform 中继）。 */
function emitInputFallback(payload: Record<string, unknown>): boolean {
  if (readonlySession.value) return false;
  if (!sessionId) return false;
  if (
    sendWsEnvelope("media", "input", {
      type: "input",
      from_role: "browser",
      payload,
    })
  ) {
    return true;
  }
  void postMedia(sessionId, {
    type: "input",
    from_role: "browser",
    payload,
  }).catch(() => undefined);
  return false;
}

function sendTouch(payload: { x: number; y: number; action: number }) {
  if (
    payload.action === 2 &&
    transportMode.value === "http" &&
    Date.now() - lastTouchMoveAt < TOUCH_MOVE_INTERVAL_MS
  ) {
    return;
  }
  if (payload.action === 2) lastTouchMoveAt = Date.now();
  emitTo("touch", payload);
}

function sendScroll(payload: { x: number; y: number; h: number; v: number }) {
  emitTo("scroll", payload);
}

/** 与 WebApp sendKey：down + up 各一条（DC 上无 HTTP 请求）。 */
function sendAndroidKey(code: number) {
  emitTo("key", { keycode: code, action: 0 });
  emitTo("key", { keycode: code, action: 1 });
}

async function sendIosHardwareButton(command: RemoteCommandMessage) {
  // 不等 ack：sendRemoteCommand 要等 button.ack，媒体通道对不上 request_id 会空等 12s，看起来像没点。
  try {
    const ok = await dispatchRemoteCommand({
      ...command,
      request_id: crypto.randomUUID(),
    });
    if (!ok) emitInputFallback(command);
  } catch {
    emitInputFallback(command);
  }
}

async function sendIosHome() {
  await sendIosHardwareButton({ t: "home" });
}

async function sendIosVolume(name: "volumeup" | "volumedown") {
  await sendIosHardwareButton({ t: "press_button", name });
}

function sendAndroidPower(mode: 0 | 2) {
  emitTo("set_power_mode", { mode });
}

function sendAndroidAction(
  action: "rotate" | "expandNotification" | "expandSettings" | "collapse",
) {
  const typeMap = {
    rotate: "rotate_device",
    expandNotification: "expand_notification",
    expandSettings: "expand_settings",
    collapse: "collapse_panels",
  } as const;
  emitTo(typeMap[action], {});
}

function sendAndroidSwipe(direction: "up" | "down" | "left" | "right") {
  const w = videoWidth.value > 0 ? videoWidth.value : 1080;
  const h = videoHeight.value > 0 ? videoHeight.value : 1920;
  const cx = w / 2;
  const cy = h / 2;
  const delta = Math.min(w, h) * 0.22;
  let sx = cx;
  let sy = cy;
  let ex = cx;
  let ey = cy;
  if (direction === "up") {
    sy = cy + delta;
    ey = cy - delta;
  } else if (direction === "down") {
    sy = cy - delta;
    ey = cy + delta;
  } else if (direction === "left") {
    sx = cx + delta;
    ex = cx - delta;
  } else {
    sx = cx - delta;
    ex = cx + delta;
  }
  emitTo("swipe", {
    start: [sx, sy],
    end: [ex, ey],
    duration: 200,
  });
}

function sendIosSwipe(direction: "up" | "down" | "left" | "right") {
  // 与 WebAppFlaskauto-iOS DeviceStage.dir 相同：1000×1000 归一化盒，后端按比例映射。
  const box = 1000;
  const c = 500;
  const near = 320;
  const far = 680;
  const map = {
    up: { startX: c, startY: far, endX: c, endY: near },
    down: { startX: c, startY: near, endX: c, endY: far },
    left: { startX: far, startY: c, endX: near, endY: c },
    right: { startX: near, startY: c, endX: far, endY: c },
  } as const;
  const s = map[direction];
  emitInputFallback({
    t: "swipe",
    ...s,
    display_width: box,
    display_height: box,
    duration: 180,
  });
}

async function teardown() {
  configureRemoteCommandSender(null);
  transport?.close();
  transport = null;
  stopOfferRetry();
  clearPcRecoveryTimer();
  clearInputRecoverTimer();
  pcRenegotiating = false;
  stopFallbackPoll();
  lastTouchMoveAt = 0;
  if (statusTimer != null) {
    window.clearInterval(statusTimer);
    statusTimer = null;
  }
  if (statsTimer != null) {
    window.clearInterval(statsTimer);
    statsTimer = null;
  }
  try {
    inputChannel?.close();
  } catch {
    /* ignore */
  }
  inputChannel = null;
  try {
    adbChannel?.close();
  } catch {
    /* ignore */
  }
  adbChannel = null;
  try {
    pc?.close();
  } catch {
    /* ignore */
  }
  pc = null;
  webrtcConnected.value = false;
  inputReady.value = false;
  stageEl.value?.clearMediaStream();
  stageEl.value?.clearMjpegFrame();
  frameUrl.value = "";
  useMjpeg.value = false;
  pendingMjpeg = null;
  mjpegPaintScheduled = false;
  mjpegConnectedHint = false;
  if (sessionId) {
    const sid = sessionId;
    sessionId = "";
    try {
      const session = remoteDialogState.value?.session;
      if (session?.participant_role === "viewer") {
        if (session?.participant_id) {
          await apiLeaveRemoteParticipant(sid, session.participant_id);
        }
      } else {
        await closeRemoteSession(sid);
      }
    } catch {
      /* ignore */
    }
  }
}

async function onClose() {
  sessionEnding = true;
  await teardown();
  remoteDialogState.value?.resolve();
}

onBeforeUnmount(() => {
  void teardown();
});

function onDimensions(width: number, height: number) {
  if (width > 0) videoWidth.value = width;
  if (height > 0) videoHeight.value = height;
}
</script>

<template>
  <ApModal
    v-if="remoteDialogState"
    xwide
    :title="title"
    :close-on-backdrop="false"
    @close="onClose"
  >
    <div class="remote-head">
      <p class="remote-status" :class="{ ok: statusText.includes('已连接') }">{{ statusText }}</p>
      <p v-if="errorText" class="ap-field-error" role="alert">{{ errorText }}</p>
    </div>
    <div class="remote-workbench" :class="{ 'with-drawer': drawerOpen }">
      <main class="remote-main">
        <RemoteStage
          ref="stageEl"
          :use-mjpeg="useMjpeg"
          :frame-url="frameUrl"
          :connecting="connecting"
          :platform="remoteDialogState.session?.platform || 'android'"
          :readonly="readonlySession"
          :streaming="stageStreaming"
          :resolution-width="videoWidth"
          :resolution-height="videoHeight"
          @dimensions="onDimensions"
          @touch="sendTouch"
          @scroll="sendScroll"
        />
        <RemoteToolbar
          :platform="remoteDialogState.session?.platform || ''"
          :readonly="readonlySession"
          :drawer-open="drawerOpen"
          @android-key="sendAndroidKey"
          @android-action="sendAndroidAction"
          @android-swipe="sendAndroidSwipe"
          @ios-home="sendIosHome"
          @ios-volume="sendIosVolume"
          @ios-swipe="sendIosSwipe"
          @toggle-drawer="drawerOpen = !drawerOpen"
        />
      </main>
      <template v-if="remoteDialogState.session">
        <RemoteSideDrawer
          v-show="drawerOpen"
          :platform="remoteDialogState.session.platform"
          :readonly="readonlySession"
          :status="statusText"
          :error="errorText"
          :transport-mode="transportMode"
          @close="drawerOpen = false"
          @android-key="sendAndroidKey"
          @android-power="sendAndroidPower"
          @android-action="sendAndroidAction"
        />
      </template>
    </div>
    <template #actions>
      <button type="button" class="ap-btn ghost" @click="onClose">关闭</button>
    </template>
  </ApModal>
</template>

<style scoped>
.remote-head {
  display: grid;
  gap: 0.35rem;
  margin-bottom: 0.75rem;
  flex-shrink: 0;
}

.remote-status {
  margin: 0;
  font-size: 0.88rem;
  color: var(--muted);
}

.remote-status.ok {
  color: var(--ok-soft-fg, var(--ok));
}

.remote-workbench {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 1rem;
  flex: 1;
  min-height: min(68vh, 720px);
  align-items: stretch;
}

.remote-workbench.with-drawer {
  grid-template-columns: minmax(0, 1fr) minmax(300px, 360px);
}

.remote-main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  min-height: 0;
}

@media (max-width: 900px) {
  .remote-workbench {
    grid-template-columns: 1fr;
    min-height: auto;
  }
}

@media (max-width: 640px) {
  .remote-workbench {
    min-height: calc(100dvh - 11rem);
  }

  :deep(.remote-drawer) {
    border-radius: 14px 14px 0 0;
    max-height: 44vh;
  }
}
</style>

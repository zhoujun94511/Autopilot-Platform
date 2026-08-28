import type { RemoteEnvelope } from "../../api/remote";
import { remoteWebSocketUrl } from "../../api/bootstrap";
import type { RemoteSessionInfo } from "../useRemoteSession";

export type RemoteTransportHandlers = {
  onMessage: (message: Record<string, unknown>) => void | Promise<void>;
  onState?: (state: "connecting" | "open" | "fallback" | "closed") => void;
};

export type RemoteTransport = {
  mode: "ws" | "http";
  send: (message: RemoteEnvelope) => boolean;
  close: () => void;
};

/** 首帧 auth 后仍无 transport.ready 才标记 fallback（不断开 CONNECTING）。 */
const WS_READY_TIMEOUT_MS = 8000;
const WS_RECONNECT_BASE_MS = 500;
const WS_RECONNECT_MAX_MS = 8000;

/**
 * WS 优先，断线自动重连（对齐 WebAppFlaskscrcpy：信令恢复后由上层重发 offer）。
 * Browser 鉴权走首帧 ``{type:"auth", access_token}``。
 */
export function connectRemoteTransport(
  session: RemoteSessionInfo,
  handlers: RemoteTransportHandlers,
): RemoteTransport {
  let socket: WebSocket | null = null;
  let mode: "ws" | "http" = "http";
  let closedByClient = false;
  let ready = false;
  let readyTimer: number | null = null;
  let reconnectTimer: number | null = null;
  let reconnectAttempt = 0;
  let fellBack = false;

  const params = new URLSearchParams({ role: "browser" });
  if (session.participant_id) {
    params.set("participant_id", session.participant_id);
  }
  params.set(
    "connection_id",
    session.participant_id
      ? `browser-${session.participant_id}`
      : `browser-${session.id}`,
  );

  function clearReadyTimer() {
    if (readyTimer != null) window.clearTimeout(readyTimer);
    readyTimer = null;
  }

  function clearReconnectTimer() {
    if (reconnectTimer != null) window.clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  function markFallback(reason: "timeout" | "error" | "close") {
    if (fellBack && mode === "http") return;
    if (reason === "timeout" && socket?.readyState === WebSocket.OPEN && !ready) {
      socket.close(4000, "auth timeout");
    }
    mode = "http";
    fellBack = true;
    handlers.onState?.("fallback");
  }

  function bindSocket(sock: WebSocket) {
    clearReadyTimer();
    readyTimer = window.setTimeout(() => {
      if (!ready) markFallback("timeout");
    }, WS_READY_TIMEOUT_MS);

    sock.addEventListener("open", () => {
      sock.binaryType = "arraybuffer";
      sock.send(
        JSON.stringify({
          type: "auth",
          access_token: session.access_token,
        }),
      );
    });
    sock.addEventListener("message", (event) => {
      if (event.data instanceof ArrayBuffer) {
        void handlers.onMessage({
          channel: "media",
          name: "frame",
          binary: event.data,
        });
        return;
      }
      if (typeof Blob !== "undefined" && event.data instanceof Blob) {
        void event.data.arrayBuffer().then((buf) => {
          void handlers.onMessage({
            channel: "media",
            name: "frame",
            binary: buf,
          });
        });
        return;
      }
      try {
        const parsed = JSON.parse(String(event.data || "{}"));
        if (!parsed || typeof parsed !== "object") return;
        const message = parsed as Record<string, unknown>;
        if (!ready && message.name === "transport.ready") {
          ready = true;
          mode = "ws";
          fellBack = false;
          reconnectAttempt = 0;
          clearReadyTimer();
          handlers.onState?.("open");
        }
        void handlers.onMessage(message);
      } catch {
        /* ignore non-json */
      }
    });
    sock.addEventListener("close", () => {
      mode = "http";
      ready = false;
      socket = null;
      clearReadyTimer();
      if (!closedByClient) {
        markFallback("close");
        scheduleReconnect();
      }
    });
    sock.addEventListener("error", () => {
      markFallback("error");
    });
  }

  function scheduleReconnect() {
    if (closedByClient || reconnectTimer != null) return;
    const delay = Math.min(
      WS_RECONNECT_BASE_MS * 2 ** reconnectAttempt,
      WS_RECONNECT_MAX_MS,
    );
    reconnectAttempt += 1;
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      if (closedByClient) return;
      handlers.onState?.("connecting");
      connectOnce();
    }, delay);
  }

  function connectOnce() {
    if (closedByClient) return;
    try {
      socket = new WebSocket(
        remoteWebSocketUrl(session.transport.websocket_path, params),
      );
      socket.binaryType = "arraybuffer";
      bindSocket(socket);
    } catch {
      markFallback("error");
      scheduleReconnect();
    }
  }

  const transport: RemoteTransport = {
    get mode() {
      return mode;
    },
    send(message) {
      if (!socket || socket.readyState !== WebSocket.OPEN || !ready) return false;
      socket.send(JSON.stringify(message));
      return true;
    },
    close() {
      closedByClient = true;
      clearReadyTimer();
      clearReconnectTimer();
      socket?.close(1000, "client close");
      socket = null;
      ready = false;
      mode = "http";
      handlers.onState?.("closed");
    },
  };

  if (
    session.transport.signaling !== "ws" ||
    !session.transport.websocket_path ||
    !session.access_token
  ) {
    handlers.onState?.("fallback");
    return transport;
  }

  handlers.onState?.("connecting");
  connectOnce();
  return transport;
}

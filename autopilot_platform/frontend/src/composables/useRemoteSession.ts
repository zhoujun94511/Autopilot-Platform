/**
 * Platform Web 远控：会话创建 + HTTP 信令/媒体中继（WebRTC 或 MJPEG）。
 */
import { shallowRef } from "vue";
import type { Device } from "../api";
import {
  apiCloseRemoteSession,
  apiCreateRemoteSession,
  apiGetRemoteSession,
  apiJoinDeviceRemoteSession,
  apiPollRemoteMedia,
  apiPollRemoteSignaling,
  apiPostRemoteMedia,
  apiPostRemoteSignaling,
  type RemoteIceServer,
  type RemoteSessionApiOut,
  type RemoteTransportInfo,
} from "../api/remote";
import { displayName } from "../utils/deviceDisplay";

export type RemoteSessionInfo = {
  id: string;
  device_id: string;
  runner_id: string;
  udid: string;
  platform: string;
  status: string;
  capabilities: string[];
  access_token: string;
  signaling_base_path: string;
  participant_id: string;
  participant_role: "controller" | "viewer";
  viewer_count: number;
  max_viewers: number;
  ice_servers: RemoteIceServer[];
  transport: RemoteTransportInfo;
  deviceLabel: string;
};

type RemoteDialogState = {
  device: Device;
  session: RemoteSessionInfo | null;
  mode: "controller" | "viewer";
  resolve: () => void;
};

export const remoteDialogState = shallowRef<RemoteDialogState | null>(null);

function isMobileRemotePlatform(device: Device): boolean {
  const platform = String(device.platform || "").toLowerCase();
  return platform === "android" || platform === "ios";
}

export type RemoteGateUser = {
  id?: string | null;
  username?: string | null;
};

function actorId(actor?: string | RemoteGateUser | null): string {
  if (actor && typeof actor === "object") return String(actor.id || "").trim();
  return "";
}

function actorName(actor?: string | RemoteGateUser | null): string {
  if (typeof actor === "string") return actor.trim();
  if (actor && typeof actor === "object") return String(actor.username || "").trim();
  return "";
}

/** 优先用 user_id，避免重名；无 id 时回退 username。 */
export function isReservationOccupier(
  device: Device,
  actor?: string | RemoteGateUser | null,
): boolean {
  const uid = actorId(actor);
  const ownerId = String(device.reservation_user_id || "").trim();
  if (uid && ownerId) return uid === ownerId;
  const name = actorName(actor);
  const ownerName = String(device.reservation_username || "").trim();
  return Boolean(name && ownerName && name === ownerName);
}

/** 仅占用人开控制台。管理员能释放占用，不等于能当 controller。 */
export function canOpenRemote(
  device: Device,
  actor?: string | RemoteGateUser | null,
): boolean {
  if (device.busy_kind !== "reservation") return false;
  if (!isMobileRemotePlatform(device)) return false;
  return isReservationOccupier(device, actor);
}

/** 组织/平台管理员只读旁观：须已有进行中远控，且不是自己占用。 */
export function canObserveRemote(
  device: Device,
  actor?: string | RemoteGateUser | null,
): boolean {
  if (!device.can_manage) return false;
  if (device.busy_kind !== "reservation") return false;
  if (!isMobileRemotePlatform(device)) return false;
  if (!device.remote_session_active) return false;
  if (isReservationOccupier(device, actor)) return false;
  return true;
}

export function prefersMjpeg(session: RemoteSessionInfo | null | undefined): boolean {
  const caps = session?.capabilities || [];
  if (caps.includes("webrtc")) return false;
  return caps.includes("mjpeg") || String(session?.platform || "").toLowerCase() === "ios";
}

export async function createRemoteSession(
  device: Device,
): Promise<RemoteSessionInfo> {
  if (!device.id) throw new Error("设备缺少 id");
  const out = await apiCreateRemoteSession(device.id);
  return normalizeSession(out, device);
}

export async function joinRemoteSession(device: Device): Promise<RemoteSessionInfo> {
  if (!device.id) throw new Error("设备缺少 id");
  return normalizeSession(await apiJoinDeviceRemoteSession(device.id), device);
}

function normalizeSession(
  out: RemoteSessionApiOut,
  device?: Device,
): RemoteSessionInfo {
  const fallbackTransport: RemoteTransportInfo = {
    signaling: "http",
    media: "http",
    command: "http",
    websocket_path: "",
  };
  return {
    id: String(out.id),
    device_id: String(out.device_id),
    runner_id: String(out.runner_id),
    udid: String(out.udid || device?.udid || ""),
    platform: String(out.platform || device?.platform || ""),
    status: String(out.status || "pending"),
    capabilities: Array.isArray(out.capabilities) ? out.capabilities : [],
    access_token: String(out.access_token || ""),
    signaling_base_path: String(
      out.signaling_base_path || `/api/v1/device-remote-sessions/${out.id}`,
    ),
    participant_id: String(out.participant_id || ""),
    // 缺省/未知角色当 viewer，避免 status 轮询把旁观抬成可触控
    participant_role: out.participant_role === "controller" ? "controller" : "viewer",
    viewer_count: Number(out.viewer_count || 0),
    max_viewers: Number(out.max_viewers ?? 5),
    ice_servers: Array.isArray(out.ice_servers) ? out.ice_servers : [],
    transport: {
      ...fallbackTransport,
      ...(out.transport || {}),
    },
    deviceLabel: device ? displayName(device) : "",
  };
}

export async function closeRemoteSession(sessionId: string): Promise<void> {
  await apiCloseRemoteSession(sessionId);
}

export async function getRemoteSession(
  sessionId: string,
): Promise<RemoteSessionInfo> {
  return normalizeSession(await apiGetRemoteSession(sessionId));
}

export async function postSignaling(
  sessionId: string,
  kind: "offer" | "answer" | "ice",
  body: {
    type: string;
    sdp?: string;
    candidate?: Record<string, unknown>;
    from_role?: string;
  },
): Promise<void> {
  await apiPostRemoteSignaling(sessionId, kind, body);
}

export async function pollSignaling(sessionId: string): Promise<{
  messages: Array<Record<string, unknown>>;
  session_status: string;
}> {
  const out = await apiPollRemoteSignaling(sessionId);
  return {
    messages: Array.isArray(out.messages) ? out.messages : [],
    session_status: String(out.session_status || ""),
  };
}

export async function postMedia(
  sessionId: string,
  body: {
    type: "frame" | "input" | "command" | "command_reply";
    from_role?: string;
    payload?: Record<string, unknown>;
    mime?: string;
    data_b64?: string;
    width?: number;
    height?: number;
    ts?: number;
  },
): Promise<void> {
  await apiPostRemoteMedia(sessionId, body);
}

export async function pollMedia(sessionId: string): Promise<{
  messages: Array<Record<string, unknown>>;
  session_status: string;
}> {
  const out = await apiPollRemoteMedia(sessionId);
  return {
    messages: Array.isArray(out.messages) ? out.messages : [],
    session_status: String(out.session_status || ""),
  };
}

/** 打开远控面板（异步；关闭后 resolve） */
export function openRemoteDialog(device: Device): Promise<void> {
  return new Promise((resolve) => {
    remoteDialogState.value = {
      device,
      session: null,
      mode: "controller",
      resolve: () => {
        remoteDialogState.value = null;
        resolve();
      },
    };
  });
}

/** 以只读 viewer 身份加入设备当前主会话。 */
export function openRemoteViewerDialog(device: Device): Promise<void> {
  return new Promise((resolve) => {
    remoteDialogState.value = {
      device,
      session: null,
      mode: "viewer",
      resolve: () => {
        remoteDialogState.value = null;
        resolve();
      },
    };
  });
}

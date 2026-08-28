/** Platform Web 远控 REST 契约；WebSocket 不可用时这些接口是完整降级路径。 */
import { api } from "../api";

export type RemoteIceServer = {
  urls: string[];
  username?: string;
  credential?: string;
};

export type RemoteTransportInfo = {
  signaling: "ws" | "http";
  media: "ws" | "http";
  command: "ws" | "http";
  websocket_path: string;
};

export type RemoteSessionApiOut = {
  id: string;
  device_id: string;
  runner_id: string;
  udid?: string;
  platform?: string;
  status?: string;
  capabilities?: string[];
  access_token?: string;
  signaling_base_path?: string;
  participant_id?: string;
  participant_role?: "controller" | "viewer";
  viewer_count?: number;
  max_viewers?: number;
  ice_servers?: RemoteIceServer[];
  transport?: Partial<RemoteTransportInfo>;
  error_message?: string;
};

export type RemotePollOut = {
  messages?: Array<Record<string, unknown>>;
  session_status?: string;
};

export type RemoteEnvelope = {
  channel: "signaling" | "media" | "command" | "event";
  type: "request" | "result" | "progress" | "error" | "event" | "ping" | "pong";
  name?: string;
  request_id?: string;
  participant_id?: string;
  payload?: Record<string, unknown>;
  progress?: number | null;
  error_code?: string;
  error_message?: string;
};

export type RemoteParticipant = {
  id: string;
  session_id: string;
  user_id: string;
  username: string;
  role: "controller" | "viewer";
  connection_id: string;
  status: string;
  joined_at: string;
  last_seen_at: string;
  left_at?: string | null;
};

export async function apiCreateRemoteSession(
  deviceId: string,
  durationMinutes = 60,
  maxViewers = 5,
): Promise<RemoteSessionApiOut> {
  return api(`/api/v1/devices/${encodeURIComponent(deviceId)}/remote-sessions`, {
    method: "POST",
    body: JSON.stringify({
      duration_minutes: durationMinutes,
      max_viewers: maxViewers,
    }),
  });
}

export function apiGetRemoteSession(sessionId: string): Promise<RemoteSessionApiOut> {
  return api(`/api/v1/device-remote-sessions/${encodeURIComponent(sessionId)}`);
}

export function apiJoinDeviceRemoteSession(
  deviceId: string,
  connectionId = crypto.randomUUID(),
): Promise<RemoteSessionApiOut> {
  return api(
    `/api/v1/devices/${encodeURIComponent(deviceId)}/remote-sessions/join`,
    {
      method: "POST",
      body: JSON.stringify({ role: "viewer", connection_id: connectionId }),
    },
  );
}

export function apiListRemoteParticipants(
  sessionId: string,
): Promise<RemoteParticipant[]> {
  return api(
    `/api/v1/device-remote-sessions/${encodeURIComponent(sessionId)}/participants`,
  );
}

export async function apiLeaveRemoteParticipant(
  sessionId: string,
  participantId: string,
): Promise<void> {
  await api(
    `/api/v1/device-remote-sessions/${encodeURIComponent(sessionId)}/participants/${encodeURIComponent(participantId)}`,
    { method: "DELETE" },
  );
}

export async function apiPromoteRemoteParticipant(
  sessionId: string,
  participantId: string,
): Promise<RemoteParticipant> {
  return api(
    `/api/v1/device-remote-sessions/${encodeURIComponent(sessionId)}/participants/${encodeURIComponent(participantId)}/promote`,
    { method: "POST" },
  );
}

export async function apiCloseRemoteSession(sessionId: string): Promise<void> {
  await api(`/api/v1/device-remote-sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
}

export async function apiPostRemoteSignaling(
  sessionId: string,
  kind: "offer" | "answer" | "ice",
  body: {
    type: string;
    sdp?: string;
    candidate?: Record<string, unknown>;
    from_role?: string;
    participant_id?: string;
  },
): Promise<void> {
  const base = `/api/v1/device-remote-sessions/${encodeURIComponent(sessionId)}`;
  const path =
    kind === "offer"
      ? `${base}/offer`
      : kind === "answer"
        ? `${base}/answer`
        : `${base}/ice`;
  await api(path, {
    method: "POST",
    body: JSON.stringify({
      type: body.type || kind,
      sdp: body.sdp || "",
      candidate: body.candidate || {},
      from_role: body.from_role || "browser",
      participant_id: body.participant_id || "",
    }),
  });
}

export function apiPollRemoteSignaling(sessionId: string): Promise<RemotePollOut> {
  return api(
    `/api/v1/device-remote-sessions/${encodeURIComponent(sessionId)}/signaling-poll`,
  );
}

export async function apiPostRemoteMedia(
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
  await api(`/api/v1/device-remote-sessions/${encodeURIComponent(sessionId)}/media`, {
    method: "POST",
    body: JSON.stringify({
      type: body.type,
      from_role: body.from_role || "browser",
      payload: body.payload || {},
      mime: body.mime || "image/jpeg",
      data_b64: body.data_b64 || "",
      width: body.width || 0,
      height: body.height || 0,
      ts: body.ts || Date.now() / 1000,
    }),
  });
}

export function apiPollRemoteMedia(sessionId: string): Promise<RemotePollOut> {
  return api(`/api/v1/device-remote-sessions/${encodeURIComponent(sessionId)}/media-poll`);
}

export async function apiPostRemoteCommand(
  sessionId: string,
  name: string,
  payload: Record<string, unknown> = {},
  requestId = crypto.randomUUID(),
): Promise<Record<string, unknown>> {
  return api(`/api/v1/device-remote-sessions/${encodeURIComponent(sessionId)}/commands`, {
    method: "POST",
    body: JSON.stringify({ name, payload, request_id: requestId }),
  });
}

export async function apiCreateDeviceLogStreamToken(
  sessionId: string,
): Promise<{ access_token: string; expires_in: number; token_type: string }> {
  return api(
    `/api/v1/device-remote-sessions/${encodeURIComponent(sessionId)}/logs/stream-token`,
    { method: "POST" },
  );
}

export async function apiClearRemoteDeviceLogs(sessionId: string): Promise<void> {
  await api(
    `/api/v1/device-remote-sessions/${encodeURIComponent(sessionId)}/logs/clear`,
    { method: "POST" },
  );
}

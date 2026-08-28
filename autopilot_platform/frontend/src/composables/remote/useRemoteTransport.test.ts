import { afterEach, describe, expect, it, vi } from "vitest";
import { connectRemoteTransport } from "./useRemoteTransport";
import type { RemoteSessionInfo } from "../useRemoteSession";

type Listener = (event?: { data?: string }) => void;

class FakeWebSocket {
  static OPEN = 1;
  static CONNECTING = 0;
  static instances: FakeWebSocket[] = [];
  readyState = FakeWebSocket.CONNECTING;
  sent: string[] = [];
  private listeners = new Map<string, Listener[]>();

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type: string, listener: Listener) {
    const list = this.listeners.get(type) || [];
    list.push(listener);
    this.listeners.set(type, list);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = 3;
    for (const listener of this.listeners.get("close") || []) listener();
  }

  openNow() {
    this.readyState = FakeWebSocket.OPEN;
    for (const listener of this.listeners.get("open") || []) listener();
  }

  emitMessage(payload: unknown) {
    for (const listener of this.listeners.get("message") || []) {
      listener({ data: JSON.stringify(payload) });
    }
  }
}

function session(partial?: Partial<RemoteSessionInfo>): RemoteSessionInfo {
  return {
    id: "sess-1",
    device_id: "dev-1",
    runner_id: "runner-1",
    udid: "UDID",
    platform: "android",
    status: "connected",
    capabilities: ["webrtc"],
    access_token: "tok-1",
    signaling_base_path: "/api/v1/device-remote-sessions/sess-1",
    participant_id: "p-1",
    participant_role: "controller",
    viewer_count: 0,
    max_viewers: 5,
    ice_servers: [],
    transport: {
      signaling: "ws",
      media: "ws",
      command: "ws",
      websocket_path: "/api/v1/device-remote-sessions/sess-1/ws",
    },
    deviceLabel: "dev",
    ...partial,
  };
}

afterEach(() => {
  FakeWebSocket.instances = [];
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("connectRemoteTransport", () => {
  it("falls back when transport is not ws", () => {
    const states: string[] = [];
    const transport = connectRemoteTransport(
      session({
        transport: {
          signaling: "http",
          media: "http",
          command: "http",
          websocket_path: "",
        },
      }),
      { onMessage: () => undefined, onState: (s) => states.push(s) },
    );
    expect(transport.mode).toBe("http");
    expect(states).toEqual(["fallback"]);
  });

  it("auths via first frame and keeps token out of URL", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
    const states: string[] = [];
    const transport = connectRemoteTransport(session(), {
      onMessage: () => undefined,
      onState: (s) => states.push(s),
    });
    expect(states[0]).toBe("connecting");
    const sock = FakeWebSocket.instances[0];
    expect(sock.url).not.toContain("access_token=");
    expect(sock.url).toContain("role=browser");
    sock.openNow();
    expect(JSON.parse(sock.sent[0])).toMatchObject({
      type: "auth",
      access_token: "tok-1",
    });
    expect(transport.send({ channel: "signaling", type: "event", name: "x", payload: {} })).toBe(
      false,
    );
    sock.emitMessage({
      channel: "event",
      name: "transport.ready",
      payload: { auth_via: "first_frame" },
    });
    expect(transport.mode).toBe("ws");
    expect(states).toContain("open");
    expect(
      transport.send({ channel: "signaling", type: "event", name: "x", payload: {} }),
    ).toBe(true);
    expect(sock.sent.length).toBe(2);
  });

  it("does not close CONNECTING socket on ready timeout", () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
    const states: string[] = [];
    connectRemoteTransport(session(), {
      onMessage: () => undefined,
      onState: (s) => states.push(s),
    });
    const sock = FakeWebSocket.instances[0];
    expect(sock.readyState).toBe(FakeWebSocket.CONNECTING);
    vi.advanceTimersByTime(8000);
    expect(states).toContain("fallback");
    expect(sock.readyState).toBe(FakeWebSocket.CONNECTING);
  });

  it("schedules reconnect after socket close", () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
    const states: string[] = [];
    connectRemoteTransport(session(), {
      onMessage: () => undefined,
      onState: (s) => states.push(s),
    });
    const first = FakeWebSocket.instances[0];
    first.openNow();
    first.emitMessage({ channel: "event", name: "transport.ready", payload: {} });
    expect(states).toContain("open");
    first.close();
    expect(states).toContain("fallback");
    vi.advanceTimersByTime(500);
    expect(FakeWebSocket.instances.length).toBe(2);
    expect(states.filter((s) => s === "connecting").length).toBeGreaterThanOrEqual(2);
  });

  it("uses same-origin websocket via vite proxy in dev", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
    const { remoteWebSocketUrl, loadPlatformBootstrap } = await import("../../api/bootstrap");
    vi.stubGlobal("window", {
      location: {
        port: "5173",
        protocol: "http:",
        host: "127.0.0.1:5173",
        origin: "http://127.0.0.1:5173",
      },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          schema_version: "1",
          platform_base_url: "http://127.0.0.1:8000",
          api_prefix: "/api/v1",
          web_dev_port: 5173,
          endpoints: {},
          runner: { module: "m", cli_command: "c" },
          flags: {},
        }),
      ),
    );
    await loadPlatformBootstrap(true);
    const url = remoteWebSocketUrl(
      "/api/v1/device-remote-sessions/s/ws",
      new URLSearchParams({ role: "browser" }),
    );
    expect(url.startsWith("ws://127.0.0.1:5173/")).toBe(true);
  });
});

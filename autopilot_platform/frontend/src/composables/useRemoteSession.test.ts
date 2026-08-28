import { describe, expect, it } from "vitest";
import {
  canObserveRemote,
  canOpenRemote,
  isReservationOccupier,
  prefersMjpeg,
  type RemoteSessionInfo,
} from "./useRemoteSession";
import type { Device } from "../api";

function device(partial: Partial<Device>): Device {
  return {
    id: "d1",
    udid: "U1",
    platform: "android",
    name: "n",
    model: "m",
    os_version: "14",
    state: "ready",
    busy_kind: "reservation",
    can_release_reservation: true,
    ...partial,
  } as Device;
}

describe("remote session gating", () => {
  it("isReservationOccupier prefers user id over username", () => {
    const occupied = device({
      reservation_user_id: "u-alice",
      reservation_username: "alice",
    });
    expect(isReservationOccupier(occupied, { id: "u-alice", username: "alice" })).toBe(true);
    expect(isReservationOccupier(occupied, { id: "u-admin", username: "alice" })).toBe(false);
    expect(isReservationOccupier(occupied, "alice")).toBe(true);
  });

  it("canOpenRemote is only for the occupier on android/ios", () => {
    expect(
      canOpenRemote(device({ platform: "android", reservation_username: "alice" }), "alice"),
    ).toBe(true);
    expect(
      canOpenRemote(device({ platform: "ios", reservation_username: "alice" }), "alice"),
    ).toBe(true);
    expect(
      canOpenRemote(device({ platform: "web", reservation_username: "alice" }), "alice"),
    ).toBe(false);
    expect(
      canOpenRemote(
        device({
          can_release_reservation: true,
          can_manage: true,
          reservation_username: "alice",
        }),
        "admin",
      ),
    ).toBe(false);
    expect(canOpenRemote(device({ busy_kind: "job", reservation_username: "alice" }), "alice")).toBe(
      false,
    );
  });

  it("canObserveRemote requires an active remote session on someone else's reservation", () => {
    expect(
      canObserveRemote(
        device({
          can_manage: true,
          can_release_reservation: true,
          reservation_username: "alice",
          remote_session_active: true,
        }),
        "admin",
      ),
    ).toBe(true);
    expect(
      canObserveRemote(
        device({
          can_manage: true,
          can_release_reservation: true,
          reservation_username: "alice",
          remote_session_active: false,
        }),
        "admin",
      ),
    ).toBe(false);
    expect(
      canObserveRemote(
        device({
          can_manage: false,
          can_release_reservation: false,
          reservation_username: "alice",
          remote_session_active: true,
        }),
        "bob",
      ),
    ).toBe(false);
    expect(
      canObserveRemote(
        device({
          can_manage: true,
          can_release_reservation: true,
          reservation_username: "admin",
          remote_session_active: true,
        }),
        "admin",
      ),
    ).toBe(false);
  });

  it("prefersMjpeg for ios capability without webrtc", () => {
    const ios: RemoteSessionInfo = {
      id: "s",
      device_id: "d",
      runner_id: "r",
      udid: "u",
      platform: "ios",
      status: "ready",
      capabilities: ["mirror", "control", "mjpeg", "ios-wda"],
      access_token: "t",
      signaling_base_path: "/",
      participant_id: "p",
      participant_role: "controller",
      viewer_count: 0,
      max_viewers: 5,
      ice_servers: [],
      transport: {
        signaling: "ws",
        media: "ws",
        command: "ws",
        websocket_path: "/ws",
      },
      deviceLabel: "ios",
    };
    expect(prefersMjpeg(ios)).toBe(true);
    expect(
      prefersMjpeg({
        ...ios,
        platform: "android",
        capabilities: ["webrtc", "android-scrcpy"],
      }),
    ).toBe(false);
  });
});

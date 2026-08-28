/**
 * 与 WebAppFlaskscrcpy useScrcpySession.js::toDataChannelEvent 一致。
 * Runner 侧消费见 runner/remote/android/input_dispatch.py（自 scrcpy_input.py 移植）。
 */

export type TouchPayload = { x: number; y: number; action: number };
export type ScrollPayload = { x: number; y: number; h: number; v: number };
export type KeyPayload = { keycode: number; action?: number };

/** DataChannel JSON 真源（与 services/scrcpy_input.py 文档一致）。 */
export function toDataChannelEvent(
  type: string,
  payload: Record<string, unknown> = {},
): Record<string, unknown> | null {
  if (type === "touch") {
    return {
      t: "touch",
      x: payload.x,
      y: payload.y,
      action: payload.action,
    };
  }
  if (type === "scroll") {
    return {
      t: "scroll",
      x: payload.x,
      y: payload.y,
      h: payload.h,
      v: payload.v,
    };
  }
  if (type === "key") {
    return {
      t: "key",
      code: payload.keycode,
      action: payload.action,
    };
  }
  if (type === "swipe") {
    const start = (payload.start as number[] | undefined) || [];
    const end = (payload.end as number[] | undefined) || [];
    return {
      t: "swipe",
      startX: start[0],
      startY: start[1],
      endX: end[0],
      endY: end[1],
      duration: payload.duration,
    };
  }
  if (type === "text") return { t: "text", text: payload.text };
  if (type === "set_power_mode") return { t: "power", mode: payload.mode ?? 2 };
  if (type === "expand_notification") return { t: "expandNotification" };
  if (type === "expand_settings") return { t: "expandSettings" };
  if (type === "collapse_panels") return { t: "collapse" };
  if (type === "rotate_device") return { t: "rotate" };
  if (type === "request_keyframe") {
    return { t: "request_keyframe", reason: String(payload.reason || "") };
  }
  if (type === "clipboard_get") return { t: "clipboard.get" };
  if (type === "clipboard_set") {
    return { t: "clipboard.set", text: payload.text, paste: payload.paste };
  }
  return null;
}

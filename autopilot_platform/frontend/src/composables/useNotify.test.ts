import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  TOAST_MAX,
  TOAST_MS,
  createNotifier,
  dismissToast,
  notifyToasts,
  pauseToast,
  resetNotifyPolicy,
  resumeToast,
  setNotifyPolicy,
  toast,
} from "./useNotify";

afterEach(() => {
  for (const item of [...notifyToasts.value]) {
    dismissToast(item.id);
  }
  resetNotifyPolicy();
  vi.useRealTimers();
});

beforeEach(() => {
  vi.useFakeTimers();
});

describe("toast stack", () => {
  it("newest first and drops the oldest past TOAST_MAX", () => {
    for (let i = 1; i <= TOAST_MAX + 1; i += 1) {
      toast(`n${i}`, "error");
    }
    expect(notifyToasts.value.map((t) => t.text)).toEqual(["n5", "n4", "n3", "n2"]);
    expect(notifyToasts.value).toHaveLength(TOAST_MAX);
  });

  it("keeps ok shorter than warn/error when success is forced on", () => {
    toast("ok", "success", { toast: true });
    vi.advanceTimersByTime(TOAST_MS.success - 1);
    expect(notifyToasts.value).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(notifyToasts.value).toHaveLength(0);

    toast("failed", "error");
    vi.advanceTimersByTime(TOAST_MS.success);
    expect(notifyToasts.value).toHaveLength(1);
    vi.advanceTimersByTime(TOAST_MS.error - TOAST_MS.success);
    expect(notifyToasts.value).toHaveLength(0);
  });

  it("pauses remaining time while hovered", () => {
    toast("hold", "success", { toast: true });
    const id = notifyToasts.value[0].id;
    vi.advanceTimersByTime(1000);
    pauseToast(id);
    vi.advanceTimersByTime(TOAST_MS.success);
    expect(notifyToasts.value).toHaveLength(1);
    resumeToast(id);
    vi.advanceTimersByTime(TOAST_MS.success - 1000 - 1);
    expect(notifyToasts.value).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(notifyToasts.value).toHaveLength(0);
  });

  it("accepts warn and dismiss clears the timer", () => {
    toast("occupier", "warn");
    expect(notifyToasts.value[0].kind).toBe("warn");
    const id = notifyToasts.value[0].id;
    dismissToast(id);
    vi.advanceTimersByTime(TOAST_MS.warn);
    expect(notifyToasts.value).toHaveLength(0);
  });
});

describe("toast kind policy", () => {
  it("drops ok/info by default and keeps warn/error", () => {
    toast("saved", "success");
    toast("hint", "info");
    toast("careful", "warn");
    toast("failed", "error");
    expect(notifyToasts.value.map((t) => t.kind)).toEqual(["error", "warn"]);
  });

  it("maps legacy ok/bad kinds to success/error", () => {
    const push = toast as (text: string, kind: string, opts?: { toast?: boolean }) => void;
    push("legacy-bad", "bad");
    push("legacy-ok", "ok", { toast: true });
    expect(notifyToasts.value.map((t) => t.kind)).toEqual(["success", "error"]);
  });

  it("forces a success toast with { toast: true }", () => {
    toast("copied", "success", { toast: true });
    expect(notifyToasts.value).toHaveLength(1);
    expect(notifyToasts.value[0].text).toBe("copied");
  });

  it("lets a panel opt into success via createNotifier", () => {
    const notify = createNotifier({ success: true });
    notify("pool saved", "success");
    notify("hint", "info");
    expect(notifyToasts.value.map((t) => t.text)).toEqual(["pool saved"]);
  });

  it("applies setNotifyPolicy until reset", () => {
    setNotifyPolicy({ success: true, info: true });
    toast("a", "success");
    toast("b", "info");
    expect(notifyToasts.value).toHaveLength(2);
    resetNotifyPolicy();
    toast("c", "success");
    expect(notifyToasts.value.map((t) => t.text)).toEqual(["b", "a"]);
  });
});

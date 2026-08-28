import { afterEach, describe, expect, it } from "vitest";
import { remoteDialogState } from "../useRemoteSession";
import {
  configureRemoteCommandSender,
  emitRemoteCommandMessage,
  sendRemoteCommand,
  sendRemoteCommandUntil,
} from "./useRemoteCommands";

afterEach(() => {
  configureRemoteCommandSender(null);
  remoteDialogState.value = null;
});

describe("remote command bus", () => {
  it("correlates a terminal result by request id", async () => {
    configureRemoteCommandSender((message) => {
      queueMicrotask(() => {
        emitRemoteCommandMessage({
          t: "clipboard.value",
          request_id: message.request_id,
          text: "hello",
        });
      });
      return true;
    });
    const result = await sendRemoteCommand({
      t: "clipboard.get",
      request_id: "request-1",
    });
    expect(result.text).toBe("hello");
  });

  it("keeps waiting through progress events", async () => {
    configureRemoteCommandSender((message) => {
      queueMicrotask(() => {
        emitRemoteCommandMessage({
          t: "file.progress",
          request_id: message.request_id,
          received: 5,
          total: 10,
        });
        emitRemoteCommandMessage({
          t: "file.done",
          request_id: message.request_id,
          ok: true,
        });
      });
      return true;
    });
    const result = await sendRemoteCommand({
      t: "file.end",
      request_id: "request-2",
    });
    expect(result.t).toBe("file.done");
  });

  it("rejects generic error while waiting for a typed file terminal event", async () => {
    configureRemoteCommandSender((message) => {
      queueMicrotask(() => {
        emitRemoteCommandMessage({
          t: "error",
          request_id: message.request_id,
          error: "Permission denied",
        });
      });
      return true;
    });
    await expect(
      sendRemoteCommandUntil(
        { t: "file.end", request_id: "request-end-error" },
        (message) => message.t === "file.done" || message.t === "file.error",
      ),
    ).rejects.toThrow("Permission denied");
  });

  it("resolves typed file.error so callers can read error_code", async () => {
    configureRemoteCommandSender((message) => {
      queueMicrotask(() => {
        emitRemoteCommandMessage({
          t: "file.error",
          request_id: message.request_id,
          error: "签名冲突",
          error_code: "signature_mismatch",
          existing_package: "com.example.app",
        });
      });
      return true;
    });
    const result = await sendRemoteCommandUntil(
      { t: "file.end", request_id: "request-end-typed" },
      (message) => message.t === "file.done" || message.t === "file.error",
    );
    expect(result.t).toBe("file.error");
    expect(result.error_code).toBe("signature_mismatch");
    expect(result.existing_package).toBe("com.example.app");
  });

  it("rejects immediately when no transport accepts the command", async () => {
    configureRemoteCommandSender(() => false);
    await expect(
      sendRemoteCommand({ t: "stream.stats", request_id: "request-3" }),
    ).rejects.toThrow("发送失败");
  });

  it("blocks write commands in viewer mode before hitting the sender", async () => {
    remoteDialogState.value = {
      device: { id: "d1", udid: "u", platform: "android", name: "n", model: "m", runner_id: "r" },
      session: null,
      mode: "viewer",
      resolve: () => undefined,
    };
    let sent = false;
    configureRemoteCommandSender(() => {
      sent = true;
      return true;
    });
    await expect(sendRemoteCommand({ t: "clipboard.set", text: "x" })).rejects.toThrow(
      "旁观模式为只读",
    );
    expect(sent).toBe(false);
  });
});

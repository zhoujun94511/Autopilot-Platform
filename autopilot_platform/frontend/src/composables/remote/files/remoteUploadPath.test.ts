import { describe, expect, it } from "vitest";
import {
  asUploadDirRemote,
  displayUploadDestination,
  isAndroidRootDir,
  joinUploadRemote,
  normalizeUploadDir,
} from "./remoteUploadPath";

describe("remoteUploadPath", () => {
  it("keeps android root instead of collapsing it to empty", () => {
    expect(normalizeUploadDir("/")).toBe("/");
    expect(normalizeUploadDir("///")).toBe("/");
    expect(normalizeUploadDir("/sdcard/")).toBe("/sdcard");
    expect(normalizeUploadDir(".")).toBe("");
  });

  it("does not pretend root uploads go to /sdcard", () => {
    expect(displayUploadDestination("", "/", "android")).toBe("/");
    expect(displayUploadDestination("", "", "android")).toBe("/sdcard");
    expect(displayUploadDestination("", "", "ios")).toBe(".");
    expect(isAndroidRootDir("/")).toBe(true);
    expect(isAndroidRootDir("/sdcard")).toBe(false);
  });

  it("joins android directory remotes for file.end push", () => {
    expect(asUploadDirRemote("/", "/sdcard")).toBe("/");
    expect(asUploadDirRemote("/sdcard/Download/", "/sdcard")).toBe(
      "/sdcard/Download/",
    );
  });

  it("joins ios destinations with the file name", () => {
    expect(joinUploadRemote("Documents", "fast_script.py")).toBe(
      "Documents/fast_script.py",
    );
    expect(joinUploadRemote("", "fast_script.py")).toBe("fast_script.py");
    expect(joinUploadRemote("/", "fast_script.py")).toBe("/fast_script.py");
  });
});

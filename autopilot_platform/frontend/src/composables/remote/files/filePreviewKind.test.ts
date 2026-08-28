import { describe, expect, it } from "vitest";
import {
  canPreviewFile,
  filePreviewKind,
  previewBlockReason,
  previewMimeType,
} from "./filePreviewKind";

describe("filePreviewKind", () => {
  it("detects previewable extensions", () => {
    expect(filePreviewKind("photo.jpg")).toBe("image");
    expect(filePreviewKind("clip.mp4")).toBe("video");
    expect(filePreviewKind("notes.txt")).toBe("text");
    expect(filePreviewKind("archive.zip")).toBeNull();
    expect(canPreviewFile("a.pdf")).toBe(true);
  });

  it("blocks heic like the iOS reference project", () => {
    expect(previewBlockReason("IMG_001.HEIC")).toMatch(/HEIC/);
    expect(canPreviewFile("photo.heic")).toBe(false);
    expect(filePreviewKind("photo.heif")).toBeNull();
  });

  it("returns mime types for media preview", () => {
    expect(previewMimeType("a.jpg", "image")).toBe("image/jpeg");
    expect(previewMimeType("a.mp4", "video")).toBe("video/mp4");
  });
});

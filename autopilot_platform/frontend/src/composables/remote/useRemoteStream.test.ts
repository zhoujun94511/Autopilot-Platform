import { describe, expect, it } from "vitest";
import {
  STREAM_LIMITS,
  clampAndroidWidth,
  clampStreamInt,
} from "./useRemoteStream";

describe("stream quality clamps", () => {
  it("caps bitrate and fps to the safe window", () => {
    expect(
      clampStreamInt(99_000_000, STREAM_LIMITS.bitrate.min, STREAM_LIMITS.bitrate.max, 4_000_000),
    ).toBe(20_000_000);
    expect(clampStreamInt("nope", 5, 60, 60)).toBe(60);
    expect(clampStreamInt(240, 5, 60, 60)).toBe(60);
  });

  it("rejects tiny positive widths that crash some encoders", () => {
    expect(clampAndroidWidth(0)).toBe(0);
    expect(clampAndroidWidth(120)).toBe(480);
    expect(clampAndroidWidth(4096)).toBe(1920);
  });
});

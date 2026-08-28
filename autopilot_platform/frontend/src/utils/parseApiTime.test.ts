import { describe, expect, it } from "vitest";
import { parseApiTime } from "./parseApiTime";

describe("parseApiTime", () => {
  it("treats timezone-less ISO as UTC", () => {
    const utcMs = Date.UTC(2026, 7, 24, 13, 20, 35);
    expect(parseApiTime("2026-08-24T13:20:35")).toBe(utcMs);
    expect(parseApiTime("2026-08-24T13:20:35Z")).toBe(utcMs);
  });
});

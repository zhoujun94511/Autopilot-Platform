import { describe, expect, it } from "vitest";
import { toDataChannelEvent } from "./scrcpyInputProtocol";

describe("toDataChannelEvent", () => {
  it("matches WebAppFlaskscrcpy touch/key/scroll shape", () => {
    expect(toDataChannelEvent("touch", { x: 10, y: 20, action: 0 })).toEqual({
      t: "touch",
      x: 10,
      y: 20,
      action: 0,
    });
    expect(toDataChannelEvent("key", { keycode: 4, action: 1 })).toEqual({
      t: "key",
      code: 4,
      action: 1,
    });
    expect(toDataChannelEvent("scroll", { x: 1, y: 2, h: 3, v: 4 })).toEqual({
      t: "scroll",
      x: 1,
      y: 2,
      h: 3,
      v: 4,
    });
  });
});

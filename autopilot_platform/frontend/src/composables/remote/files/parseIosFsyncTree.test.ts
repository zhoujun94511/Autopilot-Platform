import { describe, expect, it } from "vitest";
import {
  collapseIosFsyncTree,
  flattenIosFsyncTree,
  iosTreeAnyExpanded,
  parseIosFsyncTree,
} from "./parseIosFsyncTree";

describe("parseIosFsyncTree", () => {
  it("parses indented tree with base path", () => {
    const text = [
      "|-Books/",
      "|  |-Managed/",
      "|  |  |-readme.txt",
    ].join("\n");
    const roots = parseIosFsyncTree(text, "Media");
    expect(roots).toHaveLength(1);
    expect(roots[0].name).toBe("Books");
    expect(roots[0].path).toBe("Media/Books");
    expect(roots[0].children[0].path).toBe("Media/Books/Managed");
    expect(roots[0].children[0].children[0].path).toBe(
      "Media/Books/Managed/readme.txt",
    );
  });

  it("flattens visible rows respecting expand state", () => {
    const roots = parseIosFsyncTree("|-A/\n|  |-b.txt", ".");
    roots[0].expanded = true;
    const rows = flattenIosFsyncTree(roots);
    expect(rows.map((row) => row.node.name)).toEqual(["A", "b.txt"]);
    collapseIosFsyncTree(roots);
    expect(iosTreeAnyExpanded(roots)).toBe(false);
    expect(flattenIosFsyncTree(roots).map((row) => row.node.name)).toEqual([
      "A",
    ]);
  });
});

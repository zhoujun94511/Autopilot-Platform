import { describe, expect, it } from "vitest";
import {
  collapseAndroidLazyTree,
  entriesToLazyTreeNodes,
  flattenAndroidLazyTree,
  type AndroidLazyTreeNode,
} from "./androidLazyTree";

describe("androidLazyTree", () => {
  it("builds lazy nodes from flat entries", () => {
    const nodes = entriesToLazyTreeNodes([
      { name: "DCIM", path: "/sdcard/DCIM", is_dir: true, size: 0 },
      { name: "a.txt", path: "/sdcard/a.txt", is_dir: false, size: 12 },
    ]);
    expect(nodes[0].loaded).toBe(false);
    expect(nodes[1].loaded).toBe(true);
    expect(nodes[1].size).toBe(12);
  });

  it("flattens expanded branches only", () => {
    const root: AndroidLazyTreeNode = {
      name: "sdcard",
      path: "/sdcard",
      isDir: true,
      expanded: true,
      loaded: true,
      loading: false,
      children: [
        {
          name: "a.txt",
          path: "/sdcard/a.txt",
          isDir: false,
          expanded: false,
          loaded: true,
          loading: false,
          children: [],
          size: 1,
        },
      ],
    };
    expect(flattenAndroidLazyTree([root]).map((row) => row.node.name)).toEqual([
      "sdcard",
      "a.txt",
    ]);
    collapseAndroidLazyTree([root]);
    expect(flattenAndroidLazyTree([root]).map((row) => row.node.name)).toEqual([
      "sdcard",
    ]);
  });
});

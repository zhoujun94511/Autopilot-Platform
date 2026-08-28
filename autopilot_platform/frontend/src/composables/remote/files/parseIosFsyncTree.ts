/** go-ios `fsync tree` 文本树节点。 */

export type IosFsyncTreeNode = {
  name: string;
  isDir: boolean;
  expanded: boolean;
  children: IosFsyncTreeNode[];
  path: string;
};

export type IosFsyncTreeRow = {
  node: IosFsyncTreeNode;
  depth: number;
};

/**
 * 解析 go-ios fsync tree 输出的缩进文本：
 *   |-Books/
 *   |  |-Managed/
 *   |  |  |-.Managed.plist.lock
 */
export function parseIosFsyncTree(
  text: string,
  basePath = ".",
): IosFsyncTreeNode[] {
  const base =
    basePath && basePath !== "." ? basePath.replace(/\/+$/, "") : "";
  const roots: IosFsyncTreeNode[] = [];
  const stack: Array<{
    children: IosFsyncTreeNode[];
    depth: number;
    path: string;
  }> = [{ children: roots, depth: -1, path: base }];

  for (const raw of text.split(/\r?\n/)) {
    const idx = raw.indexOf("|-");
    if (idx < 0) continue;
    const depth = Math.floor(idx / 3);
    let name = raw.slice(idx + 2);
    if (!name) continue;
    const isDir = name.endsWith("/");
    if (isDir) name = name.slice(0, -1);
    while (stack.length > 1 && stack[stack.length - 1].depth >= depth) {
      stack.pop();
    }
    const parent = stack[stack.length - 1];
    const node: IosFsyncTreeNode = {
      name,
      isDir,
      expanded: false,
      children: [],
      path: (parent.path ? `${parent.path}/` : "") + name,
    };
    parent.children.push(node);
    if (isDir) {
      stack.push({ children: node.children, depth, path: node.path });
    }
  }
  return roots;
}

export function flattenIosFsyncTree(nodes: IosFsyncTreeNode[]): IosFsyncTreeRow[] {
  const out: IosFsyncTreeRow[] = [];
  const walk = (list: IosFsyncTreeNode[], depth: number) => {
    for (const node of list) {
      out.push({ node, depth });
      if (node.isDir && node.expanded && node.children.length) {
        walk(node.children, depth + 1);
      }
    }
  };
  walk(nodes, 0);
  return out;
}

export function iosTreeAnyExpanded(nodes: IosFsyncTreeNode[]): boolean {
  let found = false;
  const walk = (list: IosFsyncTreeNode[]) => {
    for (const node of list) {
      if (node.expanded) found = true;
      if (node.children.length) walk(node.children);
    }
  };
  walk(nodes);
  return found;
}

export function collapseIosFsyncTree(nodes: IosFsyncTreeNode[]): void {
  const walk = (list: IosFsyncTreeNode[]) => {
    for (const node of list) {
      node.expanded = false;
      if (node.children.length) walk(node.children);
    }
  };
  walk(nodes);
}

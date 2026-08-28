import type { RemoteFileEntry } from "../useRemoteFiles";

/** Android 懒加载树节点（与 iOS fsync 解析节点字段对齐，供同一树 UI 渲染）。 */
export type AndroidLazyTreeNode = {
  name: string;
  path: string;
  isDir: boolean;
  expanded: boolean;
  children: AndroidLazyTreeNode[];
  size?: number;
  /** 目录是否已拉取过子项 */
  loaded: boolean;
  loading: boolean;
};

export function entryToLazyTreeNode(entry: RemoteFileEntry): AndroidLazyTreeNode {
  return {
    name: entry.name,
    path: entry.path,
    isDir: entry.is_dir,
    expanded: false,
    children: [],
    size: entry.is_dir ? undefined : entry.size,
    loaded: !entry.is_dir,
    loading: false,
  };
}

export function entriesToLazyTreeNodes(
  entries: RemoteFileEntry[],
): AndroidLazyTreeNode[] {
  return entries.map(entryToLazyTreeNode);
}

export type AndroidLazyTreeRow = {
  node: AndroidLazyTreeNode;
  depth: number;
};

export function flattenAndroidLazyTree(
  nodes: AndroidLazyTreeNode[],
): AndroidLazyTreeRow[] {
  const out: AndroidLazyTreeRow[] = [];
  const walk = (list: AndroidLazyTreeNode[], depth: number) => {
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

export function androidLazyTreeAnyExpanded(nodes: AndroidLazyTreeNode[]): boolean {
  let found = false;
  const walk = (list: AndroidLazyTreeNode[]) => {
    for (const node of list) {
      if (node.expanded) found = true;
      if (node.children.length) walk(node.children);
    }
  };
  walk(nodes);
  return found;
}

export function collapseAndroidLazyTree(nodes: AndroidLazyTreeNode[]): void {
  const walk = (list: AndroidLazyTreeNode[]) => {
    for (const node of list) {
      node.expanded = false;
      if (node.children.length) walk(node.children);
    }
  };
  walk(nodes);
}

/** 变更后标记目录需重新拉取子项。 */
export function invalidateAndroidLazySubtree(node: AndroidLazyTreeNode): void {
  node.loaded = false;
  node.children = [];
  node.expanded = false;
}

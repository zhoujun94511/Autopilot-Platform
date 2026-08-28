/** DesignChat FAB 几何（AUD-2026-12 Wave 1）：纯函数，无 Vue 依赖。 */

export const CHAT_FAB_SIZE = 56;
export const CHAT_FAB_EDGE = 16;
/** v2：未拖动时用 right/bottom 锚定右下角；旧 left/top 缓存易落在视口中间 */
export const CHAT_FAB_POS_KEY = "ap-mc-chat-fab-pos-v2";

export type FabPoint = { left: number; top: number };

export type ClampFabOpts = {
  size?: number;
  edge?: number;
  viewportW?: number;
  viewportH?: number;
};

function _viewport(opts?: ClampFabOpts) {
  const size = opts?.size ?? CHAT_FAB_SIZE;
  const edge = opts?.edge ?? CHAT_FAB_EDGE;
  const viewportW =
    opts?.viewportW ?? (typeof window !== "undefined" ? window.innerWidth : 0);
  const viewportH =
    opts?.viewportH ?? (typeof window !== "undefined" ? window.innerHeight : 0);
  return { size, edge, viewportW, viewportH };
}

export function clampChatFab(
  left: number,
  top: number,
  opts?: ClampFabOpts,
): FabPoint {
  const { size, edge, viewportW, viewportH } = _viewport(opts);
  const maxL = Math.max(edge, viewportW - size - edge);
  const maxT = Math.max(edge, viewportH - size - edge);
  return {
    left: Math.min(maxL, Math.max(edge, left)),
    top: Math.min(maxT, Math.max(edge, top)),
  };
}

export function defaultChatFabPos(opts?: ClampFabOpts): FabPoint {
  const { size, edge, viewportW, viewportH } = _viewport(opts);
  return clampChatFab(viewportW - size - edge, viewportH - size - edge, {
    size,
    edge,
    viewportW,
    viewportH,
  });
}

export function parseChatFabPos(raw: string | null): FabPoint | null {
  if (!raw) return null;
  try {
    const p = JSON.parse(raw) as { left?: number; top?: number };
    if (typeof p.left !== "number" || typeof p.top !== "number") return null;
    if (!Number.isFinite(p.left) || !Number.isFinite(p.top)) return null;
    return clampChatFab(p.left, p.top);
  } catch {
    return null;
  }
}

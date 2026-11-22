import { onScopeDispose } from "vue";
import type { McTabId } from "./mcRefreshScopes";

const handlers = new Map<string, () => Promise<void>>();

/** Panels that own their data refresh through the top-bar action. */
export function useManualPageRefresh(tab: McTabId, refresh: () => Promise<void>) {
  handlers.set(tab, refresh);
  onScopeDispose(() => {
    if (handlers.get(tab) === refresh) handlers.delete(tab);
  });
}

export function refreshPageFromToolbar(tab: string, fallback: () => Promise<void>) {
  return (handlers.get(tab) ?? fallback)();
}

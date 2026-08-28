/**
 * DesignChat 会话分页列表（AUD-2026-12 Wave 1）。
 */
import { type ComputedRef, type Ref } from "vue";
import {
  CHAT_SESSION_PAGE_SIZE,
  listChatSessionsPage,
  type ChatSession,
} from "../api/designChat";
import { usePagedList } from "./usePagedList";

export function useDesignChatSessions(opts: {
  generalMode: ComputedRef<boolean>;
  filterProjectId: Ref<string | undefined> | Ref<string>;
  activeSessionId: Ref<string>;
  activeSession: Ref<ChatSession | null>;
}) {
  const { generalMode, filterProjectId, activeSessionId, activeSession } = opts;

  const sessionList = usePagedList<ChatSession>({
    immediate: false,
    pageSize: CHAT_SESSION_PAGE_SIZE,
    fetchPage: ({ page, pageSize }) => {
      if (generalMode.value) {
        return Promise.resolve({ items: [], total: 0, page: 1, page_size: pageSize });
      }
      return listChatSessionsPage(filterProjectId.value, { page, pageSize });
    },
    resetSources: [() => filterProjectId.value, generalMode],
  });

  const {
    items: sessions,
    total: sessionsTotal,
    page: sessionsPage,
    pageSize: sessionsPageSize,
    loading: sessionsLoading,
    hasLoaded: sessionsHasLoaded,
    reload: reloadSessions,
    setPage: setSessionsPage,
    setPageSize: setSessionsPageSize,
  } = sessionList;

  async function loadSessions(reset = true) {
    await reloadSessions(reset);
    if (
      activeSessionId.value &&
      !sessions.value.some((s) => s.id === activeSessionId.value)
    ) {
      activeSessionId.value = "";
    }
    activeSession.value =
      sessions.value.find((s) => s.id === activeSessionId.value) || null;
  }

  return {
    sessions,
    sessionsTotal,
    sessionsPage,
    sessionsPageSize,
    sessionsLoading,
    sessionsHasLoaded,
    setSessionsPage,
    setSessionsPageSize,
    loadSessions,
  };
}

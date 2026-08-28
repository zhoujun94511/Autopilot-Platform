import { ref, watch, type Ref, type WatchSource } from "vue";
import {
  DEFAULT_PAGE_SIZE,
  type PagedResult,
} from "../utils/pagination";

export type PagedFetchFn<T> = (params: {
  page: number;
  pageSize: number;
}) => Promise<PagedResult<T>>;

export type UsePagedListOptions<T> = {
  fetchPage: PagedFetchFn<T>;
  pageSize?: number;
  immediate?: boolean;
  /** 数据域变化（组织/项目等）：始终重置到第 1 页并 reload */
  resetSources?: WatchSource<unknown>[];
  /**
   * 列表内筛选。若最近一次「未筛选」请求已确认全量为空，则不再打接口，
   * 避免空状态被 loading 拆掉重挂。
   */
  filterSources?: WatchSource<unknown>[];
  /** 当前是否未叠加列表内筛选（不含组织/项目）。配合 filterSources 使用。 */
  isUnfiltered?: () => boolean;
};

/**
 * 标准分页列表 composable：按页替换 items，配合 DataPager page 模式。
 */
export function usePagedList<T>(options: UsePagedListOptions<T>) {
  const items = ref([]) as Ref<T[]>;
  const total = ref(0);
  const page = ref(1);
  const pageSize = ref(options.pageSize ?? DEFAULT_PAGE_SIZE);
  const loading = ref(false);
  const hasLoaded = ref(false);
  const universeEmpty = ref(false);

  function rememberUniverse(nextTotal: number) {
    if (!options.isUnfiltered) return;
    if (nextTotal > 0) universeEmpty.value = false;
    else if (options.isUnfiltered()) universeEmpty.value = true;
  }

  async function reload(resetPage = false) {
    if (resetPage) page.value = 1;
    loading.value = true;
    try {
      const res = await options.fetchPage({
        page: page.value,
        pageSize: pageSize.value,
      });
      items.value = res.items;
      total.value = res.total;
      page.value = res.page;
      pageSize.value = res.page_size;
      rememberUniverse(res.total);
    } catch {
      items.value = [];
      total.value = 0;
      rememberUniverse(0);
    } finally {
      loading.value = false;
      hasLoaded.value = true;
    }
  }

  function setPage(next: number) {
    const max = Math.max(1, Math.ceil(total.value / Math.max(1, pageSize.value)) || 1);
    const pg = Math.min(max, Math.max(1, next));
    if (pg !== page.value) {
      page.value = pg;
      void reload(false);
    }
  }

  function setPageSize(size: number) {
    const n = Math.max(1, size);
    if (n !== pageSize.value) {
      pageSize.value = n;
      page.value = 1;
      void reload(false);
    }
  }

  function skipEmptyFilterReload() {
    return hasLoaded.value && universeEmpty.value;
  }

  if (options.immediate !== false) {
    void reload(true);
  }

  if (options.resetSources?.length) {
    watch(options.resetSources, () => {
      universeEmpty.value = false;
      void reload(true);
    });
  }

  if (options.filterSources?.length) {
    watch(options.filterSources, () => {
      if (skipEmptyFilterReload()) return;
      void reload(true);
    });
  }

  return {
    items,
    total,
    page,
    pageSize,
    loading,
    hasLoaded,
    universeEmpty,
    reload,
    setPage,
    setPageSize,
    skipEmptyFilterReload,
  };
}

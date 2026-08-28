/** 列表分页：类型、页码条、范围文案（设计域 / 运维共用）。 */

export type PagedResult<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};

export const PAGE_SIZE_OPTIONS = [20, 50, 100] as const;
export const DEFAULT_PAGE_SIZE = 50;

export function totalPages(total: number, pageSize: number): number {
  const size = Math.max(1, pageSize || DEFAULT_PAGE_SIZE);
  return Math.max(1, Math.ceil(Math.max(0, total) / size));
}

export function rangeLabel(total: number, page: number, pageSize: number): string {
  if (total <= 0) return "共 0 条";
  const size = Math.max(1, pageSize || DEFAULT_PAGE_SIZE);
  const pg = Math.max(1, page);
  const start = (pg - 1) * size + 1;
  const end = Math.min(total, pg * size);
  return `共 ${total} 条 · 当前第 ${start}–${end}`;
}

export type PageNavItem =
  | { kind: "page"; page: number; active: boolean }
  | { kind: "ellipsis" };

/** 生成页码条（含首尾与省略号）。 */
export function buildPageNav(
  total: number,
  page: number,
  pageSize: number,
  siblingCount = 1,
): PageNavItem[] {
  const pages = totalPages(total, pageSize);
  const current = Math.min(Math.max(1, page), pages);
  if (pages <= 1) return [{ kind: "page", page: 1, active: current === 1 }];

  const slots = new Set<number>([1, pages, current]);
  for (let i = 1; i <= siblingCount; i += 1) {
    slots.add(Math.max(1, current - i));
    slots.add(Math.min(pages, current + i));
  }
  const ordered = [...slots].sort((a, b) => a - b);
  const out: PageNavItem[] = [];
  let prev = 0;
  for (const n of ordered) {
    if (prev && n - prev > 1) out.push({ kind: "ellipsis" });
    out.push({ kind: "page", page: n, active: n === current });
    prev = n;
  }
  return out;
}

export function buildPageQuery(params: {
  page?: number;
  pageSize?: number;
  extra?: Record<string, string | number | boolean | undefined | null>;
}): string {
  const q = new URLSearchParams();
  if (params.page != null) q.set("page", String(params.page));
  if (params.pageSize != null) q.set("page_size", String(params.pageSize));
  if (params.extra) {
    for (const [key, raw] of Object.entries(params.extra)) {
      if (raw === undefined || raw === null || raw === "") continue;
      q.set(key, String(raw));
    }
  }
  const qs = q.toString();
  return qs ? `?${qs}` : "";
}

/** 解析后端 ListPage 或兼容裸数组。 */
export function normalizePagedResult<T>(
  raw: PagedResult<T> | T[] | null | undefined,
  fallbackPage = 1,
  fallbackSize = DEFAULT_PAGE_SIZE,
): PagedResult<T> {
  if (Array.isArray(raw)) {
    return {
      items: raw,
      total: raw.length,
      page: fallbackPage,
      page_size: fallbackSize,
    };
  }
  const body = raw || { items: [], total: 0, page: fallbackPage, page_size: fallbackSize };
  return {
    items: body.items || [],
    total: Number(body.total) || 0,
    page: Number(body.page) || fallbackPage,
    page_size: Number(body.page_size) || fallbackSize,
  };
}

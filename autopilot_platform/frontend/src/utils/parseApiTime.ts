/** 解析 Platform API 返回的时间戳（UTC 存库、JSON 常无 Z 后缀）。 */
export function parseApiTime(iso?: string | null): number {
  const raw = (iso || "").trim();
  if (!raw) return Number.NaN;
  if (/[zZ]$|[+-]\d{2}:\d{2}$/.test(raw)) {
    return new Date(raw).getTime();
  }
  return new Date(`${raw}Z`).getTime();
}

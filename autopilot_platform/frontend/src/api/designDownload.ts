/** 设计域文件下载（Excel / CSV / JSON 等 blob 响应）。 */

import { parseApiError, sessionFetch } from "../api";

export async function downloadDesignBlob(
  path: string,
  opts?: {
    method?: string;
    body?: unknown;
    filename?: string;
  },
): Promise<void> {
  const headers = new Headers();

  let body: BodyInit | undefined;
  const method = opts?.method || (opts?.body !== undefined ? "POST" : "GET");
  if (opts?.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(opts.body);
  }

  const res = await sessionFetch(path, { method, headers, body });
  if (!res.ok) throw await parseApiError(res);

  const blob = await res.blob();
  let filename = opts?.filename || "";
  if (!filename) {
    const cd = res.headers.get("Content-Disposition") || "";
    const m = /filename\*?=(?:UTF-8''|"?)([^";]+)/i.exec(cd);
    if (m?.[1]) filename = decodeURIComponent(m[1].replace(/"/g, ""));
  }
  if (!filename) {
    const ct = res.headers.get("Content-Type") || "";
    if (ct.includes("json")) filename = "download.json";
    else if (ct.includes("csv")) filename = "download.csv";
    else filename = "download.xlsx";
  }

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

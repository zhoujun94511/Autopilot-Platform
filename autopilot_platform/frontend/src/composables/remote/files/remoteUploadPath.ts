/** 规范化远控上传目录，保留 Android 根路径 `/`，去掉其它目录的尾斜杠。 */
export function normalizeUploadDir(path: string): string {
  const value = (path || "").trim();
  if (!value || value === ".") return "";
  if (value === "/" || /^\/+$/.test(value)) return "/";
  return value.replace(/\/+$/, "");
}

export function displayUploadDestination(
  dir: string,
  fallback: string,
  platform?: string,
): string {
  const base = normalizeUploadDir(dir) || normalizeUploadDir(fallback);
  if (!base) return platform === "ios" ? "." : "/sdcard";
  return base;
}

/** Android `file.push` 的 remote 目录形式：以 `/` 结尾，根目录就是 `/`。 */
export function asUploadDirRemote(dir: string, fallback: string): string {
  const base = normalizeUploadDir(dir) || normalizeUploadDir(fallback) || "/sdcard";
  return base === "/" ? "/" : `${base}/`;
}

/** iOS 上传目标是含文件名的相对路径。 */
export function joinUploadRemote(dir: string, filename: string): string {
  const name = filename.replace(/^\/+/, "") || "upload.bin";
  const base = normalizeUploadDir(dir);
  if (!base) return name;
  if (base === "/") return `/${name}`;
  return `${base}/${name}`;
}

export function isAndroidRootDir(path: string): boolean {
  return normalizeUploadDir(path) === "/";
}

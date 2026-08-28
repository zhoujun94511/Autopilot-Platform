export type FilePreviewKind = "text" | "image" | "audio" | "pdf" | "video" | null;

const PREVIEW_EXTENSIONS: Record<Exclude<FilePreviewKind, null>, Set<string>> = {
  text: new Set([
    "txt",
    "log",
    "md",
    "rst",
    "json",
    "xml",
    "yaml",
    "yml",
    "csv",
    "tsv",
    "ini",
    "conf",
    "cfg",
    "properties",
    "env",
    "sh",
    "bash",
    "zsh",
    "py",
    "js",
    "mjs",
    "ts",
    "tsx",
    "jsx",
    "vue",
    "svelte",
    "html",
    "htm",
    "css",
    "scss",
    "less",
    "java",
    "kt",
    "kts",
    "gradle",
    "pro",
    "c",
    "cc",
    "cpp",
    "cxx",
    "h",
    "hpp",
    "go",
    "rs",
    "php",
    "rb",
    "lua",
    "pl",
    "sql",
    "gitignore",
    "editorconfig",
    "dockerfile",
    "smali",
    "aidl",
  ]),
  image: new Set(["png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "svg", "avif"]),
  video: new Set(["mp4", "webm", "ogv", "mov", "m4v"]),
  audio: new Set(["mp3", "wav", "m4a", "aac", "ogg", "opus", "flac", "oga"]),
  pdf: new Set(["pdf"]),
};

/** 浏览器无法内联渲染，参考 iOS 远控项目明确排除。 */
const PREVIEW_BLOCKED_EXTENSIONS = new Set(["heic", "heif"]);

const PREVIEW_MIME: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  webp: "image/webp",
  bmp: "image/bmp",
  svg: "image/svg+xml",
  avif: "image/avif",
  ico: "image/x-icon",
  mp4: "video/mp4",
  webm: "video/webm",
  ogv: "video/ogg",
  mov: "video/quicktime",
  m4v: "video/x-m4v",
  mp3: "audio/mpeg",
  wav: "audio/wav",
  m4a: "audio/mp4",
  aac: "audio/aac",
  ogg: "audio/ogg",
  opus: "audio/opus",
  flac: "audio/flac",
  oga: "audio/ogg",
  pdf: "application/pdf",
};

export const TEXT_PREVIEW_LIMIT = 1024 * 1024;
export const BINARY_PREVIEW_LIMIT = 50 * 1024 * 1024;

export function fileExtension(name: string): string {
  const index = name.lastIndexOf(".");
  if (index <= 0) return "";
  return name.slice(index + 1).toLowerCase();
}

export function previewBlockReason(name: string): string | null {
  const ext = fileExtension(name);
  if (PREVIEW_BLOCKED_EXTENSIONS.has(ext)) {
    return "HEIC/HEIF 格式浏览器无法内联预览，请下载后查看";
  }
  return null;
}

export function filePreviewKind(name: string): FilePreviewKind {
  if (previewBlockReason(name)) return null;
  const ext = fileExtension(name);
  if (!ext) return null;
  for (const [kind, set] of Object.entries(PREVIEW_EXTENSIONS) as Array<
    [Exclude<FilePreviewKind, null>, Set<string>]
  >) {
    if (set.has(ext)) return kind;
  }
  return null;
}

export function canPreviewFile(name: string): boolean {
  return filePreviewKind(name) !== null;
}

export function previewSizeLimit(kind: FilePreviewKind): number {
  if (kind === "text") return TEXT_PREVIEW_LIMIT;
  if (kind) return BINARY_PREVIEW_LIMIT;
  return 0;
}

export function previewMimeType(name: string, kind: FilePreviewKind): string {
  const ext = fileExtension(name);
  if (ext && PREVIEW_MIME[ext]) return PREVIEW_MIME[ext];
  if (kind === "text") return "text/plain;charset=utf-8";
  return "application/octet-stream";
}

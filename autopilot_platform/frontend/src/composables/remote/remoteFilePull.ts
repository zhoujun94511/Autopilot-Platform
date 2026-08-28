import { sendRemoteCommand, subscribeRemoteCommands, type RemoteCommandMessage } from "./useRemoteCommands";
import {
  filePreviewKind,
  previewBlockReason,
  previewMimeType,
  previewSizeLimit,
  TEXT_PREVIEW_LIMIT,
} from "./files/filePreviewKind";
import { formatFileSize } from "./files/formatFileSize";
import type { RemoteFileEntry } from "./useRemoteFiles";

export class RemoteFilePullTooLargeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RemoteFilePullTooLargeError";
  }
}

async function collectPullBlob(
  remotePath: string,
  app = "",
  maxBytes?: number,
  mimeType?: string,
): Promise<Blob> {
  const requestId = crypto.randomUUID();
  const chunks = new Map<number, Uint8Array>();
  let totalBytes = 0;
  let oversizeError: Error | null = null;
  const stop = subscribeRemoteCommands((message: RemoteCommandMessage) => {
    if (String(message.request_id || "") !== requestId) return;
    if (message.t === "file.pull.chunk") {
      const raw = atob(String(message.data || ""));
      const bytes = Uint8Array.from(raw, (char) => char.charCodeAt(0));
      totalBytes += bytes.length;
      if (maxBytes != null && totalBytes > maxBytes) {
        oversizeError = new RemoteFilePullTooLargeError(
          `文件过大（已超过 ${formatFileSize(maxBytes)}），请下载后查看`,
        );
        return;
      }
      chunks.set(Number(message.seq || 0), bytes);
    }
  });
  try {
    await sendRemoteCommand(
      {
        t: "file.pull",
        id: requestId,
        request_id: requestId,
        path: remotePath,
        app,
      },
      10 * 60_000,
    );
    if (oversizeError) throw oversizeError;
    const binaryParts = [...chunks.entries()]
      .sort(([left], [right]) => left - right)
      .map(([, value]) => value);
    return new Blob(binaryParts, mimeType ? { type: mimeType } : undefined);
  } finally {
    stop();
  }
}

export async function statRemoteFileEntry(
  path: string,
  app = "",
): Promise<RemoteFileEntry | null> {
  try {
    const result = await sendRemoteCommand({ t: "file.stat", path, app });
    const entry = result.entry;
    if (entry && typeof entry === "object" && !Array.isArray(entry)) {
      return entry as RemoteFileEntry;
    }
  } catch {
    /* iOS 等平台可能不支持 file.stat */
  }
  return null;
}

export async function pullRemoteFileBlob(
  remotePath: string,
  filename: string,
  options?: { size?: number; app?: string },
): Promise<Blob> {
  const blocked = previewBlockReason(filename);
  if (blocked) throw new Error(blocked);

  const kind = filePreviewKind(filename);
  if (!kind) throw new Error("此类型不支持内联预览");

  const limit = previewSizeLimit(kind);
  let size = options?.size;
  if (size == null) {
    const entry = await statRemoteFileEntry(remotePath, options?.app);
    size = entry?.size;
  }
  if (size != null && size > limit) {
    throw new Error(`文件过大（${formatFileSize(size)}），请下载后查看`);
  }

  const mimeType = previewMimeType(filename, kind);
  const blob = await collectPullBlob(remotePath, options?.app ?? "", limit, mimeType);

  if (kind === "text" && blob.size > TEXT_PREVIEW_LIMIT) {
    throw new RemoteFilePullTooLargeError(
      `文件过大（${formatFileSize(blob.size)}），请下载后查看`,
    );
  }
  if (kind !== "text" && blob.size > limit) {
    throw new RemoteFilePullTooLargeError(
      `文件过大（${formatFileSize(blob.size)}），请下载后查看`,
    );
  }
  return blob;
}

export async function pullRemoteFileBlobRaw(
  remotePath: string,
  app = "",
): Promise<Blob> {
  return collectPullBlob(remotePath, app);
}

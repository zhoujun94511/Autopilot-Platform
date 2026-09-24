/** 浏览器 WebCodecs 解码 iOS 27 HEVC 访问单元。主机不转码。 */

const HEVC_PROBE_CODECS = ["hev1.1.6.L150.B0", "hev1.1.6.L93.B0"];

export async function browserSupportsHevc(): Promise<boolean> {
  if (typeof VideoDecoder === "undefined" || !VideoDecoder.isConfigSupported) return false;
  for (const codec of HEVC_PROBE_CODECS) {
    try {
      const res = await VideoDecoder.isConfigSupported({ codec });
      if (res.supported) return true;
    } catch {
      /* 这一档不支持，试下一档 */
    }
  }
  return false;
}

export type HevcPlaybackHooks = {
  canvas: () => HTMLCanvasElement | null;
  onFrame: (width: number, height: number) => void;
  onUnsupported: (reason: string) => void;
  onKeyframe: () => void;
};

export class HevcCanvasPlayer {
  private decoder: VideoDecoder | null = null;
  private config: VideoDecoderConfig | null = null;
  private timestamp = 0;
  private gotKey = false;
  private needsResync = false;
  private configuring = false;
  private pending: Uint8Array[] = [];
  private keyAskedAt = 0;
  private closed = false;

  constructor(private readonly hooks: HevcPlaybackHooks) {}

  close(): void {
    this.closed = true;
    this.pending = [];
    this.closeDecoder();
  }

  async pushConfig(codec: string, description: Uint8Array): Promise<void> {
    if (this.closed) return;
    const descriptionCopy = new Uint8Array(description);
    this.config = {
      codec,
      description: descriptionCopy,
      optimizeForLatency: true,
    };
    this.configuring = true;
    let supported = false;
    try {
      const res = await VideoDecoder.isConfigSupported(this.config);
      supported = !!res.supported;
    } catch {
      supported = false;
    }
    if (this.closed) return;
    if (!supported || !this.config) {
      this.configuring = false;
      this.pending = [];
      this.hooks.onUnsupported("浏览器无法解码这路 HEVC");
      return;
    }
    try {
      this.closeDecoder();
      this.decoder = this.buildDecoder();
      this.decoder.configure(this.config);
    } catch {
      this.configuring = false;
      this.pending = [];
      this.hooks.onUnsupported("浏览器无法配置 HEVC 解码器");
      return;
    }
    this.gotKey = false;
    this.needsResync = false;
    this.configuring = false;
    const queued = this.pending;
    this.pending = [];
    queued.forEach((bytes) => this.pushPacket(bytes));
  }

  pushPacket(bytes: Uint8Array): void {
    if (this.closed || bytes.byteLength < 5) return;
    if (!this.decoder || this.configuring) {
      this.pending.push(bytes);
      if (this.pending.length > 45) {
        this.pending.shift();
        this.noteGap();
      }
      return;
    }
    this.decodePacket(bytes);
  }

  private buildDecoder(): VideoDecoder {
    return new VideoDecoder({
      output: (frame) => {
        const canvas = this.hooks.canvas();
        const ctx = canvas?.getContext("2d");
        if (ctx && canvas) {
          if (canvas.width !== frame.displayWidth || canvas.height !== frame.displayHeight) {
            canvas.width = frame.displayWidth;
            canvas.height = frame.displayHeight;
          }
          ctx.drawImage(frame, 0, 0);
          this.hooks.onFrame(frame.displayWidth, frame.displayHeight);
        }
        frame.close();
      },
      error: () => {
        this.noteGap();
      },
    });
  }

  private noteGap(): void {
    this.needsResync = true;
    const now = performance.now();
    if (now - this.keyAskedAt < 500) return;
    this.keyAskedAt = now;
    this.hooks.onKeyframe();
  }

  private decodePacket(bytes: Uint8Array): void {
    const decoder = this.decoder;
    const config = this.config;
    if (!decoder || !config || bytes.byteLength < 5) return;
    const len = (bytes[0] << 24) | (bytes[1] << 16) | (bytes[2] << 8) | bytes[3];
    if (bytes.byteLength < 4 + len) return;
    const type = bytes[4];
    const data = bytes.subarray(5, 4 + len);
    if (type === 1 && decoder.decodeQueueSize > 4) {
      this.noteGap();
      return;
    }
    if (type === 2 || (type === 0 && this.needsResync)) {
      this.closeDecoder();
      this.decoder = this.buildDecoder();
      this.decoder.configure(config);
      this.needsResync = false;
      this.gotKey = true;
    } else if (type === 0) {
      this.gotKey = true;
    }
    const active = this.decoder;
    if (!this.gotKey || this.needsResync || !active || active.state !== "configured") return;
    try {
      active.decode(
        new EncodedVideoChunk({
          type: type === 1 ? "delta" : "key",
          timestamp: this.timestamp,
          data,
        }),
      );
      this.timestamp += 16666;
    } catch {
      this.noteGap();
    }
  }

  private closeDecoder(): void {
    try {
      this.decoder?.close();
    } catch {
      /* already closed */
    }
    this.decoder = null;
    this.gotKey = false;
    this.needsResync = false;
  }
}

import { reactive, ref } from "vue";
import { sendRemoteCommand } from "./useRemoteCommands";

export type RemoteStreamStats = {
  bitrateKbps: number;
  fps: number;
  packetsLost: number;
  rttMs: number;
  framesDecoded: number;
  framesDropped: number;
  iceType: string;
  candidatePair: string;
  regime: string;
};

export const STREAM_LIMITS = {
  bitrate: { min: 500_000, max: 20_000_000, fallback: 4_000_000 },
  maxFpsAndroid: { min: 5, max: 60, fallback: 60 },
  maxFpsIos: { min: 1, max: 30, fallback: 12 },
  maxWidth: { min: 0, max: 1920, fallback: 0, minPositive: 480 },
  iFrameInterval: { min: 1, max: 8, fallback: 2 },
  jpegQuality: { min: 10, max: 90, fallback: 45 },
  jpegScale: { min: 25, max: 100, fallback: 60 },
} as const;

export function clampStreamInt(
  value: unknown,
  min: number,
  max: number,
  fallback: number,
): number {
  const number = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(max, Math.max(min, Math.round(number)));
}

export function clampAndroidWidth(value: unknown): number {
  const width = clampStreamInt(
    value,
    STREAM_LIMITS.maxWidth.min,
    STREAM_LIMITS.maxWidth.max,
    STREAM_LIMITS.maxWidth.fallback,
  );
  if (width > 0 && width < STREAM_LIMITS.maxWidth.minPositive) {
    return STREAM_LIMITS.maxWidth.minPositive;
  }
  return width;
}

export const remoteStreamStats = reactive<RemoteStreamStats>({
  bitrateKbps: 0,
  fps: 0,
  packetsLost: 0,
  rttMs: 0,
  framesDecoded: 0,
  framesDropped: 0,
  iceType: "",
  candidatePair: "",
  regime: "",
});

export function useRemoteStream(platform: string) {
  const ios = platform.toLowerCase() === "ios";
  const fpsLimit = ios ? STREAM_LIMITS.maxFpsIos : STREAM_LIMITS.maxFpsAndroid;
  const adaptive = ref(true);
  const bitrate = ref(STREAM_LIMITS.bitrate.fallback);
  const maxFps = ref(fpsLimit.fallback);
  const maxWidth = ref(STREAM_LIMITS.maxWidth.fallback);
  const iFrameInterval = ref(STREAM_LIMITS.iFrameInterval.fallback);
  const jpegQuality = ref(STREAM_LIMITS.jpegQuality.fallback);
  const jpegScale = ref(STREAM_LIMITS.jpegScale.fallback);
  const loading = ref(false);
  const error = ref("");

  function clampForm(): void {
    bitrate.value = clampStreamInt(
      bitrate.value,
      STREAM_LIMITS.bitrate.min,
      STREAM_LIMITS.bitrate.max,
      STREAM_LIMITS.bitrate.fallback,
    );
    maxFps.value = clampStreamInt(maxFps.value, fpsLimit.min, fpsLimit.max, fpsLimit.fallback);
    maxWidth.value = clampAndroidWidth(maxWidth.value);
    iFrameInterval.value = clampStreamInt(
      iFrameInterval.value,
      STREAM_LIMITS.iFrameInterval.min,
      STREAM_LIMITS.iFrameInterval.max,
      STREAM_LIMITS.iFrameInterval.fallback,
    );
    jpegQuality.value = clampStreamInt(
      jpegQuality.value,
      STREAM_LIMITS.jpegQuality.min,
      STREAM_LIMITS.jpegQuality.max,
      STREAM_LIMITS.jpegQuality.fallback,
    );
    jpegScale.value = clampStreamInt(
      jpegScale.value,
      STREAM_LIMITS.jpegScale.min,
      STREAM_LIMITS.jpegScale.max,
      STREAM_LIMITS.jpegScale.fallback,
    );
  }

  async function apply(): Promise<void> {
    loading.value = true;
    error.value = "";
    clampForm();
    try {
      await sendRemoteCommand(
        {
          t: "stream.configure",
          adaptive: adaptive.value,
          bitrate: bitrate.value,
          max_fps: maxFps.value,
          max_width: maxWidth.value,
          i_frame_interval: iFrameInterval.value,
          jpeg_quality: jpegQuality.value,
          mjpeg_scaling: jpegScale.value,
        },
        120_000,
      );
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause);
      throw cause;
    } finally {
      loading.value = false;
    }
  }

  async function keyframe(): Promise<void> {
    await sendRemoteCommand({ t: "stream.keyframe" });
  }

  async function refreshRunnerStats(): Promise<void> {
    const result = await sendRemoteCommand({ t: "stream.stats" });
    const stats = result.stats as Record<string, unknown> | undefined;
    if (stats?.regime) remoteStreamStats.regime = String(stats.regime);
  }

  return {
    adaptive,
    bitrate,
    maxFps,
    maxWidth,
    iFrameInterval,
    jpegQuality,
    jpegScale,
    fpsLimit,
    loading,
    error,
    apply,
    keyframe,
    refreshRunnerStats,
  };
}

<script setup lang="ts">
/**
 * 画面区：视频/MJPEG + 指针输入。
 * 触控/滚轮逻辑移植自 WebAppFlaskscrcpy DeviceScreen.vue（pointer → touch/scroll emit）。
 */
import { computed, onBeforeUnmount, reactive, ref } from "vue";
import { HevcCanvasPlayer } from "../../composables/remote/hevcPlayback";
import { letterboxRect, mapPointerToDevice } from "../../composables/remote/mapPointerToDevice";

const props = defineProps<{
  useMjpeg: boolean;
  frameUrl: string;
  connecting: boolean;
  failure?: string;
  readonly?: boolean;
  platform?: string;
  /** 设备坐标系宽（live video 优先，见 onDimensions） */
  resolutionWidth?: number;
  resolutionHeight?: number;
  streaming?: boolean;
}>();

const emit = defineEmits<{
  touch: [payload: { x: number; y: number; action: number }];
  scroll: [payload: { x: number; y: number; h: number; v: number }];
  dimensions: [width: number, height: number];
  hevcFallback: [reason: string];
  hevcKeyframe: [];
}>();

const videoRef = ref<HTMLVideoElement | null>(null);
const canvasRef = ref<HTMLCanvasElement | null>(null);
const mjpegReady = ref(false);
let mjpegPaintGen = 0;
let hevcPlayer: HevcCanvasPlayer | null = null;

function ensureHevcPlayer(): HevcCanvasPlayer {
  if (!hevcPlayer) {
    hevcPlayer = new HevcCanvasPlayer({
      canvas: () => canvasRef.value,
      onFrame: (width, height) => {
        mjpegReady.value = true;
        if (width && height) emit("dimensions", width, height);
      },
      onUnsupported: (reason) => emit("hevcFallback", reason),
      onKeyframe: () => emit("hevcKeyframe"),
    });
  }
  return hevcPlayer;
}

function pushHevcConfig(codec: string, description: Uint8Array): void {
  void ensureHevcPlayer().pushConfig(codec, description);
}

function pushHevcPacket(packet: Uint8Array): void {
  ensureHevcPlayer().pushPacket(packet);
}

function closeHevc(): void {
  hevcPlayer?.close();
  hevcPlayer = null;
}

onBeforeUnmount(closeHevc);

const pointerState = reactive({
  dragging: false,
  pointerId: null as number | null,
  last: null as { x: number; y: number } | null,
});
let cachedRect: DOMRect | null = null;

function setMediaStream(stream: MediaStream) {
  const el = videoRef.value;
  if (!el) return;
  if (el.srcObject !== stream) {
    try {
      el.pause?.();
    } catch {
      /* ignore */
    }
    el.srcObject = stream;
  }
  try {
    el.muted = true;
    el.defaultMuted = true;
  } catch {
    /* ignore */
  }
  void el.play?.().catch(() => {
    try {
      el.muted = true;
      void el.play?.().catch(() => undefined);
    } catch {
      /* ignore */
    }
  });
}

function clearMediaStream() {
  if (videoRef.value) videoRef.value.srcObject = null;
}

function getElement(): HTMLVideoElement | HTMLCanvasElement | null {
  if (props.useMjpeg) return canvasRef.value;
  return videoRef.value;
}

function getNativeDimensions(): { w: number; h: number } {
  if (props.useMjpeg) {
    return {
      w: canvasRef.value?.width || 0,
      h: canvasRef.value?.height || 0,
    };
  }
  return {
    w: videoRef.value?.videoWidth || 0,
    h: videoRef.value?.videoHeight || 0,
  };
}

function onLoadedMetadata(event: Event) {
  const v = event.target as HTMLVideoElement;
  if (v?.videoWidth && v.videoHeight) {
    emit("dimensions", v.videoWidth, v.videoHeight);
  }
}

async function applyMjpegFrame(bytes: Uint8Array, mime: string): Promise<boolean> {
  if (!bytes.byteLength) return false;
  const gen = ++mjpegPaintGen;
  try {
    const blob = new Blob([bytes], { type: mime || "image/jpeg" });
    const bitmap = await createImageBitmap(blob);
    if (gen !== mjpegPaintGen) {
      bitmap.close();
      return mjpegReady.value;
    }
    const canvas = canvasRef.value;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) {
      bitmap.close();
      return false;
    }
    if (canvas.width !== bitmap.width) canvas.width = bitmap.width;
    if (canvas.height !== bitmap.height) canvas.height = bitmap.height;
    ctx.drawImage(bitmap, 0, 0);
    const width = bitmap.width;
    const height = bitmap.height;
    bitmap.close();
    mjpegReady.value = true;
    if (width && height) emit("dimensions", width, height);
    return true;
  } catch {
    return false;
  }
}

function clearMjpegFrame() {
  mjpegPaintGen += 1;
  mjpegReady.value = false;
  const canvas = canvasRef.value;
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  ctx?.clearRect(0, 0, canvas.width, canvas.height);
  canvas.width = 0;
  canvas.height = 0;
}

const stageAspectStyle = computed(() => {
  const w = props.resolutionWidth || 0;
  const h = props.resolutionHeight || 0;
  if (w > 0 && h > 0) return { aspectRatio: `${w} / ${h}` };
  return { aspectRatio: props.platform === "ios" ? "390 / 844" : "9 / 16" };
});

const hasLiveFrame = computed(() => {
  if (props.useMjpeg) return mjpegReady.value || Boolean(props.frameUrl);
  const w = props.resolutionWidth || 0;
  const h = props.resolutionHeight || 0;
  return props.streaming && w > 0 && h > 0;
});

const showPlaceholder = computed(() => !hasLiveFrame.value);

const placeholderTitle = computed(() => {
  if (props.connecting) return "正在连接…";
  if (props.failure) return "画面暂不可用";
  if (!props.streaming) return "等待媒体流";
  return "等待首帧";
});

function deviceSize(): { w: number; h: number } {
  const live = getNativeDimensions();
  if (live.w > 0 && live.h > 0) return live;
  return {
    w: props.resolutionWidth || 0,
    h: props.resolutionHeight || 0,
  };
}

function readSurfaceRect(): DOMRect | null {
  const el = getElement();
  if (!el) return null;
  const box = el.getBoundingClientRect();
  if (!box.width || !box.height) return null;
  const { w: natW, h: natH } = deviceSize();
  const fitted = letterboxRect(box, natW, natH);
  return new DOMRect(fitted.left, fitted.top, fitted.width, fitted.height);
}

function mapToDevice(event: PointerEvent | WheelEvent, rectOverride: DOMRect | null = null) {
  const { w, h } = deviceSize();
  const rect = rectOverride || readSurfaceRect();
  if (!rect) return null;
  return mapPointerToDevice(event.clientX, event.clientY, rect, w, h);
}

function handlePointerDown(event: PointerEvent) {
  if (props.readonly || !props.streaming) return;
  if (event.button !== 0) return;
  cachedRect = readSurfaceRect();
  const p = mapToDevice(event, cachedRect);
  if (!p) {
    cachedRect = null;
    return;
  }
  pointerState.dragging = true;
  pointerState.pointerId = event.pointerId;
  pointerState.last = p;
  getElement()?.setPointerCapture?.(event.pointerId);
  emit("touch", { x: p.x, y: p.y, action: 0 });
}

function handlePointerMove(event: PointerEvent) {
  if (!pointerState.dragging || pointerState.pointerId !== event.pointerId) return;
  const p = mapToDevice(event, cachedRect);
  if (!p) return;
  pointerState.last = p;
  emit("touch", { x: p.x, y: p.y, action: 2 });
}

function finishPointer(event: PointerEvent, sendUp: boolean) {
  if (!pointerState.dragging || pointerState.pointerId !== event.pointerId) return;
  const p = mapToDevice(event, cachedRect) || pointerState.last;
  if (sendUp && p) emit("touch", { x: p.x, y: p.y, action: 1 });
  try {
    getElement()?.releasePointerCapture?.(event.pointerId);
  } catch {
    /* ignore */
  }
  pointerState.dragging = false;
  pointerState.pointerId = null;
  pointerState.last = null;
  cachedRect = null;
}

function handlePointerUp(event: PointerEvent) {
  finishPointer(event, true);
}

function cancelPointerInteraction(event: PointerEvent) {
  finishPointer(event, false);
}

let wheelRect: DOMRect | null = null;
let wheelRectExpiresAt = 0;
const WHEEL_RECT_TTL_MS = 250;

function handleWheel(event: WheelEvent) {
  if (props.readonly || !props.streaming) return;
  if (Math.abs(event.deltaX) < 1 && Math.abs(event.deltaY) < 1) return;
  const now = typeof performance !== "undefined" ? performance.now() : Date.now();
  if (!wheelRect || now > wheelRectExpiresAt) {
    wheelRect = readSurfaceRect();
  }
  wheelRectExpiresAt = now + WHEEL_RECT_TTL_MS;
  const p = mapToDevice(event, wheelRect);
  if (!p) return;
  emit("scroll", {
    x: p.x,
    y: p.y,
    h: Math.round(event.deltaX * 12),
    v: Math.round(event.deltaY * 12),
  });
}

defineExpose({
  setMediaStream,
  clearMediaStream,
  clearMjpegFrame,
  applyMjpegFrame,
  pushHevcConfig,
  pushHevcPacket,
  closeHevc,
  getElement,
  getNativeDimensions,
});
</script>

<template>
  <div class="remote-stage" :class="{ readonly }">
    <div class="remote-video-wrap" :style="stageAspectStyle">
      <div v-if="showPlaceholder" class="remote-stage-placeholder" aria-hidden="true">
        <div class="remote-placeholder-screen">
          <span v-if="!failure" class="remote-placeholder-spinner" />
          <p class="remote-placeholder-title">{{ placeholderTitle }}</p>
        </div>
      </div>
      <video
        v-show="!useMjpeg"
        ref="videoRef"
        class="remote-video"
        :class="{ 'remote-video--pending': showPlaceholder }"
        autoplay
        playsinline
        muted
        aria-label="远控设备画面"
        draggable="false"
        @loadedmetadata="onLoadedMetadata"
        @resize="onLoadedMetadata"
        @pointerdown.prevent="handlePointerDown"
        @pointermove.prevent="handlePointerMove"
        @pointerup.prevent="handlePointerUp"
        @pointercancel="cancelPointerInteraction"
        @wheel.prevent="handleWheel"
      />
      <canvas
        v-show="useMjpeg"
        ref="canvasRef"
        class="remote-video"
        :class="{ 'remote-video--pending': showPlaceholder && !mjpegReady }"
        aria-label="远控设备画面"
        draggable="false"
        @pointerdown.prevent="handlePointerDown"
        @pointermove.prevent="handlePointerMove"
        @pointerup.prevent="handlePointerUp"
        @pointercancel="cancelPointerInteraction"
        @wheel.prevent="handleWheel"
      />
    </div>
    <p v-if="readonly" class="remote-readonly">旁观模式 · 只读</p>
  </div>
</template>

<style scoped>
.remote-stage {
  position: relative;
  flex: 1;
  min-height: 280px;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border-radius: var(--radius-md);
  background: var(--remote-stage-bg, #080a0f);
  touch-action: none;
  user-select: none;
}

.remote-video-wrap {
  position: relative;
  height: 100%;
  max-height: 100%;
  max-width: 100%;
  width: auto;
  min-width: 0;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  overflow: hidden;
}

.remote-stage-placeholder {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: flex;
  align-items: stretch;
  justify-content: stretch;
  pointer-events: none;
  border-radius: inherit;
  overflow: hidden;
  background: var(--remote-stage-placeholder-bg);
}

.remote-placeholder-screen {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.65rem;
  padding: clamp(1rem, 8%, 2.5rem) 1rem 12%;
  text-align: center;
}

.remote-placeholder-spinner {
  width: 20px;
  height: 20px;
  border: 2px solid transparent;
  border-top-color: var(--remote-stage-glyph);
  border-right-color: var(--remote-stage-glyph);
  border-radius: 50%;
  animation: remote-placeholder-spin 0.9s linear infinite;
}

.remote-placeholder-title {
  margin: 0;
  font-size: var(--font-size-body);
  color: var(--remote-stage-placeholder-fg);
}

@keyframes remote-placeholder-spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .remote-placeholder-spinner { animation: none; }
}

.remote-video {
  display: block;
  width: 100%;
  height: 100%;
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  cursor: crosshair;
  background: transparent;
}

.remote-video--pending {
  opacity: 0;
  pointer-events: none;
}
.readonly .remote-video {
  cursor: default;
}
.remote-readonly {
  position: absolute;
  top: 0.75rem;
  left: 0.75rem;
  margin: 0;
  padding: 0.35rem 0.6rem;
  border-radius: var(--radius-sm);
  color: var(--remote-stage-placeholder-fg);
  background: var(--remote-stage-placeholder-bg);
  pointer-events: none;
}
</style>

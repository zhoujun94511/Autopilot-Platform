<script setup lang="ts">
/**
 * 画面区：视频/MJPEG + 指针输入。
 * 触控/滚轮逻辑移植自 WebAppFlaskscrcpy DeviceScreen.vue（pointer → touch/scroll emit）。
 */
import { computed, reactive, ref } from "vue";

const props = defineProps<{
  useMjpeg: boolean;
  frameUrl: string;
  connecting: boolean;
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
}>();

const videoRef = ref<HTMLVideoElement | null>(null);
const canvasRef = ref<HTMLCanvasElement | null>(null);
const mjpegReady = ref(false);
let mjpegPaintGen = 0;

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
  if (props.useMjpeg && !mjpegReady.value) return "等待 MJPEG 首帧";
  if (!props.streaming) return "等待媒体流";
  return "等待首帧";
});

const placeholderText = computed(() => {
  if (props.connecting) return "正在创建远控会话并连接 Runner";
  if (props.useMjpeg && !mjpegReady.value) {
    return "Runner 可能正在拉起 WDA，请稍候";
  }
  if (!props.streaming) return "WebRTC 已协商，视频轨即将到达";
  return "设备画面加载中";
});

function clamp(v: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, v));
}

function readSurfaceRect(): DOMRect | null {
  const el = getElement();
  if (!el) return null;
  const box = el.getBoundingClientRect();
  if (!box.width || !box.height) return null;

  const natW = props.resolutionWidth || getNativeDimensions().w;
  const natH = props.resolutionHeight || getNativeDimensions().h;
  if (!natW || !natH) return box;

  const boxAspect = box.width / box.height;
  const contentAspect = natW / natH;
  let w: number;
  let h: number;
  let left: number;
  let top: number;

  if (contentAspect > boxAspect) {
    w = box.width;
    h = box.width / contentAspect;
    left = box.left;
    top = box.top + (box.height - h) / 2;
  } else {
    h = box.height;
    w = box.height * contentAspect;
    top = box.top;
    left = box.left + (box.width - w) / 2;
  }
  return new DOMRect(left, top, w, h);
}

function mapToDevice(event: PointerEvent | WheelEvent, rectOverride: DOMRect | null = null) {
  const w = props.resolutionWidth || getNativeDimensions().w;
  const h = props.resolutionHeight || getNativeDimensions().h;
  if (!w || !h) return null;
  const rect = rectOverride || readSurfaceRect();
  if (!rect) return null;
  const x = clamp((event.clientX - rect.left) / rect.width, 0, 1);
  const y = clamp((event.clientY - rect.top) / rect.height, 0, 1);
  return { x: Math.round(x * w), y: Math.round(y * h) };
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
  getElement,
  getNativeDimensions,
});
</script>

<template>
  <div class="remote-stage" :class="{ readonly }">
    <div class="remote-video-wrap" :style="stageAspectStyle">
      <div v-if="showPlaceholder" class="remote-stage-placeholder" aria-hidden="true">
        <div class="remote-placeholder-screen">
          <div class="remote-placeholder-spinner" aria-hidden="true">
            <span class="remote-placeholder-spinner-ring" />
            <span class="remote-placeholder-spinner-dot" />
          </div>
          <p class="remote-placeholder-title">{{ placeholderTitle }}</p>
          <p class="remote-placeholder-text">{{ placeholderText }}</p>
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
        draggable="false"
        @loadedmetadata="onLoadedMetadata"
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
  border-radius: 12px;
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
  border-radius: 10px;
  overflow: hidden;
  box-shadow:
    0 0 0 1px rgb(255 255 255 / 6%) inset,
    0 12px 32px rgb(0 0 0 / 35%);
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
  background:
    radial-gradient(120% 85% at 50% 12%, rgb(255 255 255 / 6%), transparent 55%),
    linear-gradient(180deg, #161b24 0%, #0e1118 46%, #0a0d12 100%);
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
  position: relative;
  width: 3.25rem;
  height: 3.25rem;
  margin-bottom: 0.35rem;
}

.remote-placeholder-spinner-ring {
  position: absolute;
  inset: 0;
  border: 2px solid rgb(154 168 188 / 22%);
  border-top-color: rgb(154 168 188 / 88%);
  border-radius: 50%;
  animation: remote-placeholder-spin 1.1s linear infinite;
}

.remote-placeholder-spinner-dot {
  position: absolute;
  inset: 36%;
  border-radius: 50%;
  background: rgb(154 168 188 / 55%);
  animation: remote-placeholder-pulse 1.6s ease-in-out infinite;
}

.remote-placeholder-title {
  margin: 0;
  font-size: clamp(0.92rem, 2.2vw, 1.05rem);
  font-weight: 650;
  letter-spacing: 0.01em;
  color: var(--remote-stage-placeholder-fg, #c5cedb);
}

.remote-placeholder-text {
  margin: 0;
  max-width: min(18rem, 88%);
  font-size: 0.8rem;
  line-height: 1.5;
  color: var(--remote-stage-placeholder-muted, #8a96a8);
}

@keyframes remote-placeholder-spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes remote-placeholder-pulse {
  0%,
  100% {
    opacity: 0.45;
    transform: scale(0.92);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
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
  border-radius: 999px;
  color: #dbeafe;
  background: rgb(30 64 175 / 75%);
  backdrop-filter: blur(8px);
  pointer-events: none;
}
</style>

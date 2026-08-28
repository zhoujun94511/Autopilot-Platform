<script setup lang="ts">
import {
  STREAM_LIMITS,
  remoteStreamStats,
  useRemoteStream,
} from "../../composables/remote/useRemoteStream";

const props = defineProps<{
  readonly?: boolean;
  platform: string;
  status: string;
  error?: string;
  transportMode: string;
}>();
const stream = useRemoteStream(props.platform);
const {
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
} = stream;
</script>

<template>
  <section class="remote-tool-panel">
    <header>
      <h3>流质量</h3>
      <button type="button" class="small" @click="stream.refreshRunnerStats">刷新诊断</button>
    </header>
    <div class="remote-stats-grid">
      <span>码率<strong>{{ remoteStreamStats.bitrateKbps.toFixed(0) }} kbps</strong></span>
      <span>帧率<strong>{{ remoteStreamStats.fps.toFixed(1) }}</strong></span>
      <span>RTT<strong>{{ remoteStreamStats.rttMs.toFixed(0) }} ms</strong></span>
      <span>丢包<strong>{{ remoteStreamStats.packetsLost }}</strong></span>
      <span>解码/丢帧<strong>{{ remoteStreamStats.framesDecoded }}/{{ remoteStreamStats.framesDropped }}</strong></span>
      <span>ICE<strong>{{ remoteStreamStats.candidatePair || "等待连接" }}</strong></span>
    </div>
    <label class="remote-switch">
      <input v-model="adaptive" type="checkbox" :disabled="readonly" />
      自适应质量
    </label>
    <template v-if="platform !== 'ios'">
      <label>
        目标码率（{{ STREAM_LIMITS.bitrate.min / 10000 }}万–{{ STREAM_LIMITS.bitrate.max / 10000 }}万 bps）
        <input
          v-model.number="bitrate"
          type="number"
          :min="STREAM_LIMITS.bitrate.min"
          :max="STREAM_LIMITS.bitrate.max"
          step="500000"
        />
      </label>
      <label>
        最大宽度（0=原生，其余 {{ STREAM_LIMITS.maxWidth.minPositive }}–{{ STREAM_LIMITS.maxWidth.max }}）
        <input
          v-model.number="maxWidth"
          type="number"
          :min="STREAM_LIMITS.maxWidth.min"
          :max="STREAM_LIMITS.maxWidth.max"
          step="128"
        />
      </label>
      <label>
        IDR 间隔（{{ STREAM_LIMITS.iFrameInterval.min }}–{{ STREAM_LIMITS.iFrameInterval.max }} 秒）
        <input
          v-model.number="iFrameInterval"
          type="number"
          :min="STREAM_LIMITS.iFrameInterval.min"
          :max="STREAM_LIMITS.iFrameInterval.max"
        />
      </label>
    </template>
    <template v-else>
      <label>
        JPEG 质量（{{ STREAM_LIMITS.jpegQuality.min }}–{{ STREAM_LIMITS.jpegQuality.max }}）
        <input
          v-model.number="jpegQuality"
          type="range"
          :min="STREAM_LIMITS.jpegQuality.min"
          :max="STREAM_LIMITS.jpegQuality.max"
        />
      </label>
      <label>
        画面缩放（{{ STREAM_LIMITS.jpegScale.min }}%–{{ STREAM_LIMITS.jpegScale.max }}%）
        <input
          v-model.number="jpegScale"
          type="range"
          :min="STREAM_LIMITS.jpegScale.min"
          :max="STREAM_LIMITS.jpegScale.max"
        />
      </label>
    </template>
    <label>
      最大 FPS（{{ fpsLimit.min }}–{{ fpsLimit.max }}）
      <input v-model.number="maxFps" type="number" :min="fpsLimit.min" :max="fpsLimit.max" />
    </label>
    <div class="remote-tool-actions">
      <button
        type="button"
        class="small primary"
        :disabled="readonly || loading"
        @click="stream.apply"
      >
        应用参数
      </button>
      <button type="button" class="small" :disabled="readonly" @click="stream.keyframe">
        请求关键帧
      </button>
    </div>
    <dl class="remote-diagnostics">
      <dt>会话状态</dt><dd>{{ status }}</dd>
      <dt>控制通道</dt><dd>{{ transportMode.toUpperCase() }}</dd>
      <dt>质量状态</dt><dd>{{ remoteStreamStats.regime || "浏览器侧" }}</dd>
    </dl>
    <p v-if="remoteStreamStats.iceType === 'relay'" class="ok">当前通过 TURN relay 传输。</p>
    <p v-else-if="remoteStreamStats.iceType" class="muted">
      当前为 {{ remoteStreamStats.iceType }} candidate；跨 NAT 失败时检查 TURN。
    </p>
    <p v-if="remoteStreamStats.rttMs > 500" class="bad">RTT 很高，建议启用自适应或降低清晰度。</p>
    <p v-if="error || props.error" class="bad">{{ error || props.error }}</p>
  </section>
</template>

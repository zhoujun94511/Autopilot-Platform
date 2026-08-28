<script setup lang="ts">
/**
 * 设备展台卡片网格（AUD-2026-12 Wave 5 + UX 对齐）。
 */
import type { Device } from "../api";
import { useAdminStore } from "../stores/adminStore";
import { useExecStore } from "../stores/execution";
import {
  deviceAvailability,
  deviceCardSummary,
  deviceDomId,
  deviceKey,
  deviceNickname,
  displayName,
  normalizePlatform,
  occupyLabel,
  platformBadgeLabel,
  remainingLabel,
  reservationExtraNote,
  runnerSummary,
  udidSummary,
} from "../utils/deviceDisplay";
import { canObserveRemote, canOpenRemote } from "../composables/useRemoteSession";
import StatusPill from "./StatusPill.vue";
import { useAuthStore } from "../stores/auth";

defineProps<{
  groups: Array<{ key: string; label: string; items: Device[] }>;
  showPlatformSections: boolean;
  expandedMeta: Record<string, boolean>;
}>();

const emit = defineEmits<{
  toggleMeta: [key: string];
}>();

const exec = useExecStore();
const admin = useAdminStore();
const auth = useAuthStore();

function currentActor(): { id: string; username: string } {
  return {
    id: String(auth.user?.id || "").trim(),
    username: String(auth.user?.username || "").trim(),
  };
}

function openBusyJob(d: Device) {
  const jid = String(d.busy_job_id || "").trim();
  if (!jid) return;
  exec.onViewJobLog(jid);
}

function hasPrimaryActions(d: Device): boolean {
  const actor = currentActor();
  return Boolean(
    d.can_reserve ||
      d.can_release_reservation ||
      d.can_manage ||
      canObserveRemote(d, actor),
  );
}
</script>

<template>
  <section
    v-for="group in groups"
    :key="group.key"
    class="platform-section"
    :class="{ flat: !showPlatformSections }"
  >
    <header v-if="showPlatformSections" class="platform-section-head">
      <span class="platform-badge" :class="group.key">
        <span class="platform-dot" aria-hidden="true"></span>
        {{ group.label }}
      </span>
      <span class="platform-section-count">{{ group.items.length }} 台</span>
    </header>
    <div class="device-card-grid">
      <article
        v-for="d in group.items"
        :key="deviceKey(d)"
        class="device-card"
        :class="[
          normalizePlatform(d.platform),
          { busy: !!d.busy, maint: !!d.admin_disabled },
        ]"
      >
        <div class="device-card-top">
          <span
            v-if="!showPlatformSections"
            class="platform-badge"
            :class="normalizePlatform(d.platform)"
          >
            <span class="platform-dot" aria-hidden="true"></span>
            {{ platformBadgeLabel(d.platform) }}
          </span>
          <div class="device-card-status">
            <template v-if="deviceAvailability(d).kind === 'maint'">
              <span class="maint-badge">{{ deviceAvailability(d).label }}</span>
            </template>
            <StatusPill
              v-else
              :status="deviceAvailability(d).status"
              :label="deviceAvailability(d).label"
            />
          </div>
        </div>

        <h4 class="device-card-title">
          {{ displayName(d) }}
          <span
            v-if="d.health_note"
            class="health-note"
            role="img"
            :aria-label="`健康提示：${d.health_note}`"
            :title="d.health_note"
          >!</span>
        </h4>

        <p class="device-card-summary">
          <span>{{ deviceCardSummary(d) }}</span>
          <span v-if="deviceNickname(d)" class="owner-tag">{{ deviceNickname(d) }}</span>
          <span v-if="d.owner_username" class="owner-tag">{{ d.owner_username }}</span>
        </p>

        <div class="device-card-id-row" :title="d.udid">
          <span class="meta-label">UDID</span>
          <span class="mono runner-id">{{ udidSummary(d.udid) }}</span>
          <button
            type="button"
            class="icon-copy"
            title="复制 UDID"
            aria-label="复制 UDID"
            @click.stop="admin.copyText(d.udid, '已复制 UDID')"
          >
            复制
          </button>
        </div>

        <div v-if="d.busy && !d.busy_kind && occupyLabel(d)" class="device-card-occupy" :title="occupyLabel(d)">
          {{ occupyLabel(d) }}
        </div>
        <div v-if="d.busy_kind === 'job'" class="device-card-job">
          <span class="job-name" :title="d.busy_job_name">{{ d.busy_job_name || "无名任务" }}</span>
          <span v-if="d.busy_job_id" class="job-id-tag">{{ d.busy_job_id.slice(0, 8) }}</span>
          <StatusPill v-if="d.busy_job_status" :status="d.busy_job_status" />
          <span v-if="d.busy_job_project_id" class="job-id-tag">{{ d.busy_job_project_id }}</span>
          <button
            v-if="d.busy_job_id"
            type="button"
            class="small linkish"
            @click.stop="openBusyJob(d)"
          >
            任务日志
          </button>
        </div>
        <div v-else-if="d.busy_kind === 'reservation'" class="device-card-occupy-block">
          <div class="device-card-job">
            <span class="job-name">{{ d.reservation_username || "用户" }}</span>
            <span v-if="d.reservation_purpose" class="job-id-tag">{{ d.reservation_purpose }}</span>
            <span class="job-id-tag">剩余 {{ remainingLabel(d.reservation_remaining_seconds) }}</span>
          </div>
          <p v-if="reservationExtraNote(d)" class="device-card-occupy-note" :title="d.reservation_reason">
            {{ reservationExtraNote(d) }}
          </p>
        </div>

        <button
          type="button"
          class="meta-toggle"
          :aria-expanded="expandedMeta[deviceKey(d)] ? 'true' : 'false'"
          :aria-controls="deviceDomId(d, 'meta')"
          @click.stop="emit('toggleMeta', deviceKey(d))"
        >
          详情
          <svg
            viewBox="0 0 24 24"
            width="12"
            height="12"
            fill="none"
            stroke="currentColor"
            stroke-width="2.5"
            aria-hidden="true"
            :class="{ open: expandedMeta[deviceKey(d)] }"
          >
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>
        <div
          v-if="expandedMeta[deviceKey(d)]"
          :id="deviceDomId(d, 'meta')"
          class="device-card-meta"
        >
          <div class="meta-row">
            <span class="meta-label">UDID</span>
            <span class="mono break" :title="d.udid">{{ d.udid }}</span>
            <button
              type="button"
              class="icon-copy"
              title="复制 UDID"
              aria-label="复制完整 UDID"
              @click.stop="admin.copyText(d.udid, '已复制 UDID')"
            >
              复制
            </button>
          </div>
          <div class="meta-row">
            <span class="meta-label">Runner</span>
            <span class="mono break" :title="d.runner_id">{{ runnerSummary(d.runner_id) }}</span>
            <button
              type="button"
              class="icon-copy"
              title="复制 Runner ID"
              aria-label="复制 Runner ID"
              @click.stop="admin.copyText(d.runner_id, '已复制 Runner ID')"
            >
              复制
            </button>
          </div>
          <div class="meta-row">
            <span class="meta-label">后端能力</span>
            <span v-if="d.backends?.length" class="backend-chip-row">
              <span v-for="b in d.backends" :key="b" class="backend-chip">{{ b }}</span>
            </span>
            <span v-else class="text-muted-row">—</span>
          </div>
          <div v-if="d.alt_runner_ids?.length" class="meta-row">
            <span class="meta-label">影子节点</span>
            <span class="mono break">{{ d.alt_runner_ids.join(", ") }}</span>
          </div>
        </div>

        <div v-if="hasPrimaryActions(d)" class="device-card-actions">
          <button
            v-if="d.can_reserve"
            type="button"
            class="small primary-action"
            @click="exec.onReserveDevice(d)"
          >
            占用设备
          </button>
          <button
            v-if="d.can_release_reservation"
            type="button"
            class="small"
            @click="exec.onReleaseReservation(d)"
          >
            停止占用
          </button>
          <button
            v-if="canOpenRemote(d, currentActor())"
            type="button"
            class="small primary-action"
            @click="exec.onOpenRemoteDevice(d)"
          >
            远程调试
          </button>
          <button
            v-if="canObserveRemote(d, currentActor())"
            type="button"
            class="small"
            title="只读查看占用者画面，不夺取控制权"
            @click="exec.onObserveRemoteDevice(d)"
          >
            旁观
          </button>
          <button
            v-if="d.can_manage && d.busy_kind === 'job'"
            type="button"
            class="small danger"
            @click="exec.onReleaseDevice(d.udid)"
          >
            强制释放
          </button>
          <button
            v-if="d.can_manage"
            type="button"
            class="small"
            :class="{ warn: !d.admin_disabled }"
            :title="d.admin_disabled ? '恢复该设备参与调度' : '标记维护中，暂不参与调度'"
            @click="exec.onToggleDeviceMaintenance(d.udid, !d.admin_disabled)"
          >
            {{ d.admin_disabled ? "恢复调度" : "停用维护" }}
          </button>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.platform-section {
  margin-bottom: 1.35rem;
}

.platform-section.flat {
  margin-bottom: 0;
}

.platform-section-head {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  margin-bottom: 0.7rem;
}

.platform-section-count {
  font-size: 0.75rem;
  color: var(--muted);
  font-weight: 600;
}

.device-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 0.85rem;
}

@media (max-width: 640px) {
  .device-card-grid {
    grid-template-columns: 1fr;
  }
}

@media (min-width: 641px) and (max-width: 900px) {
  .device-card-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.device-card {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 0.95rem 1rem;
  background: var(--surface-primary);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  box-shadow: var(--panel-shadow);
  border-top: 3px solid var(--border-medium);
  transition: background-color 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
  min-width: 0;
}

.device-card:hover {
  border-color: var(--border-strong);
  background: var(--surface-secondary);
}

.device-card.android {
  border-top-color: var(--ok);
}
.device-card.ios {
  /* 平台色用紫，勿与占用 claimed 青混淆 */
  border-top-color: var(--purple-soft-fg);
}
.device-card.web {
  border-top-color: var(--accent);
}
.device-card.busy {
  background: linear-gradient(
    180deg,
    var(--claimed-soft-bg) 0%,
    var(--surface-primary) 42%
  );
}
.device-card.maint {
  opacity: 0.88;
}

.device-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.device-card-status {
  margin-left: auto;
}

.device-card-title {
  margin: 0.1rem 0 0;
  font-size: 0.98rem;
  font-weight: 700;
  color: var(--text);
  line-height: 1.35;
  word-break: break-word;
  text-wrap: pretty;
}

.device-card-summary {
  margin: 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.35rem;
  font-size: 0.78rem;
  color: var(--text-secondary);
  min-width: 0;
}

.device-card-id-row {
  margin: 0;
  display: flex;
  align-items: baseline;
  gap: 0.4rem;
  font-size: 0.78rem;
  min-width: 0;
}

.meta-label {
  flex-shrink: 0;
  color: var(--muted);
  font-size: 0.7rem;
  font-weight: 650;
  min-width: 3.2rem;
}

.runner-id {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
  flex: 1;
}

.icon-copy {
  appearance: none;
  flex-shrink: 0;
  border: 1px solid var(--line);
  background: var(--btn-bg);
  color: var(--muted);
  font: inherit;
  font-size: 0.68rem;
  font-weight: 650;
  padding: 0.05rem 0.35rem;
  border-radius: 3px;
  cursor: pointer;
  line-height: 1.35;
}

.icon-copy:hover {
  color: var(--text);
  border-color: var(--border-strong);
  background: var(--btn-bg-hover);
}

.owner-tag {
  display: inline-flex;
  padding: 0.05rem 0.35rem;
  border-radius: 999px;
  background: var(--chip-bg);
  border: 1px solid var(--line);
  color: var(--muted);
  font-size: 0.68rem;
}

.device-card-occupy {
  margin: 0.35rem 0 0.15rem;
  font-size: 0.78rem;
  font-weight: 650;
  color: var(--text);
  line-height: 1.35;
}

.device-card-occupy-block {
  display: grid;
  gap: 0.25rem;
}

.device-card-occupy-note {
  margin: 0;
  padding: 0 0.15rem;
  font-size: 0.74rem;
  color: var(--muted);
  line-height: 1.35;
  word-break: break-word;
}

.device-card-job {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.2rem;
  padding: 0.4rem 0.5rem;
  border-radius: var(--radius-sm);
  background: var(--chip-bg);
  border: 1px solid var(--line-soft);
}

.device-card-job .linkish {
  border: none;
  background: none;
  padding: 0 0.15rem;
  color: var(--accent, #2563eb);
  cursor: pointer;
  font: inherit;
  text-decoration: underline;
}

.job-name {
  font-weight: 600;
  font-size: 0.78rem;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text);
}

.job-id-tag {
  font-size: 0.68rem;
  background-color: var(--btn-bg);
  border: 1px solid var(--line);
  padding: 0.05rem 0.25rem;
  border-radius: 3px;
  color: var(--muted);
  font-family: ui-monospace, monospace;
}

.meta-toggle {
  appearance: none;
  border: none;
  background: transparent;
  color: var(--accent-text);
  font: inherit;
  font-size: 0.72rem;
  font-weight: 650;
  padding: 0.25rem 0;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  align-self: flex-start;
}

.meta-toggle svg {
  transition: transform 0.15s ease;
}

.meta-toggle svg.open {
  transform: rotate(180deg);
}

.device-card-meta {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 0.5rem 0.55rem;
  border-radius: var(--radius-sm);
  background: var(--surface-soft);
  border: 1px solid var(--line-soft);
  margin-bottom: 0.15rem;
}

.meta-row {
  display: flex;
  align-items: flex-start;
  gap: 0.45rem;
  font-size: 0.75rem;
  min-width: 0;
}

.mono.break {
  word-break: break-all;
  color: var(--mono);
  flex: 1;
  min-width: 0;
}

.device-card-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  margin-top: auto;
  padding-top: 0.55rem;
  border-top: 1px solid var(--line-soft);
}

.device-card-actions .primary-action {
  font-weight: 650;
}

.device-card-actions .warn,
.device-card-actions button.warn {
  color: var(--warning-soft-fg);
}

.platform-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
  background-color: var(--chip-bg);
  border: 1px solid var(--line);
}

.platform-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
}

.platform-badge.android {
  color: var(--ok-soft-fg);
  background-color: var(--ok-soft-bg);
  border-color: var(--ok-soft-border);
}
.platform-badge.android .platform-dot {
  background-color: var(--ok);
}

.platform-badge.ios {
  color: var(--purple-soft-fg);
  background-color: var(--purple-soft-bg);
  border-color: var(--purple-soft-border);
}
.platform-badge.ios .platform-dot {
  background-color: var(--purple-soft-fg);
}

.platform-badge.web {
  color: var(--info-soft-fg);
  background-color: var(--info-soft-bg);
  border-color: var(--info-soft-border);
}
.platform-badge.web .platform-dot {
  background-color: var(--accent);
}

.platform-badge.other {
  color: var(--muted);
}

.text-muted-row {
  color: var(--muted);
}

.maint-badge {
  display: inline-block;
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  color: var(--warning-soft-fg);
  background: var(--warning-soft-bg);
  border: 1px solid var(--warning-soft-border);
}

.backend-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
}

.backend-chip {
  font-size: 0.7rem;
  font-family: ui-monospace, monospace;
  padding: 0.05rem 0.35rem;
  border-radius: 3px;
  border: 1px solid var(--line);
  background: var(--btn-bg);
  color: var(--muted);
}

.health-note {
  margin-left: 0.25rem;
  color: var(--warning);
  font-weight: 700;
  cursor: help;
}
</style>

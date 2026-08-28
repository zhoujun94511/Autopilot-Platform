<script setup lang="ts">
/**
 * 设备列表表格（AUD-2026-12 Wave 5 + UX 对齐）。
 */
import type { Device } from "../api";
import { useAdminStore } from "../stores/adminStore";
import { useExecStore } from "../stores/execution";
import {
  deviceAvailability,
  deviceKey,
  deviceOsLabel,
  deviceSourceLabel,
  displayName,
  normalizePlatform,
  occupyLabel,
  platformBadgeLabel,
  runnerSummary,
  udidSummary,
} from "../utils/deviceDisplay";
import { canObserveRemote, canOpenRemote } from "../composables/useRemoteSession";
import StatusPill from "./StatusPill.vue";
import { useAuthStore } from "../stores/auth";

defineProps<{
  items: Device[];
  hasDeviceActions: boolean;
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
</script>

<template>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>平台</th>
          <th>型号 / 名称</th>
          <th>系统</th>
          <th>UDID</th>
          <th>状态</th>
          <th>占用摘要</th>
          <th>Runner</th>
          <th>来源 / 所有者</th>
          <th v-if="hasDeviceActions">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="d in items" :key="deviceKey(d)">
          <td>
            <span class="platform-badge" :class="normalizePlatform(d.platform)">
              <span class="platform-dot" aria-hidden="true"></span>
              {{ platformBadgeLabel(d.platform) }}
            </span>
          </td>
          <td class="device-model-cell">
            {{ displayName(d) }}
            <span
              v-if="d.health_note"
              class="health-note"
              role="img"
              :aria-label="`健康提示：${d.health_note}`"
              :title="d.health_note"
            >!</span>
          </td>
          <td class="mono">{{ deviceOsLabel(d) || "-" }}</td>
          <td class="mono udid-cell">
            <span :title="d.udid">{{ udidSummary(d.udid) }}</span>
            <button
              type="button"
              class="icon-copy"
              title="复制 UDID"
              aria-label="复制 UDID"
              @click="admin.copyText(d.udid, '已复制 UDID')"
            >
              复制
            </button>
          </td>
          <td>
            <span v-if="deviceAvailability(d).kind === 'maint'" class="maint-badge">
              {{ deviceAvailability(d).label }}
            </span>
            <StatusPill
              v-else
              :status="deviceAvailability(d).status"
              :label="deviceAvailability(d).label"
            />
          </td>
          <td class="occupy-cell" :title="occupyLabel(d)">
            <template v-if="d.busy">
              <span>{{ occupyLabel(d) || "—" }}</span>
              <button
                v-if="d.busy_kind === 'job' && d.busy_job_id"
                type="button"
                class="small linkish"
                @click="openBusyJob(d)"
              >
                日志
              </button>
            </template>
            <span v-else class="text-muted-row">—</span>
          </td>
          <td class="mono runner-cell">
            <span :title="d.runner_id">{{ runnerSummary(d.runner_id) }}</span>
            <button
              type="button"
              class="icon-copy"
              title="复制 Runner ID"
              aria-label="复制 Runner ID"
              @click="admin.copyText(d.runner_id, '已复制 Runner ID')"
            >
              复制
            </button>
          </td>
          <td>
            {{ deviceSourceLabel(d) }}
            <span v-if="d.owner_username" class="owner-tag">{{ d.owner_username }}</span>
          </td>
          <td v-if="hasDeviceActions">
            <div class="device-actions">
              <button
                v-if="d.can_reserve"
                type="button"
                class="small"
                @click="exec.onReserveDevice(d)"
              >
                占用
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
                class="small"
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
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.occupy-cell {
  max-width: 16rem;
  font-size: 0.78rem;
  line-height: 1.35;
}

.occupy-cell .linkish {
  border: none;
  background: none;
  padding: 0 0.15rem;
  color: var(--accent, #2563eb);
  cursor: pointer;
  font: inherit;
  text-decoration: underline;
}

.udid-cell,
.runner-cell {
  max-width: 180px;
}

.udid-cell span,
.runner-cell span {
  display: inline-block;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.icon-copy {
  appearance: none;
  margin-left: 0.25rem;
  border: 1px solid var(--line);
  background: var(--btn-bg);
  color: var(--muted);
  font: inherit;
  font-size: 0.68rem;
  font-weight: 650;
  padding: 0.05rem 0.3rem;
  border-radius: 3px;
  cursor: pointer;
  vertical-align: middle;
}

.icon-copy:hover {
  color: var(--text);
  border-color: var(--border-strong);
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

.device-model-cell {
  font-weight: 500;
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

.owner-tag {
  display: inline-flex;
  margin-left: 0.35rem;
  padding: 0.05rem 0.35rem;
  border-radius: 999px;
  background: var(--chip-bg);
  border: 1px solid var(--line);
  color: var(--muted);
  font-size: 0.68rem;
}

.device-actions {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
  align-items: center;
}

.device-actions button.warn {
  color: var(--warning-soft-fg);
}

.health-note {
  margin-left: 0.25rem;
  color: var(--warning);
  font-weight: 700;
  cursor: help;
}
</style>

/**
 * 执行域动作。
 * 经 bindExecDeps 注入上下文；useMcStore / useExecStore 转发同名方法。
 */
import { computed, nextTick, watch, type Ref } from "vue";
import {
  api,
  apiErrorMessage,
  parseApiError,
  sessionFetch,
  type AppBuild,
  type Artifact,
  type Device,
  type Job,
  type ManagedRunnerStatus,
  type Runner,
} from "../api";
import {
  fetchAllAppBuilds,
  fetchAllArtifacts,
  fetchAllRunners,
  listJobsPage,
  type Schedule,
} from "../api/opsLists";
import { fetchAllDevices, fetchDeviceBoard } from "../api/devices";
import { confirmDialog, notify, promptDialog, showCopyDialog } from "./useNotify";
import { durationLabel, openReserveDialog } from "./useReserveDialog";
import {
  canObserveRemote,
  canOpenRemote,
  openRemoteDialog,
  openRemoteViewerDialog,
} from "./useRemoteSession";
import { user as sessionUser } from "./mcSessionState";
import { displayName } from "../utils/deviceDisplay";
import type { RefreshScope } from "./mcRefreshScopes";
import * as S from "./mcExecState";
import type { JobFormSnapshot, JobTemplate } from "./mcExecState";
import { isDevicelessPlatform, isWebPlatform, stripDevicelessSubmitPayload } from "./runTargetOptions";
import { filterOrgId } from "./mcProjectsState";

export type ExecDeps = {
  filterProjectId: Ref<string>;
  isPlatformAdmin: { readonly value: boolean };
  listPageSize: number;
  getRefreshSeq: () => number;
  refreshScopes: (scopes: Iterable<RefreshScope>) => Promise<void>;
  runnerCliFallback: () => string;
  appBuildRetentionDays: () => string;
};

let d: ExecDeps;

export function bindExecDeps(deps: ExecDeps): void {
  d = deps;
}

function requireDeps(): ExecDeps {
  if (!d) throw new Error("bindExecDeps() must be called before exec actions");
  return d;
}


export async function refreshSchedules() {
  requireDeps();
  S.schedulesListVersion.value += 1;
}

export async function onCreateSchedule(ev: Event) {
  requireDeps();
  ev.preventDefault();
  S.scheduleMsgOk.value = true;
  const udids = S.scheduleForm.device_udids
    .split(/[,;\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (!S.scheduleForm.artifact_id.trim() && !S.scheduleForm.project_dir.trim()) {
    S.scheduleMsgOk.value = false;
    S.scheduleMsg.value = "请填写制品 ID 或工程目录（至少一项）";
    return;
  }
  const pid =
    S.scheduleForm.project_id.trim() || d.filterProjectId.value.trim();
  if (!pid) {
    S.scheduleMsgOk.value = false;
    S.scheduleMsg.value = "请先选择项目空间（计划必须归属项目）";
    return;
  }
  S.scheduleForm.project_id = pid;

  if (S.scheduleEditId.value) {
    try {
      const patch: Record<string, unknown> = {
          name: S.scheduleForm.name || "Schedule",
          delay_sec: Number(S.scheduleForm.delay_sec) || 0,
          interval_sec: Number(S.scheduleForm.interval_sec) || 0,
          repeat: Number(S.scheduleForm.repeat) || 0,
          stop_on_fail: S.scheduleForm.stop_on_fail,
          webhook_url: S.scheduleForm.webhook_url.trim() || "",
          preferred_runner_id: S.scheduleForm.preferred_runner_id.trim() || null,
          device_udids: udids,
          project_dir: S.scheduleForm.project_dir.trim() || "",
          artifact_id: S.scheduleForm.artifact_id.trim() || null,
          app_build_id: S.scheduleForm.app_build_id.trim() || null,
          project_id: pid,
          platform: S.scheduleForm.platform || "android",
          backend_mode: S.scheduleForm.backend_mode || "auto",
          web_engine:
            (S.scheduleForm.web_engine || "selenium").trim().toLowerCase() ===
            "playwright"
              ? "playwright"
              : "selenium",
          wda_bundle: (S.scheduleForm.wda_bundle || "").trim(),
          parallel: S.scheduleForm.parallel,
          parallel_workers: Number(S.scheduleForm.parallel_workers) || 0,
          entry_paths: [...S.scheduleForm.entry_paths],
      };
      stripDevicelessSubmitPayload(String(patch.platform || ""), patch);
      await api(`/api/v1/schedules/${S.scheduleEditId.value}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      S.scheduleMsg.value = "计划已更新";
      S.scheduleEditId.value = "";
      await refreshSchedules();
    } catch (e) {
      S.scheduleMsgOk.value = false;
      S.scheduleMsg.value = apiErrorMessage(e);
    }
    return;
  }

  const body: Record<string, unknown> = {
    name: S.scheduleForm.name || "Schedule",
    delay_sec: Number(S.scheduleForm.delay_sec) || 0,
    interval_sec: Number(S.scheduleForm.interval_sec) || 0,
    repeat: Number(S.scheduleForm.repeat) || 0,
    stop_on_fail: S.scheduleForm.stop_on_fail,
    platform: S.scheduleForm.platform,
    backend_mode: S.scheduleForm.backend_mode || "auto",
    web_engine:
      (S.scheduleForm.web_engine || "selenium").trim().toLowerCase() === "playwright"
        ? "playwright"
        : "selenium",
    wda_bundle: (S.scheduleForm.wda_bundle || "").trim(),
    project_id: pid,
    webhook_url: S.scheduleForm.webhook_url.trim() || "",
    preferred_runner_id: S.scheduleForm.preferred_runner_id.trim() || null,
    device_udids: udids,
    parallel: S.scheduleForm.parallel,
    parallel_workers: Number(S.scheduleForm.parallel_workers) || 0,
    entry_paths: [...S.scheduleForm.entry_paths],
  };
  if (S.scheduleForm.artifact_id.trim()) body.artifact_id = S.scheduleForm.artifact_id.trim();
  if (S.scheduleForm.app_build_id.trim()) body.app_build_id = S.scheduleForm.app_build_id.trim();
  if (S.scheduleForm.project_dir.trim()) body.project_dir = S.scheduleForm.project_dir.trim();
  stripDevicelessSubmitPayload(S.scheduleForm.platform, body);
  try {
    await api("/api/v1/schedules", { method: "POST", body: JSON.stringify(body) });
    S.scheduleMsg.value = "计划已创建";
    await refreshSchedules();
  } catch (e) {
    S.scheduleMsgOk.value = false;
    S.scheduleMsg.value = apiErrorMessage(e);
  }
}

export function beginEditSchedule(s: Schedule) {
  requireDeps();
  S.scheduleEditId.value = s.id;
  S.scheduleForm.name = s.name || "Schedule";
  S.scheduleForm.delay_sec = Number(s.delay_sec) || 0;
  S.scheduleForm.interval_sec = Number(s.interval_sec) || 0;
  S.scheduleForm.repeat = Number(s.repeat) || 0;
  S.scheduleForm.stop_on_fail = Boolean(s.stop_on_fail);
  S.scheduleForm.artifact_id = s.artifact_id || "";
  S.scheduleForm.app_build_id = s.app_build_id || "";
  S.scheduleForm.project_dir = s.project_dir || "";
  S.scheduleForm.project_id = s.project_id || "";
  S.scheduleForm.platform = s.platform || "android";
  S.scheduleForm.backend_mode = s.backend_mode || "auto";
  S.scheduleForm.web_engine =
    (s as { web_engine?: string }).web_engine?.toLowerCase() === "playwright"
      ? "playwright"
      : "selenium";
  S.scheduleForm.wda_bundle = s.wda_bundle || "";
  S.scheduleForm.device_udids = (s.device_udids || []).join(", ");
  S.scheduleForm.preferred_runner_id = s.preferred_runner_id || "";
  S.scheduleForm.webhook_url = s.webhook_url || "";
  S.scheduleForm.parallel = Boolean(s.parallel);
  S.scheduleForm.parallel_workers = Number(s.parallel_workers) || 0;
  S.scheduleForm.entry_paths = [...((s as { entry_paths?: string[] }).entry_paths || [])];
  S.scheduleMsg.value = `正在编辑计划 ${s.id.slice(0, 8)}…（保存将更新调度参数与制品/工程源）`;
  S.scheduleMsgOk.value = true;
  if (S.scheduleForm.artifact_id.trim()) {
    void loadScheduleArtifactEntries(S.scheduleForm.artifact_id, { preservePaths: true });
  }
}

export function cancelEditSchedule() {
  requireDeps();
  S.scheduleEditId.value = "";
  S.scheduleMsg.value = "";
  S.scheduleForm.entry_paths = [];
  const pid = d.filterProjectId.value.trim();
  if (pid) S.scheduleForm.project_id = pid;
}

export async function onToggleSchedule(id: string, enabled: boolean) {
  requireDeps();
  try {
    await api(`/api/v1/schedules/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled: !enabled }),
    });
    notify("已更新计划启停", "success");
    await refreshSchedules();
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export async function onRunScheduleNow(id: string) {
  requireDeps();
  try {
    await api(`/api/v1/schedules/${id}/run-now`, { method: "POST" });
    notify("已触发立即执行", "success");
    await refreshSchedules();
    await d.refreshScopes(["jobs"]);
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export async function onDeleteSchedule(id: string) {
  requireDeps();
  if (!(await confirmDialog("删除该计划？"))) return;
  try {
    await api(`/api/v1/schedules/${id}`, { method: "DELETE" });
    notify("已删除计划", "success");
    await refreshSchedules();
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export async function refreshRunners() {
  requireDeps();
  try {
    S.runners.value = await fetchAllRunners(undefined);
  } catch {
    S.runners.value = [];
  } finally {
    // 失败时也 bump，避免 RunnersPanel 分页表钉死 stale online 态。
    S.runnersListVersion.value += 1;
  }
}

export async function refreshManagedRunner() {
  requireDeps();
  if (!d.isPlatformAdmin.value) {
    S.managedRunner.value = null;
    return;
  }
  try {
    S.managedRunner.value =
      (await api<ManagedRunnerStatus>("/api/v1/runners/managed?log_lines=30")) || null;
  } catch {
    // 非 admin / 功能关闭时静默；按钮区会根据 null / enabled 隐藏
    S.managedRunner.value = null;
  }
}

export async function refreshDevicesData() {
  requireDeps();
  try {
    const pid = d.filterProjectId.value.trim();
    const [all, board, dispatch] = await Promise.all([
      fetchAllDevices(undefined),
      fetchDeviceBoard(undefined, { summary_only: true }),
      pid ? fetchAllDevices(pid) : Promise.resolve(null),
    ]);
    S.devices.value = all;
    S.dispatchDevices.value = dispatch ?? all;
    S.deviceBoard.value = board ? { summary: board.summary } : null;
  } catch {
    S.devices.value = [];
    S.dispatchDevices.value = [];
    S.deviceBoard.value = null;
  } finally {
    S.devicesVersion.value += 1;
  }
}

export async function refreshJobsList(seq: number) {
  requireDeps();
  const res = await listJobsPage({
    projectId: d.filterProjectId.value.trim() || undefined,
    page: 1,
    pageSize: d.listPageSize,
  });
  if (seq !== d.getRefreshSeq()) return;
  S.jobs.value = res.items;
  S.jobsListVersion.value += 1;
}

export async function refreshReportsList(seq: number) {
  requireDeps();
  if (seq !== d.getRefreshSeq()) return;
  S.reportsListVersion.value += 1;
}

export async function refreshArtifactsList(seq: number) {
  requireDeps();
  const pid = d.filterProjectId.value.trim() || undefined;
  S.artifacts.value = await fetchAllArtifacts(pid);
  if (seq !== d.getRefreshSeq()) return;
  S.artifactsVersion.value += 1;
}

export async function refreshAppBuildsList(seq: number) {
  requireDeps();
  const pid = d.filterProjectId.value.trim() || undefined;
  S.appBuilds.value = await fetchAllAppBuilds(pid);
  if (seq !== d.getRefreshSeq()) return;
  S.appBuildsVersion.value += 1;
}

export async function onCancelJob(id: string) {
  requireDeps();
  if (!(await confirmDialog(`取消任务 ${id.slice(0, 8)}… ?`))) return;
  try {
    await api(`/api/v1/jobs/${id}/cancel`, { method: "POST" });
    notify(`已取消任务 ${id.slice(0, 8)}…`, "success");
    await d.refreshScopes(["jobs", "devices"]);
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export async function onRetryJob(id: string) {
  requireDeps();
  if (!(await confirmDialog(`重试任务 ${id.slice(0, 8)}… ?`))) return;
  try {
    const job = await api<Job>(`/api/v1/jobs/${id}/retry`, { method: "POST" });
    // 列表动作：走 Toast，勿写入批跑创建表单的内联通道
    notify(`已重试 → ${job.id}`, "success");
    await d.refreshScopes(["jobs"]);
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export function canCancel(status: string): boolean {
  requireDeps();
  return ["pending", "claimed", "running"].includes(status);
}

export function canRetry(status: string): boolean {
  requireDeps();
  return ["succeeded", "failed", "cancelled"].includes(status);
}

export function canViewReport(status: string): boolean {
  requireDeps();
  return ["succeeded", "failed", "cancelled"].includes(status);
}

let reportViewSeq = 0;

function revokeReportView() {
  const cur = S.reportView.value;
  if (cur?.url) URL.revokeObjectURL(cur.url);
  S.reportView.value = null;
}

export async function onViewReport(jobId: string) {
  requireDeps();
  if (!jobId) return;
  const seq = ++reportViewSeq;
  try {
    const res = await sessionFetch(`/api/v1/jobs/${jobId}/report`);
    if (!res.ok) throw await parseApiError(res);
    const blob = await res.blob();
    if (seq !== reportViewSeq) return;
    revokeReportView();
    // sandbox 无 allow-same-origin：报告页无法读管理台 localStorage JWT
    S.reportView.value = { jobId, url: URL.createObjectURL(blob) };
  } catch (e) {
    if (seq === reportViewSeq) notify(apiErrorMessage(e), "error");
  }
}

export function closeJobReport() {
  requireDeps();
  reportViewSeq += 1;
  revokeReportView();
}

export function onViewJobLog(jobId: string) {
  requireDeps();
  if (!jobId) return;
  S.logJobId.value = jobId;
}

export function closeJobLog() {
  requireDeps();
  S.logJobId.value = null;
}

export function pickCompare(jobId: string) {
  requireDeps();
  if (!jobId) return;
  if (!S.compareForm.left || S.compareForm.left === jobId) {
    S.compareForm.left = jobId;
  } else if (!S.compareForm.right || S.compareForm.right === jobId) {
    S.compareForm.right = jobId;
  } else {
    S.compareForm.left = S.compareForm.right;
    S.compareForm.right = jobId;
  }
}

export async function onCompareReports(ev: Event) {
  requireDeps();
  ev.preventDefault();
  S.compareMsg.value = "";
  S.compareResult.value = null;
  if (!S.compareForm.left || !S.compareForm.right) {
    S.compareOk.value = false;
    S.compareMsg.value = "请选择两个任务";
    return;
  }
  if (S.compareForm.left === S.compareForm.right) {
    S.compareOk.value = false;
    S.compareMsg.value = "请选择两个不同的任务";
    return;
  }
  try {
    const q = `?left=${encodeURIComponent(S.compareForm.left)}&right=${encodeURIComponent(S.compareForm.right)}`;
    S.compareResult.value = await api(`/api/v1/reports/compare${q}`);
    S.compareOk.value = true;
    S.compareMsg.value = `对比完成：${S.compareResult.value?.verdict || ""}`;
  } catch (e) {
    S.compareOk.value = false;
    S.compareMsg.value = apiErrorMessage(e);
  }
}

export async function onIssueRunnerToken(runnerId: string) {
  requireDeps();
  if (!(await confirmDialog(`为 ${runnerId} 签发/轮换独立 Token？旧令牌将立即失效。`))) return;
  try {
    const out = await api<{ runner_id: string; api_token: string }>(
      `/api/v1/runners/${encodeURIComponent(runnerId)}/token`,
      { method: "POST" },
    );
    await showCopyDialog(out.api_token, {
      title: "Runner Token",
      text: "请立即复制保存（仅显示一次）",
    });
    await d.refreshScopes(["runners"]);
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export async function onDeregisterRunner(runner: Runner) {
  requireDeps();
  const prompt = runner.online
    ? `节点 ${runner.runner_id} 当前在线。注销后如该机 Runner 仍在运行，下次心跳会自动重新注册（需先停机才能彻底移除）。远程节点无法由网页直接杀进程；本机托管请先点「停止」。仍要注销？`
    : `注销离线节点 ${runner.runner_id}？将一并清除其设备记录。`;
  if (!(await confirmDialog(prompt))) return;
  try {
    const out = await api<{ devices_removed: number }>(
      `/api/v1/runners/${encodeURIComponent(runner.runner_id)}`,
      { method: "DELETE" },
    );
    notify(
      `已注销 ${runner.runner_id}（清除 ${out?.devices_removed ?? 0} 台设备记录）`,
      "success",
    );
    await d.refreshScopes(["runners", "devices", "managed-runner"]);
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export async function onStartManagedRunner() {
  requireDeps();
  if (!(await confirmDialog("在 Platform 本机启动托管 Runner 子进程？"))) return;
  try {
    const rid = (S.managedRunner.value?.runner_id || "managed-local").trim();
    const existing = String(
      (S.runners.value || []).find((r) => r.runner_id === rid)?.org_id || "",
    ).trim();
    const oid = existing || filterOrgId.value.trim();
    const out = await api<ManagedRunnerStatus>("/api/v1/runners/managed/start", {
      method: "POST",
      body: oid ? JSON.stringify({ org_id: oid }) : undefined,
    });
    S.managedRunner.value = out;
    notify(
      out?.running
        ? `已启动托管 Runner（PID ${out.pid ?? "-"}，id=${out.runner_id}）`
        : "已请求启动托管 Runner",
      "success",
    );
    await d.refreshScopes(["runners", "devices", "managed-runner"]);
  } catch (e) {
    notify(apiErrorMessage(e), "error");
    await refreshManagedRunner();
  }
}

export async function onStopManagedRunner() {
  requireDeps();
  if (!(await confirmDialog("停止本机托管 Runner 子进程？"))) return;
  try {
    const out = await api<ManagedRunnerStatus>("/api/v1/runners/managed/stop", {
      method: "POST",
    });
    S.managedRunner.value = out;
    notify("已停止本机托管 Runner", "success");
    await d.refreshScopes(["runners", "devices", "managed-runner"]);
  } catch (e) {
    notify(apiErrorMessage(e), "error");
    await refreshManagedRunner();
  }
}

export async function onCopyManagedRunnerCli() {
  requireDeps();
  const cmd = S.managedRunner.value?.cli_command || d.runnerCliFallback();
  await showCopyDialog(cmd, {
    title: "CLI 启动命令",
    text: "远程节点或托管不可用时，可在目标机终端执行：",
  });
}

export async function onReleaseDevice(udid: string) {
  requireDeps();
  if (!(await confirmDialog(`强制释放设备 ${udid} 的占用？`))) return;
  try {
    const out = await api<{ warning?: string }>(
      `/api/v1/devices/${encodeURIComponent(udid)}/release`,
      { method: "POST" },
    );
    if (out?.warning) {
      notify(out.warning, "warn");
    } else {
      notify(`已释放 ${udid}`, "success");
    }
    await d.refreshScopes(["devices", "jobs"]);
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export async function onReserveDevice(device: Device) {
  requireDeps();
  if (!device.id) {
    notify("设备记录缺少 id，无法占用", "error");
    return;
  }
  if (device.busy_kind === "job") {
    notify("设备正被任务占用，请等任务结束或由管理员强制释放后再占用", "error");
    return;
  }
  const form = await openReserveDialog({
    deviceLabel: displayName(device),
    udid: device.udid,
  });
  if (!form) return;
  const { durationMinutes: duration, reason } = form;
  try {
    await api(`/api/v1/devices/${encodeURIComponent(device.id)}/reservations`, {
      method: "POST",
      body: JSON.stringify({ duration_minutes: duration, reason }),
    });
    notify(
      `已占用 ${displayName(device)}，${durationLabel(duration)}后自动释放`,
      "success",
    );
    await d.refreshScopes(["devices"]);
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export async function onReleaseReservation(device: Device) {
  requireDeps();
  const id = String(device.reservation_id || "").trim();
  if (!id) return;
  if (
    !(await confirmDialog(`停止占用设备 ${device.udid}？`, {
      okText: "停止占用",
    }))
  ) {
    return;
  }
  try {
    await api(`/api/v1/device-reservations/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    notify(`已停止占用 ${device.udid}`, "success");
    await d.refreshScopes(["devices"]);
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export async function onOpenRemoteDevice(device: Device) {
  requireDeps();
  if (!device.id) {
    notify("设备记录缺少 id，无法远控", "error");
    return;
  }
  if (device.busy_kind === "job") {
    notify("设备正被任务占用，无法远控", "error");
    return;
  }
  if (!canOpenRemote(device, sessionUser.value)) {
    notify("请先占用设备，再开启远程调试", "error");
    return;
  }
  await openRemoteDialog(device);
  await d.refreshScopes(["devices"]);
}

export async function onObserveRemoteDevice(device: Device) {
  requireDeps();
  if (!device.id) {
    notify("设备记录缺少 id，无法旁观", "error");
    return;
  }
  if (!canObserveRemote(device, sessionUser.value)) {
    if (
      device.can_manage &&
      device.busy_kind === "reservation" &&
      !device.remote_session_active
    ) {
      notify("占用人尚未开启远程调试，暂无法旁观", "warn");
      return;
    }
    notify("仅管理员可旁观他人占用的设备", "error");
    return;
  }
  await openRemoteViewerDialog(device);
}

export async function onToggleDeviceMaintenance(udid: string, disabled: boolean) {
  requireDeps();
  const dev = S.devices.value.find((d) => d.udid === udid);
  let release = false;
  if (disabled) {
    if (dev?.busy) {
      // 停用即腾空：设备在跑任务时，需明确是否中断释放
      if (
        !(await confirmDialog(
          `设备 ${udid} 正在执行任务。停用维护并【中断释放】当前任务？`,
        ))
      ) {
        return;
      }
      release = true;
    } else if (
      !(await confirmDialog(
        `将设备 ${udid} 标记为「维护中」？维护期间不再参与调度。`,
      ))
    ) {
      return;
    }
  } else if (!(await confirmDialog(`恢复设备 ${udid} 参与调度？`))) {
    return;
  }
  try {
    await api(`/api/v1/devices/${encodeURIComponent(udid)}/maintenance`, {
      method: "POST",
      body: JSON.stringify({ disabled, release }),
    });
    const done = disabled ? (release ? "已停用并释放" : "已停用") : "已恢复";
    notify(`${done}设备 ${udid}`, "success");
    await d.refreshScopes(release ? ["devices", "jobs"] : ["devices"]);
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export async function onReclaimStale() {
  requireDeps();
  if (
    !(await confirmDialog("回收超时后仍卡住的任务？进行中的合法任务不会被误杀。", {
      title: "回收超时任务",
      okText: "回收",
    }))
  ) {
    return;
  }
  try {
    const ids = await api<string[]>("/api/v1/jobs/reclaim", { method: "POST" });
    notify(ids?.length ? `已回收 ${ids.length} 个任务` : "无可回收任务", ids?.length ? "success" : "info");
    await d.refreshScopes(["jobs", "devices"]);
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}
export async function onDeleteArtifact(id: string) {
  requireDeps();
  if (!(await confirmDialog(`删除制品 ${id.slice(0, 8)}…？`))) return;
  try {
    await api(`/api/v1/artifacts/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (S.form.artifact_id === id) S.form.artifact_id = "";
    notify("已删除制品", "success");
    await d.refreshScopes(["artifacts"]);
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export async function onDeleteAppBuild(id: string) {
  requireDeps();
  if (!(await confirmDialog(`删除应用资源 ${id.slice(0, 8)}…？`))) return;
  try {
    await api(`/api/v1/app-builds/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (S.form.app_build_id === id) S.form.app_build_id = "";
    notify("已删除应用资源", "success");
    await d.refreshScopes(["app-builds"]);
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export async function onRenameAppBuild(id: string, currentName: string) {
  requireDeps();
  const name = await promptDialog("新显示名称", {
    title: "重命名应用资源",
    defaultValue: currentName || "",
  });
  if (name == null) return;
  const trimmed = name.trim();
  if (!trimmed) {
    notify("名称不能为空", "error");
    return;
  }
  try {
    await api(`/api/v1/app-builds/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ name: trimmed }),
    });
    notify("已重命名应用资源", "success");
    await d.refreshScopes(["app-builds"]);
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export async function onPurgeAppBuilds() {
  requireDeps();
  const days = await promptDialog("清理多少天前的应用资源？", {
    title: "清理应用资源",
    defaultValue: String(d.appBuildRetentionDays() || "90"),
  });
  if (days == null) return;
  const n = Number(days);
  if (!Number.isFinite(n) || n < 1) {
    notify("请输入有效天数", "error");
    return;
  }
  try {
    const out = await api<{ deleted: number; older_than_days: number }>(
      `/api/v1/app-builds/purge?older_than_days=${encodeURIComponent(String(Math.floor(n)))}`,
      { method: "POST" },
    );
    notify(`已清理 ${out.deleted} 个应用资源（≥${out.older_than_days} 天）`, "success");
    await d.refreshScopes(["app-builds"]);
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export async function onPurgeArtifacts() {
  requireDeps();
  const days = await promptDialog("清理多少天前的制品？", {
    title: "清理制品",
    defaultValue: "30",
  });
  if (days == null) return;
  const n = Number(days);
  if (!Number.isFinite(n) || n < 1) {
    notify("请输入有效天数", "error");
    return;
  }
  try {
    const out = await api<{ deleted: number; older_than_days: number }>(
      `/api/v1/artifacts/purge?older_than_days=${encodeURIComponent(String(Math.floor(n)))}`,
      { method: "POST" },
    );
    notify(`已清理 ${out.deleted} 个制品（≥${out.older_than_days} 天）`, "success");
    await d.refreshScopes(["artifacts"]);
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}
export async function onCreateJob(ev: Event) {
  requireDeps();
  ev.preventDefault();
  if (!S.form.artifact_id.trim() && !S.form.project_dir.trim()) {
    S.jobMsgOk.value = false;
    S.jobMsg.value = "请填写制品 ID 或 Runner 本地工程路径（至少一项）";
    return;
  }
  const projectId =
    S.form.project_id.trim() || d.filterProjectId.value.trim();
  if (!projectId) {
    S.jobMsgOk.value = false;
    S.jobMsg.value = "请先选择项目空间（批跑必须归属项目）";
    return;
  }
  S.form.project_id = projectId;
  const udids = S.form.device_udids
    .split(/[,;\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  // 与勾选列表对齐：手填占用中的 UDID 不可绕过
  const byUdid = new Map(
    (S.devices.value || []).map((d) => [d.udid, d] as const),
  );
  const busy = udids.filter((u) => Boolean(byUdid.get(u)?.busy));
  if (busy.length) {
    S.jobMsgOk.value = false;
    S.jobMsg.value = `设备占用中，无法提交：${busy.join(", ")}`;
    return;
  }
  const unknown = udids.filter((u) => !byUdid.has(u));
  if (unknown.length) {
    const ok = await confirmDialog(
      `以下 UDID 不在当前在线设备列表中：\n${unknown.join(", ")}\n\n` +
        "仍可提交，但需对应 Runner 上线且挂载该设备后才能被领取。是否继续？",
    );
    if (!ok) return;
  }
  if (!udids.length && !isDevicelessPlatform(S.form.platform)) {
    const ok = await confirmDialog(
      "未指定设备时，任意空闲 Runner 均可领取该任务（可能在错误节点执行）。是否继续？",
    );
    if (!ok) return;
  }
  if (S.artifactEntries.value.length && !S.form.entry_paths.length) {
    S.jobMsgOk.value = false;
    S.jobMsg.value = "请至少勾选一个用例/套件/计划";
    return;
  }
  // 勾选/手填设备若同属一个 Runner，自动回填亲和
  let preferred = S.form.preferred_runner_id.trim() || null;
  if (udids.length && !preferred) {
    const runners = new Set(
      udids
        .map((u) => (byUdid.get(u)?.runner_id || "").trim())
        .filter(Boolean),
    );
    if (runners.size === 1) preferred = [...runners][0];
  }
  const body: Record<string, unknown> = {
    name: S.form.name || "Suite",
    platform: S.form.platform,
    device_udids: udids,
    preferred_runner_id: preferred,
    parallel: S.form.parallel,
    parallel_workers: Number(S.form.parallel_workers) || 0,
  };
  if (S.form.project_dir.trim()) body.project_dir = S.form.project_dir.trim();
  if (S.form.artifact_id.trim()) body.artifact_id = S.form.artifact_id.trim();
  if (S.form.app_build_id.trim()) body.app_build_id = S.form.app_build_id.trim();
  body.project_id = projectId;
  if (S.form.webhook_url.trim()) body.webhook_url = S.form.webhook_url.trim();
  if (S.form.entry_paths.length) {
    body.entry_paths = [...S.form.entry_paths];
  }
  if ((S.form.backend_mode || "").trim() && S.form.backend_mode !== "auto") {
    body.backend_mode = S.form.backend_mode.trim();
  } else {
    body.backend_mode = "auto";
  }
  if (isWebPlatform(S.form.platform)) {
    const eng = (S.form.web_engine || "selenium").trim().toLowerCase();
    body.web_engine = eng === "playwright" ? "playwright" : "selenium";
  }
  if ((S.form.wda_bundle || "").trim()) body.wda_bundle = S.form.wda_bundle.trim();
  stripDevicelessSubmitPayload(S.form.platform, body);
  S.submitting.value = true;
  try {
    const job = await api<Job>("/api/v1/jobs", {
      method: "POST",
      body: JSON.stringify(body),
    });
    S.jobMsgOk.value = true;
    const warns = (job.warnings || []).filter((w) => String(w || "").trim());
    if (warns.length) {
      S.jobMsg.value = `已创建任务 ${job.id}（有 ${warns.length} 条提示）\n${warns.join("\n")}`;
      for (const w of warns) {
        notify(w, "info");
      }
    } else {
      S.jobMsg.value = `已创建任务 ${job.id}`;
    }
    saveLastJobConfig();
    await d.refreshScopes(["jobs", "devices"]);
  } catch (e) {
    S.jobMsgOk.value = false;
    S.jobMsg.value = apiErrorMessage(e);
  } finally {
    S.submitting.value = false;
  }
}

export async function onUpload(ev: Event) {
  requireDeps();
  ev.preventDefault();
  if (!S.uploadFile.value) {
    S.artMsgOk.value = false;
    S.artMsg.value = "请选择 zip 文件";
    return;
  }
  const pid =
    d.filterProjectId.value.trim() || S.form.project_id.trim();
  if (!pid) {
    S.artMsgOk.value = false;
    S.artMsg.value = "请先选择项目空间（制品必须归属项目）";
    return;
  }
  const fd = new FormData();
  fd.append("file", S.uploadFile.value);
  if (S.uploadName.value.trim()) fd.append("name", S.uploadName.value.trim());
  fd.append("project_id", pid);
  try {
    const art = await api<Artifact>("/api/v1/artifacts", { method: "POST", body: fd });
    S.artMsgOk.value = true;
    S.artMsg.value = `已上传 ${art.id}`;
    S.form.artifact_id = art.id;
    S.uploadFile.value = null;
    await d.refreshScopes(["artifacts"]);
  } catch (e) {
    S.artMsgOk.value = false;
    S.artMsg.value = apiErrorMessage(e);
  }
}

export async function onUploadAppBuild(ev: Event) {
  requireDeps();
  ev.preventDefault();
  if (!S.appBuildUploadFile.value) {
    S.appBuildMsgOk.value = false;
    S.appBuildMsg.value = "请选择 apk/ipa 文件";
    return;
  }
  const pid =
    d.filterProjectId.value.trim() || S.form.project_id.trim();
  if (!pid) {
    S.appBuildMsgOk.value = false;
    S.appBuildMsg.value = "请先选择项目空间（应用包必须归属项目）";
    return;
  }
  const fd = new FormData();
  fd.append("file", S.appBuildUploadFile.value);
  if (S.appBuildUploadName.value.trim()) fd.append("name", S.appBuildUploadName.value.trim());
  fd.append("project_id", pid);
  try {
    const build = await api<AppBuild>("/api/v1/app-builds", { method: "POST", body: fd });
    S.appBuildMsgOk.value = true;
    S.appBuildMsg.value = build.reused
      ? `已存在相同包，复用 ${build.id}${build.version_name ? `（v${build.version_name}）` : ""}`
      : `已上传 ${build.id}${build.version_name ? ` v${build.version_name}` : ""}${
          build.package_id ? ` · ${build.package_id}` : ""
        }`;
    S.form.app_build_id = build.id;
    S.appBuildUploadFile.value = null;
    await d.refreshScopes(["app-builds"]);
  } catch (e) {
    S.appBuildMsgOk.value = false;
    S.appBuildMsg.value = apiErrorMessage(e);
  }
}

export function onFileChange(ev: Event) {
  requireDeps();
  const input = ev.target as HTMLInputElement;
  S.uploadFile.value = input.files && input.files[0] ? input.files[0] : null;
}

export function onAppBuildFileChange(ev: Event) {
  requireDeps();
  const input = ev.target as HTMLInputElement;
  S.appBuildUploadFile.value = input.files && input.files[0] ? input.files[0] : null;
}

// —— 制品条目 / 计划条目 ——
let entriesLoadSeq = 0;
let scheduleEntriesLoadSeq = 0;
let formWatchersInstalled = false;

export function selectArtifact(id: string) {
  S.form.artifact_id = id;
  S.scheduleForm.artifact_id = id;
  void loadArtifactEntries(id);
}

export function selectAppBuild(id: string) {
  S.form.app_build_id = id;
  S.scheduleForm.app_build_id = id;
}

export async function loadArtifactEntries(
  artifactId?: string,
  opts?: { preservePaths?: boolean },
) {
  const aid = (artifactId ?? S.form.artifact_id).trim();
  S.artifactEntriesError.value = "";
  if (!aid) {
    S.artifactEntries.value = [];
    S.form.entry_paths = [];
    return;
  }
  const seq = ++entriesLoadSeq;
  S.artifactEntriesLoading.value = true;
  try {
    const list = await api<{ path: string; kind: string; name: string }[]>(
      `/api/v1/artifacts/${encodeURIComponent(aid)}/entries`,
    );
    if (seq !== entriesLoadSeq) return;
    S.artifactEntries.value = list || [];
    if (opts?.preservePaths) {
      const valid = new Set((list || []).map((e) => e.path));
      S.form.entry_paths = S.form.entry_paths.filter((p) => valid.has(p));
    } else {
      S.form.entry_paths = (list || []).map((e) => e.path);
    }
  } catch (e) {
    if (seq !== entriesLoadSeq) return;
    S.artifactEntries.value = [];
    S.form.entry_paths = [];
    S.artifactEntriesError.value = apiErrorMessage(e);
  } finally {
    if (seq === entriesLoadSeq) S.artifactEntriesLoading.value = false;
  }
}

export function toggleEntryPath(path: string) {
  const set = new Set(S.form.entry_paths);
  if (set.has(path)) set.delete(path);
  else set.add(path);
  S.form.entry_paths = [...set];
}

export function selectAllEntryPaths() {
  S.form.entry_paths = S.artifactEntries.value.map((e) => e.path);
}

export function clearEntryPaths() {
  S.form.entry_paths = [];
}

export async function loadScheduleArtifactEntries(
  artifactId?: string,
  opts?: { preservePaths?: boolean },
) {
  const aid = (artifactId ?? S.scheduleForm.artifact_id).trim();
  S.scheduleArtifactEntriesError.value = "";
  if (!aid) {
    S.scheduleArtifactEntries.value = [];
    if (!opts?.preservePaths) S.scheduleForm.entry_paths = [];
    return;
  }
  const seq = ++scheduleEntriesLoadSeq;
  S.scheduleArtifactEntriesLoading.value = true;
  try {
    const list = await api<{ path: string; kind: string; name: string }[]>(
      `/api/v1/artifacts/${encodeURIComponent(aid)}/entries`,
    );
    if (seq !== scheduleEntriesLoadSeq) return;
    S.scheduleArtifactEntries.value = list || [];
    if (opts?.preservePaths) {
      const valid = new Set((list || []).map((e) => e.path));
      S.scheduleForm.entry_paths = S.scheduleForm.entry_paths.filter((p) => valid.has(p));
    } else {
      S.scheduleForm.entry_paths = (list || []).map((e) => e.path);
    }
  } catch (e) {
    if (seq !== scheduleEntriesLoadSeq) return;
    S.scheduleArtifactEntries.value = [];
    if (!opts?.preservePaths) S.scheduleForm.entry_paths = [];
    S.scheduleArtifactEntriesError.value = apiErrorMessage(e);
  } finally {
    if (seq === scheduleEntriesLoadSeq) S.scheduleArtifactEntriesLoading.value = false;
  }
}

export function toggleScheduleEntryPath(path: string) {
  const set = new Set(S.scheduleForm.entry_paths);
  if (set.has(path)) set.delete(path);
  else set.add(path);
  S.scheduleForm.entry_paths = [...set];
}

export function selectAllScheduleEntryPaths() {
  S.scheduleForm.entry_paths = S.scheduleArtifactEntries.value.map((e) => e.path);
}

export function clearScheduleEntryPaths() {
  S.scheduleForm.entry_paths = [];
}

/** 挂载表单 artifact_id 监听（幂等，由 useMcStore 启动时调用一次）。 */
export function installExecFormWatchers(): void {
  if (formWatchersInstalled) return;
  formWatchersInstalled = true;
  watch(
    () => S.scheduleForm.artifact_id,
    (aid) => {
      const id = String(aid || "").trim();
      if (!id) {
        S.scheduleArtifactEntries.value = [];
        S.scheduleForm.entry_paths = [];
        return;
      }
      void loadScheduleArtifactEntries(id, { preservePaths: Boolean(S.scheduleEditId.value) });
    },
  );
  watch(
    () => S.form.artifact_id,
    (id, prev) => {
      if (id === prev) return;
      void loadArtifactEntries(id);
    },
  );
}

// —— 批跑模板 / 沿用上次 ——
export const hasLastJobConfig = computed(() => Boolean(S.lastJobConfig.value));

function snapshotJobForm(): JobFormSnapshot {
  return {
    name: S.form.name,
    project_dir: S.form.project_dir,
    artifact_id: S.form.artifact_id,
    app_build_id: S.form.app_build_id,
    project_id: S.form.project_id,
    platform: S.form.platform,
    device_udids: S.form.device_udids,
    preferred_runner_id: S.form.preferred_runner_id,
    parallel: S.form.parallel,
    parallel_workers: S.form.parallel_workers,
    webhook_url: S.form.webhook_url,
    backend_mode: S.form.backend_mode,
    web_engine: S.form.web_engine,
    wda_bundle: S.form.wda_bundle,
    entry_paths: [...S.form.entry_paths],
  };
}

function persistJobTemplates() {
  try {
    localStorage.setItem(S.JOB_TEMPLATES_STORAGE_KEY, JSON.stringify(S.jobTemplates.value));
  } catch {
    /* localStorage 不可用时静默降级 */
  }
}

export function saveLastJobConfig() {
  const snap = snapshotJobForm();
  S.lastJobConfig.value = snap;
  try {
    localStorage.setItem(S.JOB_LAST_STORAGE_KEY, JSON.stringify(snap));
  } catch {
    /* 静默降级 */
  }
}

async function applyJobSnapshot(snap: JobFormSnapshot) {
  S.form.name = snap.name ?? "";
  S.form.project_dir = snap.project_dir ?? "";
  S.form.app_build_id = snap.app_build_id ?? "";
  S.form.project_id = snap.project_id ?? "";
  S.form.platform = snap.platform ?? "android";
  S.form.device_udids = snap.device_udids ?? "";
  S.form.preferred_runner_id = snap.preferred_runner_id ?? "";
  S.form.parallel = Boolean(snap.parallel);
  S.form.parallel_workers = Number(snap.parallel_workers) || 0;
  S.form.webhook_url = snap.webhook_url ?? "";
  S.form.backend_mode = snap.backend_mode ?? "auto";
  S.form.web_engine =
    (snap.web_engine || "selenium").toLowerCase() === "playwright"
      ? "playwright"
      : "selenium";
  S.form.wda_bundle = snap.wda_bundle ?? "";
  S.form.entry_paths = [...(snap.entry_paths ?? [])];
  S.form.artifact_id = snap.artifact_id ?? "";
  await nextTick();
  if (S.form.artifact_id.trim()) {
    await loadArtifactEntries(S.form.artifact_id, { preservePaths: true });
  }
}

export async function saveJobAsTemplate() {
  const name = await promptDialog("模板名称", {
    title: "存为批跑模板",
    placeholder: "例如: Android 冒烟",
  });
  if (!name || !name.trim()) return;
  const tn = name.trim();
  const tpl: JobTemplate = {
    name: tn,
    saved_at: new Date().toISOString(),
    form: snapshotJobForm(),
  };
  const idx = S.jobTemplates.value.findIndex((t) => t.name === tn);
  if (idx >= 0) S.jobTemplates.value.splice(idx, 1, tpl);
  else S.jobTemplates.value.push(tpl);
  persistJobTemplates();
  S.jobMsgOk.value = true;
  S.jobMsg.value = `已保存模板「${tn}」`;
}

export async function applyJobTemplate(name: string) {
  const t = S.jobTemplates.value.find((x) => x.name === name);
  if (!t) return;
  await applyJobSnapshot(t.form);
  S.jobMsgOk.value = true;
  S.jobMsg.value = `已载入模板「${name}」`;
}

export function deleteJobTemplate(name: string) {
  const idx = S.jobTemplates.value.findIndex((t) => t.name === name);
  if (idx < 0) return;
  S.jobTemplates.value.splice(idx, 1);
  persistJobTemplates();
}

export async function applyLastJobConfig() {
  if (!S.lastJobConfig.value) return;
  await applyJobSnapshot(S.lastJobConfig.value);
  S.jobMsgOk.value = true;
  S.jobMsg.value = "已沿用上次批跑配置";
}

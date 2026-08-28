/**
 * 执行域共享状态（单一真源）。
 * useMcStore 与 useExecStore 共用同一批 ref，避免双写镜像。
 */
import { reactive, ref } from "vue";
import type { AppBuild, Artifact, Device, Job, ManagedRunnerStatus, Runner } from "../api";

export const runners = ref<Runner[]>([]);
export const managedRunner = ref<ManagedRunnerStatus | null>(null);
export const devices = ref<Device[]>([]);
/** 批跑/计划选机：按当前项目池资格收窄；看板用 `devices` 组织视图。 */
export const dispatchDevices = ref<Device[]>([]);
export const devicesVersion = ref(0);
export const jobsListVersion = ref(0);
export const schedulesListVersion = ref(0);
export const reportsListVersion = ref(0);
export const artifactsVersion = ref(0);
export const appBuildsVersion = ref(0);
export const runnersListVersion = ref(0);

export const deviceBoard = ref<{
  summary: {
    online: number;
    busy: number;
    free: number;
    by_platform: Record<string, { total: number; busy: number; free: number }>;
    by_runner: Record<string, { total: number; busy: number; free: number }>;
  };
} | null>(null);

export const jobs = ref<Job[]>([]);
export const artifacts = ref<Artifact[]>([]);
export const appBuilds = ref<AppBuild[]>([]);
export const jobMsg = ref("");
export const jobMsgOk = ref(true);
export const submitting = ref(false);
export const artMsg = ref("");
export const artMsgOk = ref(true);
export const appBuildMsg = ref("");
export const appBuildMsgOk = ref(true);

export const form = reactive({
  name: "Suite",
  project_dir: "",
  artifact_id: "",
  app_build_id: "",
  project_id: "",
  platform: "android",
  device_udids: "",
  preferred_runner_id: "",
  parallel: false,
  parallel_workers: 0,
  webhook_url: "",
  backend_mode: "auto",
  web_engine: "selenium",
  wda_bundle: "",
  entry_paths: [] as string[],
});

export const artifactEntries = ref<{ path: string; kind: string; name: string }[]>([]);
export const artifactEntriesLoading = ref(false);
export const artifactEntriesError = ref("");

export const uploadName = ref("");
export const uploadFile = ref<File | null>(null);
export const appBuildUploadName = ref("");
export const appBuildUploadFile = ref<File | null>(null);

export const reportFilter = reactive({
  app_build_id: "",
  artifact_id: "",
  platform: "",
});

export const scheduleForm = reactive({
  name: "Nightly",
  delay_sec: 0,
  interval_sec: 0,
  repeat: 1,
  stop_on_fail: false,
  artifact_id: "",
  app_build_id: "",
  project_dir: "",
  project_id: "",
  platform: "android",
  backend_mode: "auto",
  web_engine: "selenium",
  wda_bundle: "",
  device_udids: "",
  preferred_runner_id: "",
  webhook_url: "",
  parallel: false,
  parallel_workers: 0,
  entry_paths: [] as string[],
});
export const scheduleEditId = ref("");
export const scheduleMsg = ref("");
export const scheduleMsgOk = ref(true);

export const compareForm = reactive({ left: "", right: "" });
export const compareResult = ref<{
  left: Record<string, any>;
  right: Record<string, any>;
  delta: Record<string, any>;
  verdict: string;
  same_app_build?: boolean;
  same_artifact?: boolean;
  cases?: {
    available?: boolean;
    new_fail?: Record<string, any>[];
    fixed?: Record<string, any>[];
    still_fail?: Record<string, any>[];
    only_left?: Record<string, any>[];
    only_right?: Record<string, any>[];
    counts?: Record<string, number>;
  };
} | null>(null);
export const compareMsg = ref("");
export const compareOk = ref(true);

export const logJobId = ref<string | null>(null);

/** 任务报告页内预览（blob URL）；关闭时必须 revoke。 */
export type JobReportView = { jobId: string; url: string };
export const reportView = ref<JobReportView | null>(null);

export const scheduleArtifactEntries = ref<{ path: string; kind: string; name: string }[]>([]);
export const scheduleArtifactEntriesLoading = ref(false);
export const scheduleArtifactEntriesError = ref("");

/** 批跑表单快照（localStorage 模板 / 沿用上次） */
export type JobFormSnapshot = {
  name: string;
  project_dir: string;
  artifact_id: string;
  app_build_id: string;
  project_id: string;
  platform: string;
  device_udids: string;
  preferred_runner_id: string;
  parallel: boolean;
  parallel_workers: number;
  webhook_url: string;
  backend_mode: string;
  web_engine: string;
  wda_bundle: string;
  entry_paths: string[];
};
export type JobTemplate = { name: string; saved_at: string; form: JobFormSnapshot };

const JOB_TEMPLATES_KEY = "ap.mc.job.templates.v1";
const JOB_LAST_KEY = "ap.mc.job.last.v1";

function readJobTemplates(): JobTemplate[] {
  try {
    const raw = localStorage.getItem(JOB_TEMPLATES_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

function readLastJobConfig(): JobFormSnapshot | null {
  try {
    const raw = localStorage.getItem(JOB_LAST_KEY);
    return raw ? (JSON.parse(raw) as JobFormSnapshot) : null;
  } catch {
    return null;
  }
}

export const JOB_TEMPLATES_STORAGE_KEY = JOB_TEMPLATES_KEY;
export const JOB_LAST_STORAGE_KEY = JOB_LAST_KEY;
export const jobTemplates = ref<JobTemplate[]>(readJobTemplates());
export const lastJobConfig = ref<JobFormSnapshot | null>(readLastJobConfig());

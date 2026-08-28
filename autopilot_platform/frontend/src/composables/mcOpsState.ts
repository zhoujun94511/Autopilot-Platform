/**
 * 运维摘要 / 配置中心 / 共享 ACL 状态（单一真源）。
 */
import { reactive, ref } from "vue";

export const ops = ref<{
  jobs_by_status: Record<string, number>;
  runners_online: number;
  runners_offline?: number;
  runners_total: number;
  devices_total: number;
  devices_busy: number;
  metrics_path: string;
  counters?: Record<string, number>;
  alert_channel?: string;
  alert_configured?: boolean;
  rag?: {
    active_embedder?: string;
    embedder_name?: string;
    success_count?: number;
    failure_count?: number;
    last_error?: string;
  };
  ai?: {
    tokens?: {
      total_tokens?: number;
      daily_budget?: number;
      budget_remaining?: number;
    };
    degraded?: {
      degraded_cases?: number;
      logical_cases?: number;
      ratio?: number;
    };
  };
} | null>(null);

export const opsConfig = reactive({
  MC_WEBHOOK_URL: "",
  MC_WEBHOOK_SECRET: "",
  MC_DESIGN_WEBHOOK_URL: "",
  MC_DESIGN_WEBHOOK_USE_JOB_URL: "0",
  MC_ALERT_WEBHOOK_URL: "",
  MC_ALERT_CHANNEL: "json",
  MC_ALERT_SECRET: "",
  MC_ALERT_ON_FAILED: "1",
  MC_ALERT_ON_STALE: "1",
  MC_ALERT_ON_RUNNER_OFFLINE: "1",
  MC_ALERT_RUNNER_OFFLINE_COOLDOWN_SEC: "3600",
  MC_ALERT_ON_DEVICE_EMPTY: "1",
  MC_JOB_STALE_SEC: "3600",
  MC_ARTIFACT_RETENTION_DAYS: "30",
  MC_APP_BUILD_RETENTION_DAYS: "90",
  MC_APP_BUILD_MAX_MB: "512",
  MC_APP_BUILD_MAX_COUNT: "100",
  MC_APP_BUILD_MAX_TOTAL_MB: "10240",
  MC_METRICS_ENABLED: "1",
  MC_REQUIRE_JOB_DEVICES: "0",
  MC_REQUIRE_ARTIFACT_MANIFEST: "0",
});

export const opsConfigSources = ref<Record<string, string>>({});
export const opsConfigMsg = ref("");

export const designAiSummary = ref<{
  provider: string;
  model: string;
  base_url: string;
  embedding_model: string;
  rag_embedder: string;
  api_key_configured: boolean;
} | null>(null);

export const shareForm = reactive({
  resource_type: "artifact",
  resource_id: "",
  username: "",
  permission: "read",
});
export const shareMsg = ref("");
export const aclRows = ref<
  {
    id: string;
    resource_type: string;
    resource_id: string;
    username: string;
    permission: string;
  }[]
>([]);

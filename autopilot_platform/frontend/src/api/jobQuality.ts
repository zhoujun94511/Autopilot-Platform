import { api } from "../api";

export type JobQualityTrendDay = {
  day: string;
  total: number;
  succeeded: number;
  failed: number;
  cancelled: number;
  fail_rate: number;
};

export type JobQualitySnapshot = {
  project_id?: string | null;
  days: number;
  jobs_scanned: number;
  status_counts: Record<string, number>;
  terminal_jobs: number;
  failed_jobs: number;
  fail_rate: number;
  trend: JobQualityTrendDay[];
  error_prefix_top: Record<string, number>;
  fail_reason_top: Record<string, number>;
  fail_class_top?: Record<string, number>;
  attribution_top?: Record<string, number>;
  reports_scanned: number;
  failed_steps: number;
  note?: string;
};

export function fetchJobQuality(
  projectId?: string,
  days = 14,
  limit = 80,
): Promise<JobQualitySnapshot> {
  const q = new URLSearchParams();
  if (projectId) q.set("project_id", projectId);
  q.set("days", String(days));
  q.set("limit", String(limit));
  const suffix = q.toString() ? `?${q}` : "";
  return api<JobQualitySnapshot>(`/api/v1/ops/job-quality${suffix}`);
}

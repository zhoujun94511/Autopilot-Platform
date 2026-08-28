/**
 * 运维配置 / 告警 / 共享 ACL 动作。
 */
import type { Ref } from "vue";
import { api, apiErrorMessage } from "../api";
import { fetchAllAclGrants } from "../api/opsLists";
import { confirmDialog, notify } from "./useNotify";
import * as O from "./mcOpsState";
import * as E from "./mcExecState";

export type OpsDeps = {
  isAdmin: () => boolean;
  activeTab: Ref<string>;
};

let d: OpsDeps;

export function bindOpsDeps(deps: OpsDeps): void {
  d = deps;
}

function requireDeps(): OpsDeps {
  if (!d) throw new Error("bindOpsDeps() must be called before ops actions");
  return d;
}

export async function refreshOps() {
  requireDeps();
  if (!d.isAdmin()) {
    O.ops.value = null;
    return;
  }
  try {
    O.ops.value = await api("/api/v1/ops/summary");
  } catch {
    O.ops.value = null;
  }
}

export async function onAlertTest() {
  requireDeps();
  try {
    const out = await api<{ ok: boolean; channel: string }>("/api/v1/ops/alert-test", {
      method: "POST",
    });
    notify(
      out.ok ? `测试已发送（${out.channel}）` : "发送失败，请查平台日志",
      out.ok ? "success" : "error",
      { toast: true },
    );
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export async function refreshOpsConfig() {
  requireDeps();
  if (!d.isAdmin()) return;
  try {
    const out = await api<{
      values: Record<string, string>;
      sources: Record<string, string>;
      secret_keys?: string[];
      secret_configured?: Record<string, boolean>;
      design_ai_summary?: {
        provider?: string;
        model?: string;
        base_url?: string;
        embedding_model?: string;
        rag_embedder?: string;
        api_key_configured?: boolean;
      };
    }>("/api/v1/ops/config");
    const vals = out.values || {};
    const secretKeys = new Set(
      out.secret_keys || ["MC_WEBHOOK_SECRET", "MC_ALERT_SECRET", "AP_AI_API_KEY"],
    );
    for (const k of Object.keys(O.opsConfig) as (keyof typeof O.opsConfig)[]) {
      if (vals[k] == null) continue;
      const raw = String(vals[k]);
      O.opsConfig[k] =
        secretKeys.has(k) && (raw === "********" || raw === "") ? "" : raw;
    }
    O.opsConfigSources.value = out.sources || {};
    const summary = out.design_ai_summary;
    if (summary) {
      O.designAiSummary.value = {
        provider: String(summary.provider || ""),
        model: String(summary.model || ""),
        base_url: String(summary.base_url || ""),
        embedding_model: String(summary.embedding_model || ""),
        rag_embedder: String(summary.rag_embedder || ""),
        api_key_configured: Boolean(summary.api_key_configured),
      };
    } else {
      O.designAiSummary.value = {
        provider: String(vals.AP_AI_PROVIDER || ""),
        model: String(vals.AP_AI_MODEL || ""),
        base_url: String(vals.AP_AI_BASE_URL || ""),
        embedding_model: String(vals.AP_AI_EMBEDDING_MODEL || ""),
        rag_embedder: String(vals.AP_RAG_EMBEDDER || ""),
        api_key_configured: Boolean(out.secret_configured?.AP_AI_API_KEY),
      };
    }
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export async function onSaveOpsConfig(ev: Event) {
  requireDeps();
  ev.preventDefault();
  try {
    await api("/api/v1/ops/config", {
      method: "PUT",
      body: JSON.stringify({ values: { ...O.opsConfig } }),
    });
    O.opsConfigMsg.value = "已保存（立即生效，无需重启）";
    await refreshOpsConfig();
    await refreshOps();
  } catch (e) {
    O.opsConfigMsg.value = apiErrorMessage(e);
  }
}

export async function refreshAcl() {
  requireDeps();
  const rid = O.shareForm.resource_id.trim();
  if (!rid) {
    O.aclRows.value = [];
    return;
  }
  try {
    O.aclRows.value = await fetchAllAclGrants(O.shareForm.resource_type, rid);
  } catch (e) {
    O.aclRows.value = [];
    notify(apiErrorMessage(e), "error");
  }
}

export async function onShare(ev: Event) {
  requireDeps();
  ev.preventDefault();
  try {
    await api("/api/v1/acl", {
      method: "POST",
      body: JSON.stringify({
        resource_type: O.shareForm.resource_type,
        resource_id: O.shareForm.resource_id.trim(),
        username: O.shareForm.username.trim(),
        permission: O.shareForm.permission,
      }),
    });
    O.shareMsg.value = `已分享给 ${O.shareForm.username.trim()}`;
    await refreshAcl();
  } catch (e) {
    O.shareMsg.value = apiErrorMessage(e);
  }
}

export async function onRevokeAcl(aclId: string) {
  requireDeps();
  if (!(await confirmDialog("撤销该分享？"))) return;
  try {
    await api(`/api/v1/acl/${encodeURIComponent(aclId)}`, { method: "DELETE" });
    notify("已撤销分享", "success");
    await refreshAcl();
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export function selectArtifactForShare(id: string) {
  requireDeps();
  E.form.artifact_id = id;
  O.shareForm.resource_id = id;
  O.shareForm.resource_type = "artifact";
  d.activeTab.value = "share";
  void refreshAcl();
}

export function selectAppBuildForShare(id: string) {
  requireDeps();
  E.form.app_build_id = id;
  O.shareForm.resource_id = id;
  O.shareForm.resource_type = "app_build";
  d.activeTab.value = "share";
  void refreshAcl();
}

export function selectJobForShare(id: string) {
  requireDeps();
  O.shareForm.resource_id = id;
  O.shareForm.resource_type = "job";
  d.activeTab.value = "share";
  void refreshAcl();
}

export function selectScheduleForShare(id: string) {
  requireDeps();
  O.shareForm.resource_id = id;
  O.shareForm.resource_type = "schedule";
  d.activeTab.value = "share";
  void refreshAcl();
}

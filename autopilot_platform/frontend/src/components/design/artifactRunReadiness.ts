/** 设计域 → 远程批跑：制品就绪判定。 */
import type { Artifact } from "../../api";
import type { DesignDomainStats } from "../../api/designStats";

export type ArtifactRunReadiness = {
  approvedCount: number;
  artifactCount: number;
  validArtifactCount: number;
  readyToEnqueue: boolean;
  missingArtifact: boolean;
  hint: string;
  ideUploadSteps: string[];
};

export function filterProjectArtifacts(
  artifacts: readonly Artifact[],
  projectId: string,
): Artifact[] {
  const pid = (projectId || "").trim();
  const list = [...(artifacts || [])];
  if (!pid) return list;
  return list.filter((a) => !a.project_id || a.project_id === pid);
}

export function deriveArtifactRunReadiness(
  stats: DesignDomainStats | null,
  artifacts: readonly Artifact[],
  projectId: string,
): ArtifactRunReadiness {
  const approved = Number(stats?.by_review_status?.APPROVED || 0);
  const projectArts = filterProjectArtifacts(artifacts, projectId);
  const valid = projectArts.filter((a) => a.manifest_status === "valid").length;
  const hasAny = projectArts.length > 0;
  const missingArtifact = approved > 0 && !hasAny;
  const readyToEnqueue = approved > 0 && hasAny;

  const ideUploadSteps = [
    "在 AutoPilot IDE 打开对应工程并登录管理台。",
    "菜单：管理台 →「上传工程制品」。",
    "上传成功后，回到本页刷新制品列表。",
    "选择制品与设备 →「入队已通过批跑」。",
  ];

  let hint = "";
  if (approved <= 0) {
    hint = "尚无审核通过的设计用例：请先在「意图用例」完成审核。";
  } else if (missingArtifact) {
    hint =
      "已有审核通过的设计用例，但尚无工程制品。若需远程执行，请先在 IDE 上传制品后再入队。";
  } else if (valid === 0 && hasAny) {
    hint = `已有 ${projectArts.length} 个制品，但校验未通过；建议在 IDE 重新上传完整工程。`;
  } else {
    hint = `${approved} 条设计已通过审核、${valid || projectArts.length} 个可用制品：可选择远程入队。`;
  }

  return {
    approvedCount: approved,
    artifactCount: projectArts.length,
    validArtifactCount: valid,
    readyToEnqueue,
    missingArtifact,
    hint,
    ideUploadSteps,
  };
}

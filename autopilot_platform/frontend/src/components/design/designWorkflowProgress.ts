/**
 * 设计域进度 / 建议下一步（单源）。
 * 主路径：粘贴需求 → 人审 →（可选）IDE 上传制品 → Web 入队批跑。
 */
import type { Artifact } from "../../api";
import type { DesignDomainStats } from "../../api/designStats";
import { deriveArtifactRunReadiness } from "./artifactRunReadiness";

export type DesignProgressStep = "cases" | "run";

export type DesignNextAction = {
  focus: DesignProgressStep;
  done: Set<DesignProgressStep>;
  hasDocs: boolean;
  hasKnowledge: boolean;
  hint: string;
  primary: { tab: string; label: string };
  runReadiness?: ReturnType<typeof deriveArtifactRunReadiness>;
};

export function deriveDesignNextAction(
  s: DesignDomainStats | null,
  opts?: { artifacts?: readonly Artifact[]; projectId?: string },
): DesignNextAction {
  const documents = Number(s?.documents || 0);
  const requirements = Number(s?.requirements || 0);
  const cases = Number(s?.logical_cases || 0);
  const knowledge = Number(s?.knowledge || 0);
  const hasDocs = documents > 0 || requirements > 0;
  const hasCases = cases > 0;
  const hasKnowledge = knowledge > 0;
  const done = new Set<DesignProgressStep>();
  const projectId = (opts?.projectId || s?.project_id || "").trim();
  const runReadiness = deriveArtifactRunReadiness(
    s,
    opts?.artifacts || [],
    projectId,
  );

  if (!hasCases) {
    return {
      focus: "cases",
      done,
      hasDocs,
      hasKnowledge,
      hint: hasDocs
        ? "可在意图用例页粘贴生成，或从需求文档勾选后批量生成，再人工审核。"
        : "直接在意图用例页粘贴需求即可生成草稿；有 Word/PDF 等材料再去需求文档导入。",
      primary: { tab: "design-cases", label: "去生成用例" },
      runReadiness,
    };
  }

  done.add("cases");

  if (runReadiness.approvedCount > 0) {
    if (runReadiness.missingArtifact) {
      return {
        focus: "run",
        done,
        hasDocs,
        hasKnowledge,
        hint: runReadiness.hint,
        primary: { tab: "design-cases", label: "查看入队与上传指引" },
        runReadiness,
      };
    }
    if (runReadiness.readyToEnqueue) {
      done.add("run");
      return {
        focus: "run",
        done,
        hasDocs,
        hasKnowledge,
        hint: runReadiness.hint,
        primary: { tab: "design-cases", label: "去入队批跑" },
        runReadiness,
      };
    }
  }

  return {
    focus: "cases",
    done,
    hasDocs,
    hasKnowledge,
        hint: "在「意图用例」审核草稿并标记通过；通过后按指引上传工程并加入批跑。",
    primary: { tab: "design-cases", label: "去审核用例" },
    runReadiness,
  };
}

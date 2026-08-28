/**
 * 人设默认落地 Tab（PRODUCT_SURFACE_AND_REFERENCE_PLAN §4.3 / B2）。
 * 仅在仍停在默认 dashboard 时用于轻量纠偏；不覆盖深链。
 */
export type PersonaLandingInput = {
  isPlatformAdmin: boolean;
  /** 当前组织或任一组织的 owner/admin */
  isOrgAdmin: boolean;
  hasProjectSelected: boolean;
};

export function resolvePersonaLandingTab(input: PersonaLandingInput): string {
  if (input.isPlatformAdmin) return "dashboard";
  if (input.isOrgAdmin) return "projects";
  if (input.hasProjectSelected) return "design-dashboard";
  return "projects";
}

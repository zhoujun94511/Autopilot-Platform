import { beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";
import { fetchAllOrgs, type Organization } from "../api/orgs";
import { fetchAllProjects, type Project } from "../api/projects";
import { bindProjectsDeps, refreshOrgs, refreshProjects, selectOrg, selectProject } from "./mcProjectsActions";
import { filterOrgId, filterProjectId, orgs, projects } from "./mcProjectsState";

vi.mock("../api/orgs", () => ({ fetchAllOrgs: vi.fn() }));
vi.mock("../api/projects", () => ({ fetchAllProjects: vi.fn() }));
vi.mock("./useNotify", () => ({ notify: vi.fn() }));

const alpha = { id: "alpha-case", org_id: "alpha", name: "Alpha" };
const beta = { id: "beta-case", org_id: "beta", name: "Beta" };

describe("organization and project selection", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    localStorage.clear();
    bindProjectsDeps({
      user: ref({ id: "user", username: "user", role: "operator" }),
      activeTab: ref("jobs"),
      refreshForTab: vi.fn(),
    });
    filterOrgId.value = "alpha";
    filterProjectId.value = alpha.id;
    projects.value = [alpha];
    orgs.value = [{ id: "alpha" } as Organization];
  });

  it("clears the old project on switch and discards an out-of-order response", async () => {
    let resolveAlpha!: (rows: Project[]) => void;
    vi.mocked(fetchAllProjects).mockReturnValueOnce(
      new Promise<Project[]>((resolve) => { resolveAlpha = resolve; }),
    ).mockResolvedValueOnce([beta]);

    const alphaRequest = refreshProjects();
    selectOrg("beta");
    expect(filterProjectId.value).toBe("");
    expect(projects.value).toEqual([]);
    await Promise.resolve();
    selectProject(beta.id);

    resolveAlpha([alpha]);
    await alphaRequest;
    expect(filterOrgId.value).toBe("beta");
    expect(filterProjectId.value).toBe(beta.id);
    expect(projects.value).toEqual([beta]);
  });

  it("retains the selection when a request for the current workspace fails", async () => {
    vi.mocked(fetchAllOrgs).mockRejectedValueOnce(new Error("outage"));
    vi.mocked(fetchAllProjects).mockRejectedValueOnce(new Error("outage"));

    await Promise.all([refreshOrgs(), refreshProjects()]);

    expect(filterOrgId.value).toBe("alpha");
    expect(filterProjectId.value).toBe(alpha.id);
    expect(projects.value).toEqual([alpha]);
  });
});

import { afterEach, expect, it, vi } from "vitest";
import { effectScope, nextTick, ref } from "vue";
import * as Api from "../api";
import * as lists from "../api/opsLists";
import * as ExecActions from "./mcExecActions";
import { appBuilds, artifacts } from "./mcExecState";
import { bindPollingDeps, refreshScopes, registerJobsPage, startPolling, stopPolling } from "./mcPolling";

afterEach(() => {
  stopPolling();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("reschedules a directly opened Jobs page when the loaded list changes activity", async () => {
  const active = ref(false);
  const page = effectScope();
  const setInterval = vi.spyOn(window, "setInterval");
  const clearInterval = vi.spyOn(window, "clearInterval");
  bindPollingDeps({
    loggedIn: ref(true),
    sessionHydrating: ref(false),
    pageVisible: ref(true),
    activeTab: ref("jobs"),
    error: ref(""),
    isPlatformAdmin: ref(false),
    getRouter: () => null,
    onUnauthorized: vi.fn(),
    refreshOrgs: vi.fn(),
    refreshProjects: vi.fn(),
  });

  try {
    startPolling();
    expect(setInterval).toHaveBeenLastCalledWith(expect.any(Function), 45_000);
    page.run(() => registerJobsPage({
      refresh: vi.fn(),
      hasActiveJobs: () => active.value,
      isCreateOpen: () => false,
    }));

    const idleTimer = setInterval.mock.results[0].value;
    active.value = true;
    await nextTick();
    expect(clearInterval).toHaveBeenLastCalledWith(idleTimer);
    expect(setInterval).toHaveBeenLastCalledWith(expect.any(Function), 10_000);

    active.value = false;
    await nextTick();
    expect(setInterval).toHaveBeenLastCalledWith(expect.any(Function), 45_000);

    page.stop();
    setInterval.mockClear();
    active.value = true;
    await nextTick();
    expect(setInterval).not.toHaveBeenCalled();
  } finally {
    page.stop();
  }
});

it("uses one health request per refresh and reloads execution resources once after a reboot", async () => {
  vi.spyOn(Api, "ensureFreshSession").mockResolvedValue(true);
  const loadRunners = vi.spyOn(ExecActions, "refreshRunners").mockResolvedValue(undefined);
  const loadDevices = vi.spyOn(ExecActions, "refreshDevicesData").mockResolvedValue(undefined);
  const loadManagedRunner = vi.spyOn(ExecActions, "refreshManagedRunner").mockResolvedValue(undefined);
  let bootId = "boot-1";
  const fetchHealth = vi.fn(async () => ({
    json: async () => ({ status: "ok", platform_boot_id: bootId }),
  }));
  vi.stubGlobal("fetch", fetchHealth);
  bindPollingDeps({
    loggedIn: ref(true),
    sessionHydrating: ref(false),
    pageVisible: ref(true),
    activeTab: ref("dashboard"),
    error: ref(""),
    isPlatformAdmin: ref(false),
    getRouter: () => null,
    onUnauthorized: vi.fn(),
    refreshOrgs: vi.fn(),
    refreshProjects: vi.fn(),
  });

  await refreshScopes(["health", "runners"]);
  expect(fetchHealth).toHaveBeenCalledExactlyOnceWith("/health");
  expect(loadRunners).toHaveBeenCalledOnce();
  expect(loadManagedRunner).not.toHaveBeenCalled();

  bootId = "boot-2";
  await refreshScopes(["health", "runners"]);
  expect(fetchHealth).toHaveBeenCalledTimes(2);
  expect(loadRunners).toHaveBeenCalledTimes(2);
  expect(loadDevices).toHaveBeenCalledOnce();
  expect(loadManagedRunner).toHaveBeenCalledOnce();
  await refreshScopes(["health"]);
  expect(fetchHealth).toHaveBeenCalledTimes(3);
  expect(loadRunners).toHaveBeenCalledTimes(2);
  expect(loadDevices).toHaveBeenCalledOnce();
  expect(loadManagedRunner).toHaveBeenCalledOnce();
});

it("applies independent artifact and app results across a jobs-only poll", async () => {
  vi.spyOn(Api, "ensureFreshSession").mockResolvedValue(true);
  vi.stubGlobal("fetch", vi.fn(async () => ({ json: async () => ({ status: "ok" }) })));
  bindPollingDeps({
    loggedIn: ref(true),
    sessionHydrating: ref(false),
    pageVisible: ref(true),
    activeTab: ref("dashboard"),
    error: ref(""),
    isPlatformAdmin: ref(false),
    getRouter: () => null,
    onUnauthorized: vi.fn(),
    refreshOrgs: vi.fn(),
    refreshProjects: vi.fn(),
  });
  ExecActions.bindExecDeps({
    filterProjectId: ref("project"),
    isPlatformAdmin: ref(false),
    listPageSize: 50,
    refreshScopes,
    runnerCliFallback: () => "",
    appBuildRetentionDays: () => "90",
  });

  let resolveArtifacts!: (rows: Api.Artifact[]) => void;
  let resolveApps!: (rows: Api.AppBuild[]) => void;
  const artifactResponse = new Promise<Api.Artifact[]>((resolve) => { resolveArtifacts = resolve; });
  const appResponse = new Promise<Api.AppBuild[]>((resolve) => { resolveApps = resolve; });
  const loadArtifacts = vi.spyOn(lists, "fetchAllArtifacts").mockReturnValue(artifactResponse);
  const loadApps = vi.spyOn(lists, "fetchAllAppBuilds").mockReturnValue(appResponse);
  vi.spyOn(lists, "listJobsPage").mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 });
  const updatingTargets = refreshScopes(["artifacts", "app-builds"]);
  await vi.waitFor(() => expect(loadArtifacts).toHaveBeenCalledExactlyOnceWith("project"));
  expect(loadApps).toHaveBeenCalledExactlyOnceWith("project");
  await refreshScopes(["jobs"]);
  resolveArtifacts([{ id: "artifact" } as Api.Artifact]);
  resolveApps([{ id: "app" } as Api.AppBuild]);
  await updatingTargets;
  expect(artifacts.value.map(({ id }) => id)).toEqual(["artifact"]);
  expect(appBuilds.value.map(({ id }) => id)).toEqual(["app"]);
});

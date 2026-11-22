import { afterEach, expect, it, vi } from "vitest";
import { beginAuthSession, clearSession, type Device } from "../api";
import * as lists from "../api/opsLists";
import { refreshAcl } from "./mcOpsActions";
import { aclRows, shareForm } from "./mcOpsState";
import { jwt, user } from "./mcSessionState";
import { closeRemoteDialog, openRemoteDialog, remoteDialogState } from "./useRemoteSession";
import "./platformRuntime";

function enterSession(id: string) {
  beginAuthSession();
  jwt.value = "test-access";
  user.value = { id, username: id, role: "admin" };
}

function grant(id: string, resourceId: string, username: string) {
  return { id, resource_type: "artifact", resource_id: resourceId, username, permission: "read" };
}

function pendingAcl() {
  let resolveRows!: (rows: lists.AclGrant[]) => void;
  const promise = new Promise<lists.AclGrant[]>((resolve) => { resolveRows = resolve; });
  return { promise, resolve: resolveRows };
}

afterEach(() => {
  clearSession();
  vi.restoreAllMocks();
});

it("discards a late ACL response when the selected resource changes", async () => {
  enterSession("operator");
  const first = grant("first-acl", "first-resource", "first-member");
  const second = grant("second-acl", "second-resource", "second-member");
  const late = pendingAcl();
  vi.spyOn(lists, "fetchAllAclGrants")
    .mockResolvedValueOnce([first])
    .mockReturnValueOnce(late.promise)
    .mockResolvedValueOnce([second]);

  shareForm.resource_id = first.resource_id;
  await refreshAcl();
  expect(aclRows.value).toEqual([first]);
  const loadingFirst = refreshAcl();

  shareForm.resource_id = second.resource_id;
  expect(aclRows.value).toEqual([]);
  await refreshAcl();
  late.resolve([first]);
  await loadingFirst;
  expect(aclRows.value).toEqual([second]);
});

it("expires shared data and closes open remote state before another account signs in", async () => {
  enterSession("first-operator");
  const first = grant("first-acl", "resource", "first-member");
  const late = pendingAcl();
  vi.spyOn(lists, "fetchAllAclGrants")
    .mockResolvedValueOnce([first])
    .mockReturnValueOnce(late.promise);
  shareForm.resource_id = first.resource_id;
  shareForm.username = first.username;
  await refreshAcl();
  const loadingFirst = refreshAcl();
  const remoteFinished = openRemoteDialog({ id: "test-device" } as Device);
  expect(remoteDialogState.value).not.toBeNull();

  clearSession();
  await remoteFinished;
  expect(remoteDialogState.value).toBeNull();
  expect(shareForm.resource_id).toBe("");
  expect(shareForm.username).toBe("");
  expect(aclRows.value).toEqual([]);

  enterSession("second-operator");
  shareForm.resource_id = first.resource_id;
  late.resolve([first]);
  await loadingFirst;
  expect(aclRows.value).toEqual([]);
  const newRemote = openRemoteDialog({ id: "another-device" } as Device);
  closeRemoteDialog();
  await newRemote;
});

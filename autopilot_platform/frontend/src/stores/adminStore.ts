/**
 * 管理域 Pinia Store：与 useMcStore 共用 mcAdminState + mcAdminActions。
 */
import { defineStore } from "pinia";
import * as admin from "../composables/mcAdminState";
import * as AdminActions from "../composables/mcAdminActions";

export const useAdminStore = defineStore("admin", () => {
  return {
    usersListVersion: admin.usersListVersion,
    auditsListVersion: admin.auditsListVersion,
    auditFilter: admin.auditFilter,
    userForm: admin.userForm,
    userMsg: admin.userMsg,
    userMsgOk: admin.userMsgOk,
    refreshAudits: AdminActions.refreshAudits,
    refreshUsers: AdminActions.refreshUsers,
    onCreateUser: AdminActions.onCreateUser,
    onToggleUserDisabled: AdminActions.onToggleUserDisabled,
    onResetUserPassword: AdminActions.onResetUserPassword,
    onDeleteUser: AdminActions.onDeleteUser,
    copyText: AdminActions.copyText,
  };
});

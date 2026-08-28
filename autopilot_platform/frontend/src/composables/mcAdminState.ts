/**
 * 管理域共享状态（审计 / 用户）。
 */
import { reactive, ref } from "vue";

export const usersListVersion = ref(0);
export const auditsListVersion = ref(0);
export const auditFilter = reactive({ action: "", actor: "" });
export const userForm = reactive({
  username: "",
  password: "",
  duty: "org_member",
});
export const userMsg = ref("");
export const userMsgOk = ref(true);

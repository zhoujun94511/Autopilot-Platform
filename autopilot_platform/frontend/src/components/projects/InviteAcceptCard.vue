<script setup lang="ts">
import { onMounted, ref } from "vue";
import {
  acceptInvite,
  previewInvite,
  registerViaInvite,
  type ProjectInvitePreview,
} from "../../api/projectInvites";
import { apiErrorMessage } from "../../api";
import { storeToRefs } from "pinia";
import { useShellStore } from "../../stores/shellStore";
import { useAuthStore } from "../../stores/auth";
import { useProjectsStore } from "../../stores/projectsStore";

const shell = useShellStore();
const auth = useAuthStore();
const projectsStore = useProjectsStore();
const { jwt } = storeToRefs(auth);

const token = ref("");
const preview = ref<ProjectInvitePreview | null>(null);
const error = ref("");
const msg = ref("");
const busy = ref(false);
const regUser = ref("");
const regPass = ref("");

function readTokenFromUrl(): string {
  const q = new URLSearchParams(window.location.search);
  return (q.get("invite") || "").trim();
}

function clearInviteQuery() {
  const url = new URL(window.location.href);
  if (!url.searchParams.has("invite")) return;
  url.searchParams.delete("invite");
  window.history.replaceState({}, "", url.pathname + url.search + url.hash);
}

async function loadPreview() {
  token.value = readTokenFromUrl();
  if (!token.value) return;
  error.value = "";
  try {
    preview.value = await previewInvite(token.value);
  } catch (e) {
    error.value = apiErrorMessage(e);
    preview.value = null;
  }
}

async function applySession(pair: {
  access_token: string;
  refresh_token?: string;
  user: { id: string; username: string; role: string };
}) {
  await auth.applyAuthSession(pair);
  clearInviteQuery();
  shell.activeTab = "projects";
  if (preview.value?.project_id) {
    projectsStore.selectProject(preview.value.project_id);
  }
}

async function onAcceptLoggedIn() {
  if (!token.value) return;
  busy.value = true;
  error.value = "";
  msg.value = "";
  try {
    const out = await acceptInvite(token.value);
    msg.value = `已加入项目 ${out.project_id}（${out.role}）`;
    clearInviteQuery();
    await shell.refreshForTab("projects");
    projectsStore.selectProject(out.project_id);
    shell.activeTab = "projects";
  } catch (e) {
    error.value = apiErrorMessage(e);
  } finally {
    busy.value = false;
  }
}

async function onRegister() {
  if (!token.value) return;
  if (!regUser.value.trim() || regPass.value.length < 8) {
    error.value = "请填写用户名，密码至少 8 位（须含字母和数字）";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    const out = await registerViaInvite(token.value, regUser.value.trim(), regPass.value);
    msg.value = `注册成功并已加入 ${preview.value?.project_id || "项目"}`;
    await applySession(out);
  } catch (e) {
    error.value = apiErrorMessage(e);
  } finally {
    busy.value = false;
  }
}

onMounted(() => {
  void loadPreview();
});
</script>

<template>
  <div v-if="token" class="invite-accept">
    <h3>项目邀请</h3>
    <div v-if="preview" class="preview">
      <p>
        项目 <strong>{{ preview.project_name || preview.project_id }}</strong>
        · 角色 <code>{{ preview.role }}</code>
      </p>
      <p v-if="preview.label" class="muted">{{ preview.label }}</p>
      <p v-if="!preview.valid" class="bad">{{ preview.detail || "邀请无效" }}</p>
    </div>
    <p v-if="error" class="bad">{{ error }}</p>
    <p v-if="msg" class="ok">{{ msg }}</p>

    <template v-if="preview?.valid">
      <div v-if="jwt" class="actions">
        <button type="button" class="primary" :disabled="busy" @click="onAcceptLoggedIn">
          接受邀请并加入项目
        </button>
      </div>
      <div v-else class="register-box">
        <p class="muted">已有账号？先登录，再点接受。或在此自助注册：</p>
        <label>
          新用户名
          <input v-model="regUser" autocomplete="username" />
        </label>
        <label>
          密码（≥6 位）
          <input v-model="regPass" type="password" autocomplete="new-password" />
        </label>
        <button type="button" class="primary" :disabled="busy" @click="onRegister">
          注册并加入
        </button>
        <p class="muted">密码至少 8 位，须同时含字母和数字。</p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.invite-accept {
  margin-top: 1.25rem;
  padding-top: 1.25rem;
  border-top: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}
.invite-accept h3 {
  margin: 0;
  font-size: 1rem;
}
.muted {
  color: var(--muted);
  font-size: 0.85rem;
}
.bad {
  color: var(--bad);
  font-size: 0.85rem;
}
.ok {
  color: var(--ok);
  font-size: 0.85rem;
}
.register-box {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}
.register-box label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.85rem;
}
.register-box input {
  padding: 0.45rem 0.6rem;
  border-radius: 6px;
  border: 1px solid var(--line);
  background: var(--surface-soft);
  color: var(--text);
}
</style>

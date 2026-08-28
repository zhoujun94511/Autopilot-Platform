<script setup lang="ts">
import { onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { getPlatformBootstrap } from "../api/bootstrap";
import { useAuthStore } from "../stores/auth";
import InviteAcceptCard from "./projects/InviteAcceptCard.vue";

const auth = useAuthStore();
const { loginForm, loginError, oidcEnabled, samlEnabled } = storeToRefs(auth);
const insecureDefaults = ref(false);
const submitting = ref(false);

onMounted(() => {
  insecureDefaults.value = Boolean(getPlatformBootstrap().flags?.insecure_defaults);
});

async function onSubmit(ev: Event) {
  submitting.value = true;
  try {
    await auth.onLogin(ev);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="login-panel">
    <header class="login-header">
      <h2>登录</h2>
      <p class="login-sub">使用组织账号继续</p>
    </header>

    <form class="login-form" @submit="onSubmit">
      <div class="form-group">
        <label for="username">用户名</label>
        <input
          id="username"
          v-model="loginForm.username"
          required
          placeholder="组织账号"
          autocomplete="username"
          autofocus
        />
      </div>

      <div class="form-group">
        <label for="password">密码</label>
        <input
          id="password"
          v-model="loginForm.password"
          type="password"
          required
          placeholder="密码"
          autocomplete="current-password"
        />
      </div>

      <p v-if="loginError" class="msg bad login-error-msg" role="alert">{{ loginError }}</p>

      <button type="submit" class="btn-login-submit" :disabled="submitting">
        {{ submitting ? "正在登录…" : "登录" }}
      </button>
    </form>

    <div v-if="oidcEnabled || samlEnabled" class="sso-divider">
      <span class="divider-line"></span>
      <span class="divider-text">或使用企业 SSO</span>
      <span class="divider-line"></span>
    </div>

    <div v-if="oidcEnabled || samlEnabled" class="sso-buttons-group">
      <button
        v-if="oidcEnabled"
        type="button"
        class="btn-sso"
        @click="auth.onOidcLogin"
      >
        企业 OIDC
      </button>
      <button
        v-if="samlEnabled"
        type="button"
        class="btn-sso"
        @click="auth.onSamlLogin"
      >
        企业 SAML 2.0
      </button>
    </div>

    <p
      v-if="insecureDefaults"
      class="insecure-defaults-hint"
      role="status"
      title="请使用正式环境配置，不要把开发默认密钥用于生产"
    >
      本机开发模式，请勿用于生产环境
    </p>

    <InviteAcceptCard />
  </div>
</template>

<style scoped>
.login-panel {
  width: 100%;
  display: flex;
  flex-direction: column;
}

.login-header {
  margin-bottom: 1.65rem;
}

.login-header h2 {
  margin: 0;
  font-size: 1.35rem;
  font-weight: 650;
  letter-spacing: -0.03em;
  color: var(--text);
  line-height: 1.25;
}

.login-sub {
  margin: 0.4rem 0 0;
  font-size: 0.88rem;
  line-height: 1.45;
  color: var(--muted);
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 0.95rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.form-group label {
  font-size: 0.78rem;
  font-weight: 650;
  color: var(--text);
}

.form-group input {
  width: 100%;
  height: 40px;
  padding: 0 0.75rem;
  font-size: 0.9rem;
  background: var(--input-bg);
  border: 1px solid var(--border-medium);
  border-radius: var(--radius-sm);
  color: var(--text);
  outline: none;
}

.form-group input::placeholder {
  color: var(--text-disabled);
}

.form-group input:focus {
  border-color: var(--accent);
  box-shadow: var(--focus-ring);
}

.btn-login-submit {
  width: 100%;
  height: 40px;
  margin-top: 0.35rem;
  background: var(--accent);
  color: var(--on-accent);
  border: 1px solid var(--accent);
  border-radius: var(--radius-sm);
  font-size: 0.9rem;
  font-weight: 650;
  cursor: pointer;
}

.btn-login-submit:hover:not(:disabled) {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
}

.btn-login-submit:active:not(:disabled) {
  background: var(--brand-pressed);
  border-color: var(--brand-pressed);
}

.sso-divider {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin: 1.35rem 0 0.85rem;
}

.divider-line {
  flex: 1;
  height: 1px;
  background: var(--line);
}

.divider-text {
  font-size: 0.72rem;
  color: var(--muted);
  white-space: nowrap;
}

.sso-buttons-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.btn-sso {
  width: 100%;
  height: 40px;
  background: var(--btn-bg);
  border: 1px solid var(--btn-border);
  color: var(--btn-fg);
  border-radius: var(--radius-sm);
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
}

.btn-sso:hover {
  background: var(--btn-bg-hover);
  border-color: var(--accent);
  color: var(--text);
}

.login-error-msg {
  margin: 0;
}

.insecure-defaults-hint {
  margin: 1.15rem 0 0;
  font-size: 0.75rem;
  line-height: 1.4;
  color: var(--muted);
}
</style>

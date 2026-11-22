<script setup lang="ts">
import { ref } from "vue";
import { storeToRefs } from "pinia";
import { Eye, EyeOff, ShieldCheck, Smartphone, Layers, Cpu } from "lucide-vue-next";
import { useAuthStore } from "../stores/auth";
import { APP_TITLE } from "../brand";
import BrandMark from "./BrandMark.vue";
import ThemeToggle from "./ThemeToggle.vue";
import InviteAcceptCard from "./projects/InviteAcceptCard.vue";

const auth = useAuthStore();
const { loginForm, loginError, oidcEnabled, samlEnabled } = storeToRefs(auth);
const submitting = ref(false);
const showPassword = ref(false);

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
  <div class="vben-login-shell">
    <!-- Left ~58% Brand Showcase Panel (Vben v5 Asymmetric Split) -->
    <section class="vben-login-hero" aria-hidden="true">
      <div class="vben-login-brand">
        <BrandMark :size="30" />
        <span class="vben-login-brand-name">{{ APP_TITLE }}</span>
      </div>

      <div class="vben-login-hero-center">
        <!-- Crisp Isometric Automation Testing & Device Lab Illustration -->
        <div class="vben-hero-visual">
          <svg viewBox="0 0 420 280" fill="none" xmlns="http://www.w3.org/2000/svg" class="vben-hero-svg">
            <defs>
              <linearGradient id="apGradPrimary" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stop-color="#006be6" />
                <stop offset="100%" stop-color="#4f46e5" />
              </linearGradient>
              <linearGradient id="apGradCard" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="rgba(255,255,255,0.92)" />
                <stop offset="100%" stop-color="rgba(241,245,249,0.78)" />
              </linearGradient>
            </defs>
            <!-- Soft Isometric Base Platform -->
            <ellipse cx="210" cy="236" rx="156" ry="26" fill="rgba(0,107,230,0.10)" />
            <path d="M74 176 L210 112 L346 176 L210 232 Z" fill="url(#apGradPrimary)" opacity="0.14" />
            <path d="M96 168 L210 116 L324 168 L210 216 Z" fill="url(#apGradPrimary)" opacity="0.22" />

            <!-- Main Workbench Dashboard Window -->
            <rect x="64" y="42" width="232" height="148" rx="12" fill="var(--vben-bg-surface)" stroke="var(--vben-border)" stroke-width="1.5" />
            <rect x="64" y="42" width="232" height="28" rx="12" fill="var(--vben-bg-muted)" />
            <circle cx="80" cy="56" r="3.5" fill="#ef4444" opacity="0.8" />
            <circle cx="92" cy="56" r="3.5" fill="#f59e0b" opacity="0.8" />
            <circle cx="104" cy="56" r="3.5" fill="#10b981" opacity="0.8" />
            <rect x="78" y="82" width="56" height="36" rx="6" fill="rgba(0,107,230,0.12)" />
            <rect x="86" y="92" width="24" height="5" rx="2.5" fill="#006be6" />
            <rect x="86" y="102" width="38" height="8" rx="3" fill="#006be6" opacity="0.45" />
            <rect x="144" y="82" width="56" height="36" rx="6" fill="rgba(16,185,129,0.12)" />
            <rect x="152" y="92" width="24" height="5" rx="2.5" fill="#10b981" />
            <rect x="152" y="102" width="38" height="8" rx="3" fill="#10b981" opacity="0.45" />
            <rect x="210" y="82" width="72" height="36" rx="6" fill="rgba(99,102,241,0.12)" />
            <rect x="218" y="92" width="32" height="5" rx="2.5" fill="#6366f1" />
            <rect x="218" y="102" width="50" height="8" rx="3" fill="#6366f1" opacity="0.45" />

            <!-- Trend Wave -->
            <path d="M78 168 Q112 138 144 152 T210 134 T282 146 L282 176 L78 176 Z" fill="url(#apGradPrimary)" opacity="0.16" />
            <path d="M78 168 Q112 138 144 152 T210 134 T282 146" stroke="#006be6" stroke-width="2.5" stroke-linecap="round" fill="none" />

            <!-- Floating Mobile Device Frame (Real Device Lab) -->
            <rect x="274" y="76" width="84" height="148" rx="14" fill="var(--vben-bg-surface)" stroke="var(--vben-primary)" stroke-width="2" />
            <rect x="304" y="84" width="24" height="4" rx="2" fill="var(--vben-border)" />
            <rect x="284" y="96" width="64" height="44" rx="6" fill="rgba(0,107,230,0.12)" />
            <circle cx="316" cy="118" r="12" fill="#006be6" opacity="0.85" />
            <path d="M311 118 L315 122 L322 114" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
            <rect x="284" y="150" width="64" height="10" rx="4" fill="var(--vben-bg-muted)" />
            <rect x="284" y="168" width="44" height="10" rx="4" fill="var(--vben-bg-muted)" />
            <rect x="284" y="188" width="64" height="22" rx="6" fill="url(#apGradPrimary)" />
          </svg>
        </div>

        <h1 class="vben-hero-title">自动化测试运营与真机云测工作台</h1>
        <p class="vben-hero-desc">
          覆盖需求解析、意图用例评审、多端批跑调度与实时真机远控的一体化企业级质量工程平台
        </p>

        <div class="vben-hero-pills">
          <span><Layers :size="14" /> 意图用例设计</span>
          <span><Cpu :size="14" /> 多端批跑调度</span>
          <span><Smartphone :size="14" /> Android / iOS 真机远控</span>
          <span><ShieldCheck :size="14" /> 多租户权限隔离</span>
        </div>
      </div>
    </section>

    <!-- Right ~42% Auth Surface Panel -->
    <section class="vben-login-form-pane">
      <div class="vben-login-toolbar">
        <div class="vben-login-mobile-brand">
          <BrandMark :size="24" />
          <span>{{ APP_TITLE }}</span>
        </div>
        <div class="vben-login-utility-pill">
          <ThemeToggle />
        </div>
      </div>

      <div class="vben-login-form-wrap">
        <header class="vben-login-header">
          <h2>欢迎回来</h2>
          <p class="vben-login-sub">请输入您的组织账号以继续使用 {{ APP_TITLE }}</p>
        </header>

        <form class="vben-login-form" @submit="onSubmit">
          <div class="vben-field">
            <label for="username">用户名</label>
            <input
              id="username"
              v-model="loginForm.username"
              required
              placeholder="请输入组织账号"
              autocomplete="username"
              autofocus
            />
          </div>

          <div class="vben-field">
            <label for="password">密码</label>
            <div class="vben-password-wrap">
              <input
                id="password"
                v-model="loginForm.password"
                :type="showPassword ? 'text' : 'password'"
                required
                placeholder="请输入密码"
                autocomplete="current-password"
              />
              <button
                type="button"
                class="vben-pw-toggle"
                :aria-label="showPassword ? '隐藏密码' : '显示密码'"
                @click="showPassword = !showPassword"
              >
                <EyeOff v-if="showPassword" :size="16" />
                <Eye v-else :size="16" />
              </button>
            </div>
          </div>

          <p v-if="loginError" class="vben-login-error" role="alert">{{ loginError }}</p>

          <button type="submit" class="vben-login-submit" :disabled="submitting">
            {{ submitting ? "正在登录…" : "登录" }}
          </button>
        </form>

        <template v-if="oidcEnabled || samlEnabled">
          <div class="vben-sso-divider">
            <span class="line"></span>
            <span class="label">其他登录方式</span>
            <span class="line"></span>
          </div>

          <div class="vben-sso-group">
            <button v-if="oidcEnabled" type="button" class="vben-sso-btn" @click="auth.onOidcLogin">
              企业 OIDC 登录
            </button>
            <button v-if="samlEnabled" type="button" class="vben-sso-btn" @click="auth.onSamlLogin">
              企业 SAML 2.0 登录
            </button>
          </div>
        </template>

        <InviteAcceptCard />
      </div>

      <footer class="vben-login-footer">
        <span>AutoPilot Platform · Enterprise Test Operations Workbench</span>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.vben-login-shell {
  min-height: 100vh;
  width: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(420px, 1fr);
  background: var(--vben-bg-surface);
}

/* Left Brand Panel */
.vben-login-hero {
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 24px 36px;
  overflow: hidden;
  background:
    radial-gradient(620px 460px at 36% 42%, rgba(0, 107, 230, 0.14), transparent 70%),
    radial-gradient(500px 420px at 68% 64%, rgba(79, 70, 229, 0.11), transparent 72%),
    var(--vben-bg-deep);
  border-right: 1px solid var(--vben-border);
}

[data-theme="dark"] .vben-login-hero {
  background:
    radial-gradient(620px 460px at 36% 42%, rgba(22, 119, 255, 0.16), transparent 70%),
    radial-gradient(500px 420px at 68% 64%, rgba(99, 102, 241, 0.12), transparent 72%),
    #111318;
}

.vben-login-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.vben-login-brand-name {
  font-size: 18px;
  font-weight: 700;
  color: var(--vben-fg-strong);
  letter-spacing: -0.02em;
}

.vben-login-hero-center {
  margin: auto;
  max-width: 500px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 16px;
}

.vben-hero-visual {
  width: 100%;
  max-width: 400px;
  margin-bottom: 4px;
}

.vben-hero-svg {
  width: 100%;
  height: auto;
  display: block;
}

.vben-hero-title {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
  color: var(--vben-fg-strong);
  letter-spacing: -0.02em;
  line-height: 1.35;
}

.vben-hero-desc {
  margin: 0;
  font-size: 14px;
  line-height: 1.65;
  color: var(--vben-fg-muted);
}

.vben-hero-pills {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  margin-top: 6px;
}

.vben-hero-pills span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 999px;
  font-size: 12.5px;
  font-weight: 500;
  color: var(--vben-fg);
  background: var(--vben-bg-surface);
  border: 1px solid var(--vben-border);
  box-shadow: var(--vben-shadow-card);
}

/* Right Auth Pane */
.vben-login-form-pane {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 20px 32px 24px;
  background: var(--vben-bg-surface);
}

.vben-login-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.vben-login-mobile-brand {
  display: none;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  font-size: 15px;
  color: var(--vben-fg-strong);
}

.vben-login-utility-pill {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  padding: 4px 6px;
  border-radius: 999px;
  background: var(--vben-bg-muted);
  border: 1px solid var(--vben-border);
}

.vben-login-form-wrap {
  width: 100%;
  max-width: 390px;
  margin: auto;
  padding: 24px 0;
}

.vben-login-header {
  margin-bottom: 28px;
}

.vben-login-header h2 {
  margin: 0;
  font-size: 32px;
  font-weight: 700;
  letter-spacing: -0.025em;
  color: var(--vben-fg-strong);
  line-height: 1.2;
}

.vben-login-sub {
  margin: 8px 0 0;
  font-size: 14px;
  color: var(--vben-fg-muted);
}

.vben-login-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.vben-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.vben-field label {
  font-size: 13px;
  font-weight: 500;
  color: var(--vben-fg);
}

.vben-field input {
  width: 100%;
  height: 40px;
  padding: 0 12px;
  font-size: 14px;
  background: var(--input-bg);
  border: 1px solid var(--vben-border);
  border-radius: var(--vben-radius-md);
  color: var(--vben-fg-strong);
  outline: 2px solid transparent;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.vben-field input:focus {
  border-color: var(--vben-primary);
  box-shadow: var(--focus-ring);
}

.vben-password-wrap {
  position: relative;
  display: flex;
  align-items: center;
}

.vben-password-wrap input {
  padding-right: 40px;
}

.vben-pw-toggle {
  position: absolute;
  right: 8px;
  border: none;
  background: transparent;
  color: var(--vben-fg-muted);
  width: 28px;
  height: 28px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.vben-pw-toggle:hover {
  color: var(--vben-fg-strong);
  background: var(--vben-bg-hover);
}

.vben-login-error {
  margin: 0;
  padding: 8px 12px;
  border-radius: var(--vben-radius-md);
  background: var(--danger-soft-bg);
  border: 1px solid var(--danger-soft-border);
  color: var(--danger-soft-fg);
  font-size: 13px;
}

.vben-login-submit {
  width: 100%;
  height: 40px;
  margin-top: 4px;
  border: none;
  border-radius: var(--vben-radius-md);
  background: var(--vben-primary);
  color: #ffffff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.vben-login-submit:hover:not(:disabled) {
  background: var(--vben-primary-hover);
}

.vben-login-submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.vben-sso-divider {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 22px 0 14px;
}

.vben-sso-divider .line {
  flex: 1;
  height: 1px;
  background: var(--vben-border);
}

.vben-sso-divider .label {
  font-size: 12px;
  color: var(--vben-fg-muted);
}

.vben-sso-group {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
}

.vben-sso-btn {
  height: 36px;
  border-radius: var(--vben-radius-md);
  border: 1px solid var(--vben-border);
  background: var(--vben-bg-surface);
  color: var(--vben-fg);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}

.vben-sso-btn:hover {
  background: var(--vben-bg-hover);
  border-color: var(--vben-primary-border);
}

.vben-login-footer {
  text-align: center;
  font-size: 12px;
  color: var(--vben-fg-subtle);
}

@media (max-width: 960px) {
  .vben-login-shell {
    grid-template-columns: 1fr;
  }
  .vben-login-hero {
    display: none;
  }
  .vben-login-mobile-brand {
    display: inline-flex;
  }
}
</style>

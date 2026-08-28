<script setup lang="ts">
import { onMounted, onUnmounted, computed, ref, onBeforeUnmount, watch } from "vue";
import { RouterView, useRoute } from "vue-router";
import { storeToRefs } from "pinia";
import { useCapabilities } from "./composables/useCapabilities";
import { useAuthStore } from "./stores/auth";
import { useShellStore } from "./stores/shellStore";
import { labelForTab, sectionIdForTab, sectionLabelForTab } from "./router/tabs";
import { KEEPALIVE_INCLUDE } from "./router/panels";
import { APP_TITLE } from "./brand";
import BrandMark from "./components/BrandMark.vue";
import LoginView from "./components/LoginView.vue";
import OrgSelect from "./components/projects/OrgSelect.vue";
import ProjectSelect from "./components/projects/ProjectSelect.vue";
import InviteAcceptCard from "./components/projects/InviteAcceptCard.vue";
import { platformRoleLabel } from "./components/projects/roleLabels";
import AppNotifyHost from "./components/AppNotifyHost.vue";
import ReserveDeviceDialog from "./components/ReserveDeviceDialog.vue";
import RemoteDeviceDialog from "./components/RemoteDeviceDialog.vue";
import JobReportViewer from "./components/JobReportViewer.vue";
import ThemeToggle from "./components/ThemeToggle.vue";
import DesignChatPanel from "./components/design/DesignChatPanel.vue";

const auth = useAuthStore();
const shell = useShellStore();
const {
  loggedIn,
  sessionHydrating,
  canManageUsers,
  user,
  healthOk,
} = storeToRefs(auth);
const { activeTab, error } = storeToRefs(shell);
const caps = useCapabilities();

const route = useRoute();
const sidebarCollapsed = ref(false);
const isMobile = ref(false);
const keepaliveInclude = KEEPALIVE_INCLUDE;
const NAV_OPEN_KEY = "ap-mc-nav-open-v1";
const navOpen = ref<Record<string, boolean>>({
  overview: true,
  design: true,
  exec: true,
  infra: true,
  admin: true,
});

function onVisibilityChange() {
  shell.setPageVisible(document.visibilityState !== "hidden");
}

function syncViewport() {
  const mobile = window.innerWidth < 900;
  const wasMobile = isMobile.value;
  isMobile.value = mobile;
  if (mobile) {
    sidebarCollapsed.value = true;
  } else if (wasMobile) {
    readSidebarPref();
  }
}

/** 共享 ACL：全体已登录用户可查看；写操作由 SharePanel 内 canShare 控制 */
const showShareNav = computed(() => Boolean(loggedIn.value));
/** 设备与执行：operator 只读；管理动作由组件内 useCapabilities 控制 */
const showDevicesNav = computed(() => Boolean(loggedIn.value));

function guardAdminTabs() {
  // 旧侧栏「AI 对话」tab 已改为悬浮窗；「设计配置」已并入运维（仅 admin）
  if (activeTab.value === "design-chat") activeTab.value = "dashboard";
  if (activeTab.value === "design-config") {
    activeTab.value = caps.canOps ? "ops" : "dashboard";
  }
  if (activeTab.value === "ops" && !caps.canOps) {
    activeTab.value = "dashboard";
  }
  if (
    (activeTab.value === "audit" || activeTab.value === "users") &&
    !canManageUsers.value
  ) {
    activeTab.value = "dashboard";
  }
  if (activeTab.value === "share" && !showShareNav.value) {
    activeTab.value = "dashboard";
  }
  if (activeTab.value === "devices" && !showDevicesNav.value) {
    activeTab.value = "dashboard";
  }
}

onMounted(() => {
  void auth.bootstrap();
  syncViewport();
  if (!isMobile.value) readSidebarPref();
  readNavOpen();
  guardAdminTabs();
  window.addEventListener("resize", syncViewport);
  document.addEventListener("visibilitychange", onVisibilityChange);
  onVisibilityChange();
});

watch(
  () => activeTab.value,
  (tab) => {
    const sec = sectionIdForTab(tab);
    if (sec && navOpen.value[sec] === false) {
      navOpen.value[sec] = true;
    }
  },
);

watch(
  () => [activeTab.value, caps.canOps, canManageUsers.value] as const,
  () => guardAdminTabs(),
);

onUnmounted(() => {
  shell.stopPolling();
  document.removeEventListener("visibilitychange", onVisibilityChange);
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", syncViewport);
});

const SIDEBAR_COLLAPSE_KEY = "ap-mc-sidebar-collapsed";

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value;
  if (!isMobile.value) {
    try {
      localStorage.setItem(SIDEBAR_COLLAPSE_KEY, sidebarCollapsed.value ? "1" : "0");
    } catch {
      /* ignore */
    }
  }
}

function selectNav(tab: string) {
  activeTab.value = tab;
  if (isMobile.value) sidebarCollapsed.value = true;
}

function readSidebarPref() {
  try {
    const v = localStorage.getItem(SIDEBAR_COLLAPSE_KEY);
    if (v === "1") sidebarCollapsed.value = true;
    if (v === "0") sidebarCollapsed.value = false;
  } catch {
    /* ignore */
  }
}

function readNavOpen() {
  try {
    const raw = localStorage.getItem(NAV_OPEN_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw) as Record<string, boolean>;
    if (parsed && typeof parsed === "object") {
      navOpen.value = { ...navOpen.value, ...parsed };
    }
  } catch {
    /* ignore */
  }
}

function toggleNavSection(id: string) {
  navOpen.value[id] = !navOpen.value[id];
  try {
    localStorage.setItem(NAV_OPEN_KEY, JSON.stringify(navOpen.value));
  } catch {
    /* ignore */
  }
}

function navGroupOpen(id: string) {
  return sidebarCollapsed.value || navOpen.value[id] !== false;
}

const currentBreadcrumb = computed(() => labelForTab(activeTab.value));
const sectionCrumb = computed(() => sectionLabelForTab(activeTab.value));
const showSectionCrumb = computed(
  () => Boolean(sectionCrumb.value) && sectionCrumb.value !== currentBreadcrumb.value,
);
</script>

<template>
  <a class="skip-link" href="#page-main">跳到主内容</a>

  <!-- Guest：GitLab / Grafana 式居中登录，不走左右分栏 -->
  <div v-if="sessionHydrating" class="guest-layout" aria-busy="true">
    <header class="guest-top">
      <div class="guest-brand-row">
        <BrandMark :size="28" />
        <span class="guest-brand-name">{{ APP_TITLE }}</span>
      </div>
      <ThemeToggle />
    </header>
    <div class="guest-main">
      <p class="session-hydrating">正在恢复登录…</p>
    </div>
  </div>
  <div v-else-if="!loggedIn" class="guest-layout">
    <header class="guest-top">
      <div class="guest-brand-row">
        <BrandMark :size="28" />
        <span class="guest-brand-name">{{ APP_TITLE }}</span>
      </div>
      <ThemeToggle />
    </header>
    <div class="guest-main">
      <div class="guest-container">
        <LoginView />
      </div>
    </div>
  </div>

  <!-- Authenticated Shell Layout -->
  <div v-else class="app-shell" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
    <div
      v-if="isMobile && !sidebarCollapsed"
      class="sidebar-backdrop"
      @click="sidebarCollapsed = true"
    ></div>
    <!-- Left Sidebar：桌面收成图标轨；移动端抽屉 -->
    <aside class="sidebar" :aria-expanded="!sidebarCollapsed">
      <div class="sidebar-header">
        <BrandMark :size="28" />
        <div class="brand-text">
          <span class="brand-name">{{ APP_TITLE }}</span>
        </div>
        <button
          type="button"
          class="sidebar-collapse-btn"
          :title="sidebarCollapsed ? '展开侧栏' : '折叠侧栏'"
          @click="toggleSidebar"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2.2" fill="none" aria-hidden="true">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>
      </div>

      <!-- Main Navigation Menu -->
      <nav class="sidebar-nav" aria-label="主导航">
        <div class="nav-group">
          <button
            type="button"
            class="nav-section-toggle"
            :class="{ 'is-open': navGroupOpen('overview') }"
            :aria-expanded="navGroupOpen('overview')"
            @click="toggleNavSection('overview')"
          >
            概览
            <svg class="nav-section-chevron" viewBox="0 0 12 12" aria-hidden="true">
              <polyline points="4 2 8 6 4 10" fill="none" stroke="currentColor" stroke-width="1.6" />
            </svg>
          </button>
          <div class="nav-group-items" :class="{ 'is-collapsed': !navGroupOpen('overview') }">
        <button class="nav-item" title="概览" :class="{ active: activeTab === 'dashboard' }" @click="selectNav('dashboard')">
          <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" class="nav-icon">
            <rect x="3" y="3" width="7" height="9" />
            <rect x="14" y="3" width="7" height="5" />
            <rect x="14" y="12" width="7" height="9" />
            <rect x="3" y="16" width="7" height="5" />
          </svg>
          <span class="nav-label">概览</span>
        </button>

        <button class="nav-item" title="项目" :class="{ active: activeTab === 'projects' }" @click="selectNav('projects')">
          <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" class="nav-icon">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
          </svg>
          <span class="nav-label">项目</span>
        </button>

        <button
          v-if="showShareNav"
          class="nav-item"
          title="共享"
          :class="{ active: activeTab === 'share' }"
          @click="selectNav('share')"
        >
          <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" class="nav-icon">
            <circle cx="18" cy="5" r="3" />
            <circle cx="6" cy="12" r="3" />
            <circle cx="18" cy="19" r="3" />
            <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
            <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
          </svg>
          <span class="nav-label">共享</span>
        </button>
          </div>
        </div>

        <div class="nav-group">
          <button
            type="button"
            class="nav-section-toggle"
            :class="{ 'is-open': navGroupOpen('design') }"
            :aria-expanded="navGroupOpen('design')"
            @click="toggleNavSection('design')"
          >
            测试设计
            <svg class="nav-section-chevron" viewBox="0 0 12 12" aria-hidden="true">
              <polyline points="4 2 8 6 4 10" fill="none" stroke="currentColor" stroke-width="1.6" />
            </svg>
          </button>
          <div class="nav-group-items" :class="{ 'is-collapsed': !navGroupOpen('design') }">
        <button class="nav-item" title="设计总览" :class="{ active: activeTab === 'design-dashboard' }" @click="selectNav('design-dashboard')">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" class="nav-icon">
            <rect x="3" y="3" width="7" height="7" rx="1"/>
            <rect x="14" y="3" width="7" height="7" rx="1"/>
            <rect x="3" y="14" width="7" height="7" rx="1"/>
            <rect x="14" y="14" width="7" height="7" rx="1"/>
          </svg>
          <span class="nav-label">设计总览</span>
        </button>
        <button class="nav-item" title="需求文档" :class="{ active: activeTab === 'design-docs' }" @click="selectNav('design-docs')">
          <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" class="nav-icon">
            <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
            <polyline points="13 2 13 9 20 9" />
          </svg>
          <span class="nav-label">需求文档</span>
        </button>
        <button class="nav-item" title="意图用例" :class="{ active: activeTab === 'design-cases' }" @click="selectNav('design-cases')">
          <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" class="nav-icon">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
          </svg>
          <span class="nav-label">意图用例</span>
        </button>
        <button
          class="nav-item"
          title="记下常用规则，生成用例时可以用"
          :class="{ active: activeTab === 'design-knowledge' }"
          @click="selectNav('design-knowledge')"
        >
          <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" class="nav-icon">
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
          </svg>
          <span class="nav-label">知识库</span>
        </button>
          </div>
        </div>

        <div class="nav-group">
          <button
            type="button"
            class="nav-section-toggle"
            :class="{ 'is-open': navGroupOpen('exec') }"
            :aria-expanded="navGroupOpen('exec')"
            @click="toggleNavSection('exec')"
          >
            测试与执行
            <svg class="nav-section-chevron" viewBox="0 0 12 12" aria-hidden="true">
              <polyline points="4 2 8 6 4 10" fill="none" stroke="currentColor" stroke-width="1.6" />
            </svg>
          </button>
          <div class="nav-group-items" :class="{ 'is-collapsed': !navGroupOpen('exec') }">
        <button class="nav-item" title="工程制品" :class="{ active: activeTab === 'artifacts' }" @click="selectNav('artifacts')">
          <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" class="nav-icon">
            <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
            <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
            <line x1="12" y1="22.08" x2="12" y2="12" />
          </svg>
          <span class="nav-label">工程制品</span>
        </button>

        <button class="nav-item" title="应用资源" :class="{ active: activeTab === 'app-builds' }" @click="selectNav('app-builds')">
          <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" class="nav-icon">
            <rect x="5" y="2" width="14" height="20" rx="2" ry="2" />
            <line x1="12" y1="18" x2="12.01" y2="18" />
          </svg>
          <span class="nav-label">应用资源</span>
        </button>

        <button class="nav-item" title="批跑" :class="{ active: activeTab === 'jobs' }" @click="selectNav('jobs')">
          <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" class="nav-icon">
            <polygon points="5 3 19 12 5 21 5 3" />
          </svg>
          <span class="nav-label">批跑</span>
        </button>

        <button class="nav-item" title="计划" :class="{ active: activeTab === 'schedules' }" @click="selectNav('schedules')">
          <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" class="nav-icon">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
          <span class="nav-label">计划</span>
        </button>

        <button class="nav-item" title="报告" :class="{ active: activeTab === 'reports' }" @click="selectNav('reports')">
          <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" class="nav-icon">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
            <polyline points="10 9 9 9 8 9" />
          </svg>
          <span class="nav-label">报告</span>
        </button>
          </div>
        </div>

        <div v-if="showDevicesNav" class="nav-group">
          <button
            type="button"
            class="nav-section-toggle"
            :class="{ 'is-open': navGroupOpen('infra') }"
            :aria-expanded="navGroupOpen('infra')"
            @click="toggleNavSection('infra')"
          >
            设备与执行
            <svg class="nav-section-chevron" viewBox="0 0 12 12" aria-hidden="true">
              <polyline points="4 2 8 6 4 10" fill="none" stroke="currentColor" stroke-width="1.6" />
            </svg>
          </button>
          <div class="nav-group-items" :class="{ 'is-collapsed': !navGroupOpen('infra') }">
          <button class="nav-item" title="设备" :class="{ active: activeTab === 'devices' }" @click="selectNav('devices')">
            <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" class="nav-icon">
              <rect x="5" y="2" width="14" height="20" rx="2" />
              <line x1="12" y1="18" x2="12.01" y2="18" />
            </svg>
            <span class="nav-label">设备</span>
          </button>
          </div>
        </div>

        <div v-if="caps.canOps || canManageUsers" class="nav-group">
          <button
            type="button"
            class="nav-section-toggle"
            :class="{ 'is-open': navGroupOpen('admin') }"
            :aria-expanded="navGroupOpen('admin')"
            @click="toggleNavSection('admin')"
          >
            {{ caps.canOps ? "系统管理" : "组织管理" }}
            <svg class="nav-section-chevron" viewBox="0 0 12 12" aria-hidden="true">
              <polyline points="4 2 8 6 4 10" fill="none" stroke="currentColor" stroke-width="1.6" />
            </svg>
          </button>
          <div class="nav-group-items" :class="{ 'is-collapsed': !navGroupOpen('admin') }">
          <button v-if="caps.canOps" class="nav-item" title="运维 · 配置中心" :class="{ active: activeTab === 'ops' }" @click="selectNav('ops')">
            <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" class="nav-icon">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
            <span class="nav-label">运维</span>
          </button>

          <button v-if="canManageUsers" class="nav-item" title="审计" :class="{ active: activeTab === 'audit' }" @click="selectNav('audit')">
            <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" class="nav-icon">
              <path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z" />
              <path d="M12 6v6l4 2" />
            </svg>
            <span class="nav-label">审计</span>
          </button>

          <button v-if="canManageUsers" class="nav-item" title="用户" :class="{ active: activeTab === 'users' }" @click="selectNav('users')">
            <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" class="nav-icon">
              <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
              <circle cx="9" cy="7" r="4" />
              <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
              <path d="M16 3.13a4 4 0 0 1 0 7.75" />
            </svg>
            <span class="nav-label">用户</span>
          </button>
          </div>
        </div>
      </nav>

      <!-- Sidebar Bottom Profile / Signout -->
      <div class="sidebar-footer">
        <div class="user-profile-badge" :title="user?.username || ''">
          <div class="avatar-placeholder">
            {{ (user?.username || 'U').slice(0, 2).toUpperCase() }}
          </div>
          <div class="profile-info">
            <span class="profile-username">{{ user?.username }}</span>
            <span class="profile-role">{{ platformRoleLabel(user?.role) }}</span>
          </div>
        </div>
        <button class="btn-logout" title="退出系统" @click="auth.onLogout">
          <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
            <polyline points="16 17 21 12 16 7" />
            <line x1="21" y1="12" x2="9" y2="12" />
          </svg>
        </button>
      </div>
    </aside>

    <!-- Right Workspace Area -->
    <div class="workspace-area">
      <!-- Global Top Bar -->
      <header class="topbar">
        <div class="topbar-left">
          <button
            type="button"
            class="btn-sidebar-toggle"
            :title="sidebarCollapsed ? '展开侧栏' : '折叠侧栏'"
            @click="toggleSidebar"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none" aria-hidden="true">
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
          <nav class="breadcrumb" aria-label="当前位置">
            <template v-if="showSectionCrumb">
              <span class="bc-parent">{{ sectionCrumb }}</span>
              <span class="bc-divider">/</span>
            </template>
            <span class="bc-active">{{ currentBreadcrumb }}</span>
          </nav>
        </div>

        <div class="topbar-right">
          <div class="workspace-switcher" role="group" aria-label="组织与项目上下文">
            <OrgSelect />
            <span class="ws-sep" aria-hidden="true"></span>
            <ProjectSelect />
          </div>

          <!-- 平台健康：仅运维需要看 /health 信号 -->
          <div
            v-if="caps.canOps"
            class="api-health-tag"
            :class="healthOk === true ? 'ok' : healthOk === false ? 'bad' : 'pending'"
          >
            <span class="health-dot"></span>
            <span class="health-label">
              {{ healthOk === true ? "API 正常" : healthOk === false ? "服务异常" : "检测中…" }}
            </span>
          </div>

          <ThemeToggle />

          <!-- Manual Refresh -->
          <button class="btn-refresh" @click="shell.refreshForTab(activeTab)" title="刷新当前页数据" aria-label="刷新">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" aria-hidden="true">
              <path
                d="M21 2v6h-6M3 12a9 9 0 0 1 15-6.7L21 8M3 22v-6h6M21 12a9 9 0 0 1-15 6.7L3 16"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          </button>
        </div>
      </header>

      <!-- 登录后仍可通过 ?invite= 接受邀请 -->
      <div class="invite-slot">
        <InviteAcceptCard />
      </div>

      <!-- 顶栏数据层错误横幅（shell.error，不是 Toast） -->
      <div v-if="error" class="global-error-banner animate-slide-in">
        <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" class="error-banner-icon">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
        <span class="error-banner-text">{{ error }}</span>
        <button class="error-banner-close" @click="error = ''">&times;</button>
      </div>

      <!-- Dynamic Tab content：RouterView + KeepAlive（Phase3） -->
      <main id="page-main" class="page-body" tabindex="-1">
        <div class="content-wrapper">
          <RouterView v-slot="{ Component }">
            <KeepAlive :include="keepaliveInclude" :max="16">
              <component
                :is="Component"
                :key="String(route.meta.tab || route.path)"
              />
            </KeepAlive>
          </RouterView>
        </div>
      </main>
    </div>
    <!-- AI 对话：全局悬浮窗（对齐 Scenario_Engine ChatDock；非侧栏 tab） -->
    <DesignChatPanel />
  </div>
  <AppNotifyHost />
  <ReserveDeviceDialog />
  <RemoteDeviceDialog />
  <JobReportViewer />
</template>

<style>
/* CSS styles are primarily centralized in styles.css, but we use these highly robust structure rules in App.vue */
.app-shell {
  display: flex;
  min-height: 100vh;
  width: 100vw;
  overflow: hidden;
  background: var(--bg);
}

/* Sidebar —— 展开 248px / 收拢 68px；深色轨 + 浅内容（Arco Pro / Grafana 分区） */
.sidebar {
  --sidebar-w: 248px;
  --sidebar-rail: 68px;
  width: var(--sidebar-w);
  background: var(--sidebar-bg);
  border-right: 1px solid var(--sidebar-line);
  color: var(--sidebar-fg);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  z-index: 100;
  overflow: hidden;
  transition: width 0.28s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 1px 0 0 rgba(0, 0, 0, 0.06);
}

.sidebar-header {
  height: var(--topbar-height, 56px);
  padding: 0 0.85rem 0 1rem;
  display: flex;
  align-items: center;
  gap: 0.55rem;
  border-bottom: 1px solid var(--sidebar-line);
  flex-shrink: 0;
}

.brand-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
  overflow: hidden;
  opacity: 1;
  max-width: 160px;
  transition: opacity 0.2s ease, max-width 0.28s ease;
}

.brand-name {
  font-size: 0.98rem;
  font-weight: 700;
  color: var(--sidebar-brand);
  letter-spacing: -0.01em;
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sidebar-nav {
  flex: 1;
  padding: 0.85rem 0.65rem;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-width: thin;
}

.nav-section-label {
  font-size: 0.68rem;
  font-weight: 600;
  color: var(--nav-section);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 0.75rem 0.6rem 0.35rem;
  white-space: nowrap;
  overflow: hidden;
  opacity: 1;
  max-height: 2.5rem;
  transition: opacity 0.18s ease, max-height 0.28s ease, padding 0.28s ease;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  background: transparent;
  border: none;
  color: var(--sidebar-muted);
  font-size: 0.88rem;
  font-weight: 500;
  padding: 0.55rem 0.75rem;
  border-radius: var(--radius-sm, 4px);
  cursor: pointer;
  text-align: left;
  transition: background 0.15s ease, color 0.15s ease, padding 0.28s ease;
  width: 100%;
  min-height: 38px;
  box-shadow: none;
}

.nav-item:hover {
  background: var(--nav-hover);
  color: var(--sidebar-fg);
}

.nav-item.active {
  background: var(--nav-active-bg);
  color: var(--nav-active-fg);
  font-weight: 600;
  box-shadow: none;
}

.nav-icon {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  opacity: 0.8;
}

.nav-item.active .nav-icon {
  color: #9ec5f5;
  opacity: 1;
}

.nav-label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  opacity: 1;
  max-width: 12rem;
  transition: opacity 0.18s ease, max-width 0.18s ease;
}
.sidebar-footer {
  padding: 0.85rem 0.65rem;
  border-top: 1px solid var(--sidebar-line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.35rem;
  background: var(--sidebar-footer-bg);
  flex-shrink: 0;
  min-height: 64px;
}

.user-profile-badge {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  min-width: 0;
  flex: 1;
}

.avatar-placeholder {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--accent);
  color: var(--on-accent);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 0.78rem;
  flex-shrink: 0;
  letter-spacing: 0.02em;
}

.profile-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  opacity: 1;
  max-width: 120px;
  transition: opacity 0.18s ease, max-width 0.28s ease;
}

.profile-username {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--sidebar-fg);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.profile-role {
  font-size: 0.7rem;
  color: var(--sidebar-muted);
}

.btn-logout {
  background: transparent;
  border: none;
  color: var(--sidebar-muted);
  cursor: pointer;
  padding: 0.4rem;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.18s ease, color 0.18s ease;
  flex-shrink: 0;
  box-shadow: none;
}

.btn-logout:hover {
  background: var(--danger-soft-bg);
  color: var(--bad);
}

.sidebar-collapse-btn {
  margin-left: auto;
  flex-shrink: 0;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--sidebar-line);
  color: var(--sidebar-muted);
  cursor: pointer;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  transition: background 0.18s ease, color 0.18s ease, transform 0.28s ease;
  box-shadow: none;
}

.sidebar-collapse-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--sidebar-fg);
}

.sidebar-collapse-btn svg {
  display: block;
  transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1);
}

/* Right Workspace Container */
.workspace-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background: var(--main-bg);
}

/* Topbar */
.topbar {
  height: var(--topbar-height, 56px);
  border-bottom: 1px solid var(--line);
  padding: 0 1.5rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--header-bg);
  flex-shrink: 0;
  box-shadow: none;
}

.breadcrumb {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.88rem;
}

.bc-parent {
  color: var(--muted);
}

.bc-divider {
  color: var(--nav-section);
}

.bc-active {
  color: var(--text);
  font-weight: 600;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  min-width: 0;
}

@media (max-width: 1100px) {
  .workspace-switcher {
    max-width: 16rem;
  }
  .health-label {
    display: none;
  }
}

.project-filter-input {
  position: relative;
  display: flex;
  align-items: center;
}

.input-search-icon {
  position: absolute;
  left: 0.65rem;
  color: var(--muted);
  pointer-events: none;
}

.project-filter-input input {
  padding-left: 2rem;
  min-width: 180px;
  font-size: 0.82rem;
  height: 32px;
}

.api-health-tag {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.22rem 0.55rem;
  border-radius: var(--radius-sm, 4px);
  background: var(--chip-bg);
  border: 1px solid var(--line);
  font-size: 0.78rem;
}

.health-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--muted);
}

.api-health-tag.ok .health-dot {
  background: var(--ok);
}

.api-health-tag.bad .health-dot {
  background: var(--bad);
}

.api-health-tag.pending .health-dot {
  background: var(--warning);
}

.btn-refresh {
  box-sizing: border-box;
  background: var(--control-bg);
  border: 1px solid var(--line);
  color: var(--text);
  cursor: pointer;
  width: 32px;
  height: 32px;
  min-width: 32px;
  padding: 0;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: var(--transition);
  flex-shrink: 0;
  opacity: 1;
}

.btn-refresh svg {
  display: block;
  flex-shrink: 0;
  color: inherit;
}

.btn-refresh:hover {
  border-color: var(--accent);
  color: var(--accent-text);
  background: var(--brand-soft);
  transform: none;
}

.btn-refresh:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

/* Page body */
.content-wrapper {
  max-width: none;
  width: 100%;
}

.page-body {
  flex: 1;
  padding: 1rem 1.25rem 1.5rem;
  overflow-y: auto;
  background: var(--main-bg);
}

.tab-panel-layout {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

/* Guest：单画布居中（GitLab / Grafana / GitHub），禁止左右分色 */
.guest-layout {
  position: relative;
  min-height: 100dvh;
  width: 100vw;
  display: flex;
  flex-direction: column;
  background: var(--main-bg);
  color: var(--text);
}

.guest-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--topbar-height, 56px);
  padding: 0 1.25rem;
  border-bottom: 1px solid var(--line-soft);
  background: var(--header-bg);
  flex-shrink: 0;
}

.guest-brand-row {
  display: flex;
  align-items: center;
  gap: 0.65rem;
}

.guest-brand-name {
  font-size: 0.95rem;
  font-weight: 650;
  letter-spacing: -0.02em;
  color: var(--text);
}

.guest-main {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2.5rem 1.25rem 3.5rem;
}

.session-hydrating {
  margin: 0;
  font-size: 0.92rem;
  color: var(--muted);
}

.guest-container {
  width: 100%;
  max-width: 22rem;
}

/* Error banner */
.global-error-banner {
  margin: 1rem 1.75rem 0;
  background: var(--danger-soft-bg);
  border: 1px solid var(--danger-soft-border);
  border-radius: 8px;
  padding: 0.75rem 1.25rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  position: relative;
}

.error-banner-icon {
  color: var(--bad);
  flex-shrink: 0;
}

.error-banner-text {
  font-size: 0.85rem;
  color: var(--danger-soft-fg);
  flex: 1;
}

.error-banner-close {
  background: transparent;
  border: none;
  color: var(--muted);
  cursor: pointer;
  font-size: 1.25rem;
  padding: 0;
  line-height: 1;
}

.error-banner-close:hover {
  color: var(--text);
}

/* Simple animation */
.animate-fade-in {
  animation: fadeIn 0.4s ease-out;
}
.animate-slide-in {
  animation: slideIn 0.3s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes slideIn {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

.sidebar-backdrop {
  position: fixed;
  inset: 0;
  background: var(--overlay);
  z-index: 90;
  animation: fadeIn 0.2s ease-out;
}

.btn-sidebar-toggle {
  background: var(--control-bg);
  border: 1px solid var(--line);
  color: var(--text);
  width: 32px;
  height: 32px;
  min-width: 32px;
  padding: 0;
  border-radius: 6px;
  cursor: pointer;
  margin-right: 0.75rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 0.18s ease, border-color 0.18s ease;
}

.btn-sidebar-toggle:hover {
  background: var(--control-bg-hover);
  border-color: var(--accent);
}

.topbar-left {
  display: flex;
  align-items: center;
  min-width: 0;
}

/* 桌面：收拢为图标轨（非消失） */
.app-shell.sidebar-collapsed .sidebar {
  width: var(--sidebar-rail);
}

.app-shell.sidebar-collapsed .brand-text,
.app-shell.sidebar-collapsed .nav-label,
.app-shell.sidebar-collapsed .profile-info,
.app-shell.sidebar-collapsed .nav-section-toggle {
  opacity: 0;
  max-width: 0;
  width: 0;
  overflow: hidden;
  visibility: hidden;
  pointer-events: none;
}

.app-shell.sidebar-collapsed .nav-group-items.is-collapsed {
  display: flex;
}

.app-shell.sidebar-collapsed .sidebar-header {
  position: relative;
  justify-content: center;
  padding: 0;
  gap: 0;
}

.app-shell.sidebar-collapsed .sidebar-header :deep(.ap-mark) {
  margin: 0 auto;
}

.app-shell.sidebar-collapsed .sidebar-collapse-btn {
  display: none;
}

.app-shell.sidebar-collapsed .sidebar-nav {
  padding: 0.65rem 0.45rem;
  align-items: center;
}

.app-shell.sidebar-collapsed .nav-group {
  width: 100%;
  align-items: center;
}

.app-shell.sidebar-collapsed .nav-group-items {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
}

.app-shell.sidebar-collapsed .nav-item {
  justify-content: center;
  padding: 0.55rem;
  width: 44px;
  gap: 0;
}

.app-shell.sidebar-collapsed .sidebar-footer {
  flex-direction: column;
  justify-content: center;
  padding: 0.65rem 0.35rem;
  gap: 0.35rem;
}

.app-shell.sidebar-collapsed .user-profile-badge {
  justify-content: center;
  flex: 0;
}

@media (max-width: 900px) {
  .sidebar {
    position: fixed;
    left: 0;
    top: 0;
    bottom: 0;
    width: var(--sidebar-w);
    transform: translateX(0);
    box-shadow: 8px 0 24px rgba(0, 0, 0, 0.18);
    transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1), width 0.28s cubic-bezier(0.4, 0, 0.2, 1);
  }

  .app-shell.sidebar-collapsed .sidebar {
    width: var(--sidebar-w);
    transform: translateX(-100%);
    box-shadow: none;
  }

  /* 移动端折叠是隐藏抽屉，不走图标轨样式 */
  .app-shell.sidebar-collapsed .brand-text,
  .app-shell.sidebar-collapsed .nav-label,
  .app-shell.sidebar-collapsed .profile-info,
  .app-shell.sidebar-collapsed .nav-section-label,
  .app-shell.sidebar-collapsed .nav-section-toggle {
    opacity: 1;
    max-width: none;
    max-height: none;
    width: auto;
    overflow: visible;
    visibility: visible;
    pointer-events: auto;
  }

  .app-shell.sidebar-collapsed .sidebar-nav,
  .app-shell.sidebar-collapsed .nav-item,
  .app-shell.sidebar-collapsed .sidebar-footer,
  .app-shell.sidebar-collapsed .sidebar-header {
    padding: revert;
    width: revert;
    justify-content: revert;
    flex-direction: revert;
    align-items: revert;
    gap: revert;
  }

  .app-shell.sidebar-collapsed .sidebar-collapse-btn {
    display: inline-flex;
    opacity: 1;
    pointer-events: auto;
    position: static;
  }

  .app-shell.sidebar-collapsed .nav-item {
    width: 100%;
  }

  .app-shell:not(.sidebar-collapsed) .sidebar {
    width: var(--sidebar-w);
    transform: translateX(0);
  }
}
</style>

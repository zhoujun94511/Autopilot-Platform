<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, computed, ref, onBeforeUnmount, watch } from "vue";
import { RouterLink, RouterView, useRoute } from "vue-router";
import { storeToRefs } from "pinia";
import { theme as antdThemeApi } from "ant-design-vue";
import zhCN from "ant-design-vue/es/locale/zh_CN";
import {
  LayoutDashboard,
  FolderKanban,
  Share2,
  Compass,
  FileText,
  ListChecks,
  BookOpen,
  Package,
  AppWindow,
  Play,
  Clock,
  FileBarChart2,
  Smartphone,
  Settings,
  History,
  Users,
  PanelLeftClose,
  PanelLeftOpen,
  ChevronsLeft,
  ChevronsRight,
  ChevronRight,
  RotateCw,
  LogOut,
  AlertCircle,
} from "lucide-vue-next";
import { useCapabilities } from "./composables/useCapabilities";
import { useAuthStore } from "./stores/auth";
import { useShellStore } from "./stores/shellStore";
import { useTheme } from "./composables/useTheme";
import { labelForTab, pathForTab, sectionIdForTab, sectionLabelForTab } from "./router/tabs";
import { refreshPageFromToolbar } from "./composables/useManualPageRefresh";
import { apiErrorMessage } from "./api";
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
import VbenTabBar from "./components/layout/VbenTabBar.vue";
import VbenCommandSearch from "./components/layout/VbenCommandSearch.vue";

const auth = useAuthStore();
const shell = useShellStore();
const { isDark } = useTheme();
const {
  loggedIn,
  sessionHydrating,
  canManageUsers,
  user,
  healthOk,
} = storeToRefs(auth);
const { activeTab, error } = storeToRefs(shell);
const caps = useCapabilities();

const antdTheme = computed(() => ({
  algorithm: isDark.value ? antdThemeApi.darkAlgorithm : antdThemeApi.defaultAlgorithm,
  token: {
    colorPrimary: isDark.value ? "#1677ff" : "#006be6",
    borderRadius: 6,
    colorBgContainer: isDark.value ? "#1c1e23" : "#ffffff",
    colorBgElevated: isDark.value ? "#24262d" : "#ffffff",
    colorBorderSecondary: isDark.value ? "#2a2c32" : "#eef0f3",
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif',
  },
}));

const route = useRoute();
const sidebarCollapsed = ref(false);
const isMobile = ref(false);
const mobileDrawerOpen = computed(() => isMobile.value && !sidebarCollapsed.value);
const mobileDrawerClosed = computed(() => isMobile.value && sidebarCollapsed.value);
const sidebar = ref<HTMLElement | null>(null);
const sidebarToggle = ref<HTMLButtonElement | null>(null);
const mainContent = ref<HTMLElement | null>(null);
const refreshingPage = ref(false);
const userMenuOpen = ref(false);
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
  const mobile = window.matchMedia("(max-width: 900px)").matches;
  const wasMobile = isMobile.value;
  isMobile.value = mobile;
  if (mobile && !wasMobile) {
    void closeMobileSidebar();
  } else if (wasMobile) {
    readSidebarPref();
  }
}

const DETAILS_MENU_SELECTOR =
  "details.action-menu, details.job-row-menu, details.schedule-row-menu, details.row-more";

function closeOpenDetailsMenus(except?: HTMLElement | null) {
  for (const el of document.querySelectorAll<HTMLDetailsElement>(`${DETAILS_MENU_SELECTOR}[open]`)) {
    if (except && el === except) continue;
    el.open = false;
  }
}

function onGlobalClick(ev: MouseEvent) {
  const target = ev.target as HTMLElement | null;
  if (userMenuOpen.value && !target?.closest(".vben-user-menu-wrap")) {
    userMenuOpen.value = false;
  }
  const insideMenu = target?.closest<HTMLDetailsElement>(DETAILS_MENU_SELECTOR) ?? null;
  closeOpenDetailsMenus(insideMenu);
}

function onGlobalDetailsToggle(ev: Event) {
  const target = ev.target as HTMLDetailsElement | null;
  if (!target?.matches?.(DETAILS_MENU_SELECTOR) || !target.open) return;
  closeOpenDetailsMenus(target);
}

function onGlobalKeydown(ev: KeyboardEvent) {
  if (ev.key === "Escape") {
    if (userMenuOpen.value) userMenuOpen.value = false;
    for (const el of document.querySelectorAll<HTMLDetailsElement>(`${DETAILS_MENU_SELECTOR}[open]`)) {
      el.open = false;
      el.querySelector("summary")?.focus();
    }
  }
}

const showShareNav = computed(() => Boolean(loggedIn.value));
const showDevicesNav = computed(() => Boolean(loggedIn.value));

function guardAdminTabs() {
  if (sessionHydrating.value || !loggedIn.value) return;
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
  document.addEventListener("click", onGlobalClick);
  document.addEventListener("keydown", onGlobalKeydown);
  document.addEventListener("toggle", onGlobalDetailsToggle, true);
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
  () => [activeTab.value, sessionHydrating.value, caps.canOps, canManageUsers.value] as const,
  () => guardAdminTabs(),
);

onUnmounted(() => {
  shell.stopPolling();
  document.removeEventListener("visibilitychange", onVisibilityChange);
  document.removeEventListener("click", onGlobalClick);
  document.removeEventListener("keydown", onGlobalKeydown);
  document.removeEventListener("toggle", onGlobalDetailsToggle, true);
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", syncViewport);
});

const SIDEBAR_COLLAPSE_KEY = "ap-mc-sidebar-collapsed";

function toggleSidebar() {
  if (isMobile.value) {
    if (mobileDrawerOpen.value) void closeMobileSidebar();
    else {
      sidebarCollapsed.value = false;
      void nextTick(() => {
        sidebar.value?.querySelector<HTMLElement>("a[href], button:not([disabled])")?.focus();
      });
    }
    return;
  }
  sidebarCollapsed.value = !sidebarCollapsed.value;
  try {
    localStorage.setItem(SIDEBAR_COLLAPSE_KEY, sidebarCollapsed.value ? "1" : "0");
  } catch {
    /* ignore */
  }
}

async function closeMobileSidebar(focusMain = false) {
  const restoreFocus = sidebar.value?.contains(document.activeElement);
  sidebarCollapsed.value = true;
  if (restoreFocus || focusMain) {
    await nextTick();
    (focusMain ? mainContent.value : sidebarToggle.value)?.focus();
  }
}

function selectNav(event: MouseEvent) {
  if (
    mobileDrawerOpen.value &&
    event.button === 0 &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.shiftKey &&
    !event.altKey
  ) {
    void closeMobileSidebar(true);
  }
}

function onSidebarKeydown(event: KeyboardEvent) {
  if (!mobileDrawerOpen.value) return;
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    void closeMobileSidebar();
  }
  if (event.key !== "Tab") return;
  const controls = Array.from(
    sidebar.value?.querySelectorAll<HTMLElement>("button:not([disabled]), a[href]") ?? [],
  ).filter((element) => !element.closest("[inert]") && element.getClientRects().length);
  const first = controls[0];
  const last = controls.at(-1);
  if (!first || !last) return;
  if (document.activeElement === (event.shiftKey ? first : last)) {
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
  }
}

async function refreshCurrentPage() {
  if (refreshingPage.value) return;
  refreshingPage.value = true;
  try {
    await refreshPageFromToolbar(activeTab.value, () => shell.refreshForTab(activeTab.value));
  } catch (cause) {
    error.value = apiErrorMessage(cause);
  } finally {
    refreshingPage.value = false;
  }
}

function readSidebarPref() {
  try {
    sidebarCollapsed.value = localStorage.getItem(SIDEBAR_COLLAPSE_KEY) === "1";
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

function handleLogout() {
  userMenuOpen.value = false;
  void auth.onLogout();
}

const currentBreadcrumb = computed(() => labelForTab(activeTab.value));
const sectionCrumb = computed(() => sectionLabelForTab(activeTab.value));
const showSectionCrumb = computed(
  () => Boolean(sectionCrumb.value) && sectionCrumb.value !== currentBreadcrumb.value,
);
const userInitials = computed(() => (user.value?.username || "U").slice(0, 2).toUpperCase());
</script>

<template>
  <a-config-provider :locale="zhCN" :theme="antdTheme">
    <a v-if="loggedIn && !sessionHydrating" class="skip-link" href="#page-main" :inert="mobileDrawerOpen">
      跳到主内容
    </a>

    <!-- Hydrating State -->
    <div v-if="sessionHydrating" class="vben-hydrating" aria-busy="true">
      <div class="vben-hydrating-card">
        <BrandMark :size="36" />
        <span class="vben-hydrating-title">{{ APP_TITLE }}</span>
        <span class="vben-hydrating-sub">正在恢复会话…</span>
      </div>
    </div>

    <!-- Guest: Vben v5 Asymmetric Split Login -->
    <LoginView v-else-if="!loggedIn" />

    <!-- Authenticated Vben v5 Shell -->
    <div v-else class="vben-shell" :class="{ 'is-collapsed': sidebarCollapsed }">
      <div
        v-if="mobileDrawerOpen"
        class="vben-sidebar-backdrop"
        aria-hidden="true"
        @click="closeMobileSidebar()"
      ></div>

      <!-- Left Sidebar (224px / 64px rail) -->
      <aside
        id="app-sidebar"
        ref="sidebar"
        class="vben-sidebar"
        :inert="mobileDrawerClosed"
        :role="mobileDrawerOpen ? 'dialog' : undefined"
        :aria-modal="mobileDrawerOpen ? true : undefined"
        :aria-label="mobileDrawerOpen ? '导航菜单' : undefined"
        @keydown="onSidebarKeydown"
      >
        <div class="vben-sidebar-brand">
          <BrandMark :size="28" />
          <span class="vben-brand-title">{{ APP_TITLE }}</span>
        </div>

        <nav class="vben-sidebar-nav" aria-label="主导航">
          <!-- 概览 -->
          <div class="vben-nav-group">
            <button
              type="button"
              class="vben-nav-section"
              :class="{ 'is-open': navGroupOpen('overview') }"
              :aria-expanded="navGroupOpen('overview')"
              @click="toggleNavSection('overview')"
            >
              <span class="vben-nav-section-text">概览</span>
              <ChevronRight :size="14" class="vben-nav-chevron" aria-hidden="true" />
            </button>
            <div class="vben-nav-items" :class="{ 'is-collapsed': !navGroupOpen('overview') }" :inert="!navGroupOpen('overview')">
              <RouterLink class="vben-nav-item" title="总览" :class="{ active: activeTab === 'dashboard' }" :to="pathForTab('dashboard')" @click="selectNav">
                <LayoutDashboard :size="16" class="vben-nav-icon" aria-hidden="true" />
                <span class="vben-nav-label">总览</span>
              </RouterLink>
              <RouterLink class="vben-nav-item" title="项目" :class="{ active: activeTab === 'projects' }" :to="pathForTab('projects')" @click="selectNav">
                <FolderKanban :size="16" class="vben-nav-icon" aria-hidden="true" />
                <span class="vben-nav-label">项目</span>
              </RouterLink>
              <RouterLink v-if="showShareNav" class="vben-nav-item" title="共享" :class="{ active: activeTab === 'share' }" :to="pathForTab('share')" @click="selectNav">
                <Share2 :size="16" class="vben-nav-icon" aria-hidden="true" />
                <span class="vben-nav-label">共享</span>
              </RouterLink>
            </div>
          </div>

          <!-- 测试设计 -->
          <div class="vben-nav-group">
            <button
              type="button"
              class="vben-nav-section"
              :class="{ 'is-open': navGroupOpen('design') }"
              :aria-expanded="navGroupOpen('design')"
              @click="toggleNavSection('design')"
            >
              <span class="vben-nav-section-text">测试设计</span>
              <ChevronRight :size="14" class="vben-nav-chevron" aria-hidden="true" />
            </button>
            <div class="vben-nav-items" :class="{ 'is-collapsed': !navGroupOpen('design') }" :inert="!navGroupOpen('design')">
              <RouterLink class="vben-nav-item" title="设计总览" :class="{ active: activeTab === 'design-dashboard' }" :to="pathForTab('design-dashboard')" @click="selectNav">
                <Compass :size="16" class="vben-nav-icon" aria-hidden="true" />
                <span class="vben-nav-label">设计总览</span>
              </RouterLink>
              <RouterLink class="vben-nav-item" title="需求文档" :class="{ active: activeTab === 'design-docs' }" :to="pathForTab('design-docs')" @click="selectNav">
                <FileText :size="16" class="vben-nav-icon" aria-hidden="true" />
                <span class="vben-nav-label">需求文档</span>
              </RouterLink>
              <RouterLink class="vben-nav-item" title="意图用例" :class="{ active: activeTab === 'design-cases' }" :to="pathForTab('design-cases')" @click="selectNav">
                <ListChecks :size="16" class="vben-nav-icon" aria-hidden="true" />
                <span class="vben-nav-label">意图用例</span>
              </RouterLink>
              <RouterLink class="vben-nav-item" title="知识库" :class="{ active: activeTab === 'design-knowledge' }" :to="pathForTab('design-knowledge')" @click="selectNav">
                <BookOpen :size="16" class="vben-nav-icon" aria-hidden="true" />
                <span class="vben-nav-label">知识库</span>
              </RouterLink>
            </div>
          </div>

          <!-- 测试执行 -->
          <div class="vben-nav-group">
            <button
              type="button"
              class="vben-nav-section"
              :class="{ 'is-open': navGroupOpen('exec') }"
              :aria-expanded="navGroupOpen('exec')"
              @click="toggleNavSection('exec')"
            >
              <span class="vben-nav-section-text">执行</span>
              <ChevronRight :size="14" class="vben-nav-chevron" aria-hidden="true" />
            </button>
            <div class="vben-nav-items" :class="{ 'is-collapsed': !navGroupOpen('exec') }" :inert="!navGroupOpen('exec')">
              <RouterLink class="vben-nav-item" title="工程制品" :class="{ active: activeTab === 'artifacts' }" :to="pathForTab('artifacts')" @click="selectNav">
                <Package :size="16" class="vben-nav-icon" aria-hidden="true" />
                <span class="vben-nav-label">工程制品</span>
              </RouterLink>
              <RouterLink class="vben-nav-item" title="应用资源" :class="{ active: activeTab === 'app-builds' }" :to="pathForTab('app-builds')" @click="selectNav">
                <AppWindow :size="16" class="vben-nav-icon" aria-hidden="true" />
                <span class="vben-nav-label">应用资源</span>
              </RouterLink>
              <RouterLink class="vben-nav-item" title="批跑" :class="{ active: activeTab === 'jobs' }" :to="pathForTab('jobs')" @click="selectNav">
                <Play :size="16" class="vben-nav-icon" aria-hidden="true" />
                <span class="vben-nav-label">批跑</span>
              </RouterLink>
              <RouterLink class="vben-nav-item" title="定时计划" :class="{ active: activeTab === 'schedules' }" :to="pathForTab('schedules')" @click="selectNav">
                <Clock :size="16" class="vben-nav-icon" aria-hidden="true" />
                <span class="vben-nav-label">定时计划</span>
              </RouterLink>
              <RouterLink class="vben-nav-item" title="报告" :class="{ active: activeTab === 'reports' }" :to="pathForTab('reports')" @click="selectNav">
                <FileBarChart2 :size="16" class="vben-nav-icon" aria-hidden="true" />
                <span class="vben-nav-label">报告</span>
              </RouterLink>
            </div>
          </div>

          <!-- 实验室设备 -->
          <div v-if="showDevicesNav" class="vben-nav-group">
            <button
              type="button"
              class="vben-nav-section"
              :class="{ 'is-open': navGroupOpen('infra') }"
              :aria-expanded="navGroupOpen('infra')"
              @click="toggleNavSection('infra')"
            >
              <span class="vben-nav-section-text">实验室资源</span>
              <ChevronRight :size="14" class="vben-nav-chevron" aria-hidden="true" />
            </button>
            <div class="vben-nav-items" :class="{ 'is-collapsed': !navGroupOpen('infra') }" :inert="!navGroupOpen('infra')">
              <RouterLink class="vben-nav-item" title="设备" :class="{ active: activeTab === 'devices' }" :to="pathForTab('devices')" @click="selectNav">
                <Smartphone :size="16" class="vben-nav-icon" aria-hidden="true" />
                <span class="vben-nav-label">设备</span>
              </RouterLink>
            </div>
          </div>

          <!-- 系统 / 组织管理 -->
          <div v-if="caps.canOps || canManageUsers" class="vben-nav-group">
            <button
              type="button"
              class="vben-nav-section"
              :class="{ 'is-open': navGroupOpen('admin') }"
              :aria-expanded="navGroupOpen('admin')"
              @click="toggleNavSection('admin')"
            >
              <span class="vben-nav-section-text">{{ caps.canOps ? "系统管理" : "组织管理" }}</span>
              <ChevronRight :size="14" class="vben-nav-chevron" aria-hidden="true" />
            </button>
            <div class="vben-nav-items" :class="{ 'is-collapsed': !navGroupOpen('admin') }" :inert="!navGroupOpen('admin')">
              <RouterLink v-if="caps.canOps" class="vben-nav-item" title="运维" :class="{ active: activeTab === 'ops' }" :to="pathForTab('ops')" @click="selectNav">
                <Settings :size="16" class="vben-nav-icon" aria-hidden="true" />
                <span class="vben-nav-label">运维</span>
              </RouterLink>
              <RouterLink v-if="canManageUsers" class="vben-nav-item" title="审计" :class="{ active: activeTab === 'audit' }" :to="pathForTab('audit')" @click="selectNav">
                <History :size="16" class="vben-nav-icon" aria-hidden="true" />
                <span class="vben-nav-label">审计</span>
              </RouterLink>
              <RouterLink v-if="canManageUsers" class="vben-nav-item" title="用户" :class="{ active: activeTab === 'users' }" :to="pathForTab('users')" @click="selectNav">
                <Users :size="16" class="vben-nav-icon" aria-hidden="true" />
                <span class="vben-nav-label">用户</span>
              </RouterLink>
            </div>
          </div>
        </nav>

        <!-- Vben v5 Bottom Collapse Rail -->
        <div class="vben-sidebar-footer">
          <button
            type="button"
            class="vben-rail-btn"
            :title="sidebarCollapsed ? '展开侧栏' : '折叠侧栏'"
            aria-controls="app-sidebar"
            @click="toggleSidebar"
          >
            <ChevronsRight v-if="sidebarCollapsed" :size="16" aria-hidden="true" />
            <ChevronsLeft v-else :size="16" aria-hidden="true" />
          </button>
        </div>
      </aside>

      <!-- Right Workspace Area -->
      <div class="vben-main-wrap" :inert="mobileDrawerOpen">
        <!-- 50px Vben Topbar -->
        <header class="vben-topbar">
          <div class="vben-topbar-left">
            <button
              type="button"
              class="vben-icon-btn"
              ref="sidebarToggle"
              :title="sidebarCollapsed ? '展开侧栏' : '折叠侧栏'"
              aria-controls="app-sidebar"
              :aria-expanded="!sidebarCollapsed"
              @click="toggleSidebar"
            >
              <PanelLeftOpen v-if="sidebarCollapsed" :size="17" aria-hidden="true" />
              <PanelLeftClose v-else :size="17" aria-hidden="true" />
            </button>

            <nav class="vben-breadcrumb" aria-label="当前位置">
              <template v-if="showSectionCrumb">
                <span class="vben-bc-parent">{{ sectionCrumb }}</span>
                <ChevronRight :size="14" class="vben-bc-sep" aria-hidden="true" />
              </template>
              <span class="vben-bc-active">{{ currentBreadcrumb }}</span>
            </nav>
          </div>

          <div class="vben-topbar-right">
            <!-- Workspace Org / Project Context Pill -->
            <div class="vben-context-pill" role="group" aria-label="组织与项目上下文">
              <OrgSelect />
              <span class="vben-context-sep" aria-hidden="true"></span>
              <ProjectSelect />
            </div>

            <!-- Ops Health Indicator -->
            <div
              v-if="caps.canOps"
              class="vben-health-badge"
              :class="healthOk === true ? 'ok' : healthOk === false ? 'bad' : 'pending'"
              title="平台服务健康状态"
            >
              <span class="vben-health-dot"></span>
              <span>{{ healthOk === true ? "API 正常" : healthOk === false ? "服务异常" : "检测中" }}</span>
            </div>

            <div class="vben-utility-group">
              <VbenCommandSearch />
              <ThemeToggle />

              <button
                type="button"
                class="vben-icon-btn"
                :disabled="refreshingPage"
                title="刷新当前页数据"
                aria-label="刷新"
                @click="refreshCurrentPage"
              >
                <RotateCw :size="16" :class="{ 'is-spinning': refreshingPage }" aria-hidden="true" />
              </button>

              <DesignChatPanel inline />

              <!-- User Avatar Dropdown (Vben v5 style) -->
              <div class="vben-user-menu-wrap">
                <button
                  type="button"
                  class="vben-user-trigger"
                  :aria-expanded="userMenuOpen"
                  aria-haspopup="menu"
                  :title="`${user?.username || ''} (${platformRoleLabel(user?.role)})`"
                  @click="userMenuOpen = !userMenuOpen"
                >
                  <span class="vben-avatar">
                    {{ userInitials }}
                    <span class="vben-avatar-online" aria-hidden="true"></span>
                  </span>
                  <span class="vben-user-name">{{ user?.username }}</span>
                </button>

                <div v-if="userMenuOpen" class="vben-user-dropdown" role="menu">
                  <div class="vben-user-dropdown-head">
                    <span class="vben-avatar lg">{{ userInitials }}</span>
                    <div class="vben-user-meta">
                      <strong>{{ user?.username }}</strong>
                      <span>{{ platformRoleLabel(user?.role) }}</span>
                    </div>
                  </div>
                  <div class="vben-dropdown-divider"></div>
                  <button type="button" class="vben-dropdown-item danger" role="menuitem" @click="handleLogout">
                    <LogOut :size="15" aria-hidden="true" />
                    <span>退出系统</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </header>

        <!-- 38px Vben Multi-Tab Bar -->
        <VbenTabBar :refreshing="refreshingPage" @refresh="refreshCurrentPage" />

        <!-- Invite Banner Slot -->
        <div class="invite-slot">
          <InviteAcceptCard />
        </div>

        <!-- Global Error Banner -->
        <div v-if="error" class="vben-error-banner" role="alert">
          <AlertCircle :size="16" aria-hidden="true" />
          <span class="vben-error-text">{{ error }}</span>
          <button type="button" class="vben-error-close" aria-label="关闭错误提示" @click="error = ''">&times;</button>
        </div>

        <!-- Main Deep Canvas Workspace -->
        <main id="page-main" ref="mainContent" class="vben-page-body" tabindex="-1">
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
    </div>

    <AppNotifyHost />
    <template v-if="loggedIn">
      <ReserveDeviceDialog />
      <RemoteDeviceDialog />
      <JobReportViewer />
    </template>
  </a-config-provider>
</template>

<style>
.skip-link {
  position: fixed;
  left: -9999px;
  top: 8px;
  z-index: 9999;
  padding: 6px 12px;
  background: var(--vben-primary);
  color: #fff;
  border-radius: 6px;
}
.skip-link:focus {
  left: 8px;
}

.vben-hydrating {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--vben-bg-deep);
}
.vben-hydrating-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 28px 36px;
  border-radius: 12px;
  background: var(--vben-bg-surface);
  border: 1px solid var(--vben-border);
  box-shadow: var(--vben-shadow-card);
}
.vben-hydrating-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--vben-fg-strong);
}
.vben-hydrating-sub {
  font-size: 13px;
  color: var(--vben-fg-muted);
}

/* —— Vben Shell Layout —— */
.vben-shell {
  display: flex;
  height: 100vh;
  width: 100%;
  overflow: hidden;
  background: var(--vben-bg-deep);
}

.vben-sidebar {
  width: var(--vben-sidebar-w, 224px);
  background: var(--vben-bg-surface);
  border-right: 1px solid var(--vben-border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  z-index: 100;
  transition: width 0.2s cubic-bezier(0.2, 0, 0, 1);
  overflow: hidden;
}

.vben-shell.is-collapsed .vben-sidebar {
  width: var(--vben-sidebar-rail, 64px);
}

.vben-sidebar-brand {
  height: var(--vben-topbar-h, 50px);
  padding: 0 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  border-bottom: 1px solid var(--vben-border-soft);
  flex-shrink: 0;
  overflow: hidden;
}

.vben-shell.is-collapsed .vben-sidebar-brand {
  justify-content: center;
  padding: 0;
}

.vben-brand-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--vben-fg-strong);
  letter-spacing: -0.02em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.vben-shell.is-collapsed .vben-brand-title {
  display: none;
}

.vben-sidebar-nav {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 10px 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  scrollbar-width: thin;
}

.vben-nav-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 4px;
}

.vben-nav-section {
  appearance: none;
  border: none;
  background: transparent;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px 4px;
  font-size: var(--vben-fs-sm, 13px);
  font-weight: 600;
  color: var(--nav-section);
  cursor: pointer;
  border-radius: 6px;
  transition: color 0.15s ease;
}

.vben-nav-section:hover {
  color: var(--vben-fg);
}

.vben-nav-chevron {
  transition: transform 0.18s ease;
  opacity: 0.7;
}

.vben-nav-section.is-open .vben-nav-chevron {
  transform: rotate(90deg);
}

.vben-shell.is-collapsed .vben-nav-section {
  display: none;
}

.vben-nav-items {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.vben-nav-items.is-collapsed {
  display: none;
}

.vben-nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 40px;
  padding: 0 12px;
  border-radius: 8px;
  font-size: var(--vben-fs-nav, 14.5px);
  font-weight: 500;
  color: var(--sidebar-muted);
  text-decoration: none;
  white-space: nowrap;
  transition: background-color 0.15s ease, color 0.15s ease;
}

.vben-nav-item:hover {
  background: var(--nav-hover);
  color: var(--vben-fg-strong);
}

.vben-nav-item.active {
  background: var(--nav-active-bg);
  color: var(--nav-active-fg);
  font-weight: 600;
}

.vben-nav-icon {
  flex-shrink: 0;
}

.vben-shell.is-collapsed .vben-nav-item {
  justify-content: center;
  padding: 0;
}

.vben-shell.is-collapsed .vben-nav-label {
  display: none;
}

.vben-sidebar-footer {
  height: 40px;
  border-top: 1px solid var(--vben-border-soft);
  padding: 0 10px;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  flex-shrink: 0;
}

.vben-shell.is-collapsed .vben-sidebar-footer {
  justify-content: center;
}

.vben-rail-btn {
  appearance: none;
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
  padding: 0;
  transition: background-color 0.15s ease, color 0.15s ease;
}

.vben-rail-btn:hover {
  background: var(--vben-bg-hover);
  color: var(--vben-fg-strong);
}

/* —— Right Workspace —— */
.vben-main-wrap {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.vben-topbar {
  height: var(--vben-topbar-h, 50px);
  background: var(--vben-bg-surface);
  border-bottom: 1px solid var(--vben-border);
  padding: 0 16px 0 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-shrink: 0;
}

.vben-topbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.vben-icon-btn {
  appearance: none;
  border: none;
  background: transparent;
  color: var(--vben-fg);
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  padding: 0;
  flex-shrink: 0;
  transition: background-color 0.15s ease, color 0.15s ease;
}

.vben-icon-btn:hover:not(:disabled) {
  background: var(--vben-bg-hover);
  color: var(--vben-primary);
}

.vben-icon-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.vben-breadcrumb {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--vben-fs-base, 15px);
  min-width: 0;
  white-space: nowrap;
}

.vben-bc-parent {
  color: var(--vben-fg-muted);
}

.vben-bc-sep {
  color: var(--vben-fg-subtle);
  flex-shrink: 0;
}

.vben-bc-active {
  color: var(--vben-fg-strong);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
}

.vben-topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.vben-context-pill {
  display: inline-flex;
  align-items: center;
  background: var(--vben-bg-muted);
  border: 1px solid var(--vben-border);
  border-radius: 8px;
  padding: 2px;
  gap: 2px;
}

.vben-context-sep {
  width: 1px;
  height: 16px;
  background: var(--vben-border);
  flex-shrink: 0;
}

.vben-health-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  border: 1px solid var(--vben-border);
  background: var(--vben-bg-muted);
  color: var(--vben-fg-muted);
  white-space: nowrap;
}

.vben-health-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--vben-fg-subtle);
}

.vben-health-badge.ok {
  color: var(--ok-soft-fg);
  background: var(--ok-soft-bg);
  border-color: var(--ok-soft-border);
}
.vben-health-badge.ok .vben-health-dot {
  background: #10b981;
}
.vben-health-badge.bad {
  color: var(--danger-soft-fg);
  background: var(--danger-soft-bg);
  border-color: var(--danger-soft-border);
}
.vben-health-badge.bad .vben-health-dot {
  background: #ef4444;
}

.vben-utility-group {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

/* User Avatar Dropdown */
.vben-user-menu-wrap {
  position: relative;
  margin-left: 4px;
}

.vben-user-trigger {
  appearance: none;
  border: none;
  background: transparent;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 34px;
  padding: 2px 8px 2px 4px;
  border-radius: 999px;
  cursor: pointer;
  color: var(--vben-fg);
  transition: background-color 0.15s ease;
}

.vben-user-trigger:hover {
  background: var(--vben-bg-hover);
}

.vben-avatar {
  position: relative;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: linear-gradient(135deg, #006be6, #4f46e5);
  color: #ffffff;
  font-size: 11px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.vben-avatar.lg {
  width: 36px;
  height: 36px;
  font-size: 13px;
}

.vben-avatar-online {
  position: absolute;
  right: -1px;
  bottom: -1px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22c55e;
  border: 1.5px solid var(--vben-bg-surface);
}

.vben-user-name {
  font-size: 13px;
  font-weight: 500;
  max-width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.vben-user-dropdown {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  min-width: 200px;
  padding: 6px;
  border-radius: 10px;
  background: var(--vben-bg-surface);
  border: 1px solid var(--vben-border);
  box-shadow: var(--vben-shadow-elevated);
  z-index: 300;
}

.vben-user-dropdown-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
}

.vben-user-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.vben-user-meta strong {
  font-size: 14px;
  color: var(--vben-fg-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.vben-user-meta span {
  font-size: 12px;
  color: var(--vben-fg-muted);
}

.vben-dropdown-divider {
  height: 1px;
  background: var(--vben-border-soft);
  margin: 4px 0;
}

.vben-dropdown-item {
  appearance: none;
  border: none;
  background: transparent;
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 13px;
  color: var(--vben-fg);
  cursor: pointer;
}

.vben-dropdown-item:hover {
  background: var(--vben-bg-hover);
}

.vben-dropdown-item.danger {
  color: #ef4444;
}
.vben-dropdown-item.danger:hover {
  background: rgba(239, 68, 68, 0.1);
}

.vben-error-banner {
  margin: 12px 16px 0;
  padding: 10px 14px;
  border-radius: 8px;
  background: var(--danger-soft-bg);
  border: 1px solid var(--danger-soft-border);
  color: var(--danger-soft-fg);
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}

.vben-error-text {
  flex: 1;
  min-width: 0;
}

.vben-error-close {
  appearance: none;
  border: none;
  background: transparent;
  color: inherit;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}

.vben-page-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 16px;
  background: var(--vben-bg-deep);
}

.content-wrapper {
  width: 100%;
  max-width: none;
  margin: 0;
  min-width: 0;
}

.vben-sidebar-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  z-index: 90;
}

.is-spinning {
  animation: vben-app-spin 0.8s linear infinite;
}

@keyframes vben-app-spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1100px) {
  .vben-health-badge,
  .vben-user-name {
    display: none;
  }
}

@media (max-width: 900px) {
  .vben-sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    transform: translateX(0);
    transition: transform 0.2s ease;
  }
  .vben-shell.is-collapsed .vben-sidebar {
    width: var(--vben-sidebar-w, 224px);
    transform: translateX(-100%);
  }
  .vben-topbar {
    padding: 0 10px;
  }
  .vben-context-pill {
    max-width: 240px;
  }
  .vben-page-body {
    padding: 12px;
  }
}
</style>

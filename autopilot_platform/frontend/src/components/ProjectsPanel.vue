<script setup lang="ts">
defineOptions({ name: "ProjectsPanel" });


import { computed, onMounted, ref, watch } from "vue";

import { useRoute } from "vue-router";

import { storeToRefs } from "pinia";
import { useProjectsStore } from "../stores/projectsStore";

import { useCapabilities } from "../composables/useCapabilities";

import { notify } from "../composables/useNotify";

import { goToHubSection } from "../navigation/tabSync";

import { router } from "../router";

import ProjectList from "./projects/ProjectList.vue";

import ProjectWorkspace from "./projects/ProjectWorkspace.vue";

import CreateProjectModal from "./projects/CreateProjectModal.vue";

import OrgSettingsSection from "./projects/OrgSettingsSection.vue";



type Section = "org" | "collab";



const projectsStore = useProjectsStore();
const { filterOrgId, filterProjectId, orgs, projects } = storeToRefs(projectsStore);

const caps = useCapabilities();

const route = useRoute();

const createOpen = ref(false);

const userPickedSection = ref(false);



const hasOrgContext = computed(() => Boolean((filterOrgId.value || "").trim()));

const hasOrgs = computed(() => (orgs.value || []).length > 0);

const hasProjectCtx = computed(

  () => Boolean((filterProjectId.value || "").trim()) || (projects.value || []).length > 0,

);



/**

 * 默认分区：

 * - 平台/组织管理员且未选组织、无项目 → 组织页

 * - 其余（含普通成员、无组织）→ 项目协作，避免诱导「去创建组织」

 */

function resolveDefaultSection(): Section {

  if (

    (caps.canCreateOrg || caps.canManageAnyOrg) &&

    !hasOrgContext.value &&

    !hasProjectCtx.value

  ) {

    return "org";

  }

  return "collab";

}



const section = ref<Section>(
  (() => {
    const q = typeof route.query.section === "string" ? route.query.section.trim() : "";
    if (q === "org" || q === "collab") return q;
    return resolveDefaultSection();
  })(),
);



onMounted(() => {

  if (!userPickedSection.value) {

    const q = typeof route.query.section === "string" ? route.query.section.trim() : "";

    if (q === "org" || q === "collab") {

      section.value = q;

    } else {

      section.value = resolveDefaultSection();

    }

  }

});



watch(

  () => route.query.section,

  (raw) => {

    const q = typeof raw === "string" ? raw.trim() : "";

    if (q === "org" || q === "collab") section.value = q;

  },
);



// 挂载时 orgs 可能尚未刷新：列表从空变为有数据时按规则重定位一次（用户已手动切换则尊重）

watch(hasOrgs, (now, prev) => {

  if (userPickedSection.value) return;

  if (!prev && now) {

    section.value = resolveDefaultSection();

  }

});



function setSection(next: Section) {

  userPickedSection.value = true;

  section.value = next;

  goToHubSection(router, "projects", next);

}



function goOrgSettings() {

  setSection("org");

}



function openCreate() {

  if (!hasOrgContext.value) {

    if (caps.canCreateOrg || caps.canManageAnyOrg) {

      goOrgSettings();

      return;

    }

    notify("请先在顶栏选择已加入的组织，再新建项目", "warn");

    return;

  }

  if (!caps.canCreateProject) {

    notify("当前组织不允许你创建项目，请联系组织负责人或管理员", "warn");

    return;

  }

  createOpen.value = true;

}



function onSubnavKeydown(ev: KeyboardEvent) {

  if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;

  ev.preventDefault();

  const order: Section[] = ["org", "collab"];

  const idx = order.indexOf(section.value);

  const next =

    ev.key === "ArrowRight"

      ? order[(idx + 1) % order.length]

      : order[(idx - 1 + order.length) % order.length];

  setSection(next);

  const btn = (ev.currentTarget as HTMLElement).querySelector<HTMLButtonElement>(

    `[data-section="${next}"]`,

  );

  btn?.focus();

}

</script>



<template>

  <section class="panel page-stack projects-panel">

    <header class="page-hero">

      <div class="page-hero-copy">

        <h2>项目</h2>

        <p class="lede">

          <template v-if="caps.canCreateOrg || caps.canManageAnyOrg">

            管理组织和项目，以及成员。可用顶栏切换当前范围。

          </template>

          <template v-else>

            在顶栏选择组织和项目后，可在此查看协作内容。组织由管理员创建并邀请成员加入。

          </template>

        </p>

      </div>

      <div class="page-hero-actions">

        <button

          v-if="!hasOrgContext && (caps.canCreateOrg || caps.canManageAnyOrg)"

          type="button"

          class="primary"

          @click="goOrgSettings"

        >

          先配置组织 / 事业部

        </button>

        <button

          v-else-if="hasOrgContext && caps.canCreateProject"

          type="button"

          class="primary"

          title="在当前组织下新建项目"

          @click="openCreate"

        >

          新建项目

        </button>

      </div>

    </header>



    <nav

      class="subnav"

      role="tablist"

      aria-label="项目与协作分区"

      @keydown="onSubnavKeydown"

    >

      <button

        type="button"

        class="subnav-item"

        role="tab"

        data-section="org"

        id="projects-tab-org"

        :class="{ active: section === 'org' }"

        :aria-selected="section === 'org'"

        :tabindex="section === 'org' ? 0 : -1"

        aria-controls="projects-panel-org"

        @click="setSection('org')"

      >

        组织 / 事业部

      </button>

      <button

        type="button"

        class="subnav-item"

        role="tab"

        data-section="collab"

        id="projects-tab-collab"

        :class="{ active: section === 'collab' }"

        :aria-selected="section === 'collab'"

        :tabindex="section === 'collab' ? 0 : -1"

        aria-controls="projects-panel-collab"

        @click="setSection('collab')"

      >

        项目协作

      </button>

    </nav>



    <div

      v-if="section === 'org'"

      id="projects-panel-org"

      role="tabpanel"

      aria-labelledby="projects-tab-org"

    >

      <OrgSettingsSection />

    </div>



    <div

      v-else

      id="projects-panel-collab"

      class="collab-layout"

      role="tabpanel"

      aria-labelledby="projects-tab-collab"

    >

      <ProjectList @create="openCreate" @configure-org="goOrgSettings" />

      <ProjectWorkspace />

    </div>



    <CreateProjectModal :open="createOpen" @close="createOpen = false" />

  </section>

</template>



<style scoped>

.projects-panel {
  width: 100%;
  max-width: none;
  min-width: 0;
}



.subnav {

  display: inline-flex;

  align-items: center;

  gap: 0.25rem;

  padding: 0.25rem;

  background: var(--surface-primary);

  border: 1px solid var(--line);

  border-radius: var(--radius-md);

  width: fit-content;

  max-width: 100%;

}



.subnav-item {

  appearance: none;

  border: none;

  background: transparent;

  color: var(--muted);

  font: inherit;

  font-size: 0.82rem;

  font-weight: 650;

  padding: 0.4rem 0.9rem;

  border-radius: var(--radius-sm);

  cursor: pointer;

  transition: var(--transition);

}



.subnav-item:hover {

  color: var(--text);

  background: var(--action-hover);

}



.subnav-item:focus-visible {

  outline: none;

  box-shadow: var(--focus-ring);

}



.subnav-item.active {

  color: var(--nav-active-fg);

  background: var(--nav-active-bg);

}



.collab-layout {
  display: grid;
  grid-template-columns: minmax(18rem, 26rem) minmax(0, 1fr);
  gap: 1rem;
  align-items: stretch;
  width: 100%;
  min-height: min(36rem, calc(100dvh - 16rem));
}



@media (max-width: 900px) {

  .collab-layout {

    grid-template-columns: 1fr;

  }

}

</style>



import { createApp } from "vue";
import App from "./App.vue";
import "./styles.css";
import { applyStoredTheme } from "./composables/useTheme";
import { loadPlatformBootstrap } from "./api/bootstrap";
import { pinia } from "./stores";
import { router } from "./router";
import { installRouteGuards } from "./router/guards";
import { wirePlatformRuntime } from "./composables/platformRuntime";

applyStoredTheme();
void loadPlatformBootstrap().finally(() => {
  const app = createApp(App);
  app.use(pinia);
  app.use(router);
  wirePlatformRuntime(router);
  installRouteGuards(router);
  app.mount("#app");
});

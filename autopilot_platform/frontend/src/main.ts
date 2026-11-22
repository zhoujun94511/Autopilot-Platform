import { createApp } from "vue";
import { ConfigProvider } from "ant-design-vue";
import "ant-design-vue/dist/reset.css";
import App from "./App.vue";
import "./styles.css";
import "./styles/vben-theme.css";
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
  app.use(ConfigProvider);
  wirePlatformRuntime(router);
  installRouteGuards(router);
  app.mount("#app");
});

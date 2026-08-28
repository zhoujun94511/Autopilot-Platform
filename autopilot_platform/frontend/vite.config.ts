import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";
import { resolve } from "node:path";

const repoRoot = resolve(__dirname, "../..");

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, repoRoot, "");
  const backendPort = String(env.MC_PORT || process.env.MC_PORT || "8000");
  const proxyTarget = `http://127.0.0.1:${backendPort}`;

  return {
    plugins: [vue()],
    server: {
      port: 5173,
      watch: {
        // 仓库根有大量 Python；Windows 目录变更溢出时 Vite 会误报全量文件并在 HMR
        // 与 server restart 竞态里崩掉（hot.error on undefined）。
        ignored: [
          "**/.git/**",
          "**/.venv/**",
          "**/logs/**",
          "**/__pycache__/**",
          "**/*.py",
          "**/*.pyc",
        ],
      },
      proxy: {
        "/api": {
          target: proxyTarget,
          changeOrigin: true,
          ws: true,
        },
        "/health": proxyTarget,
        "/metrics": proxyTarget,
      },
    },
    build: {
      outDir: resolve(__dirname, "dist"),
      emptyOutDir: true,
      assetsDir: "assets",
    },
  };
});

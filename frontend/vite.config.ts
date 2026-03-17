import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // VITE_API_PROXY_TARGET: where the Vite dev server proxies /api requests.
  // Defaults to the Docker service name; override to http://localhost:8000
  // when running the frontend outside Docker.
  const apiProxyTarget = env.VITE_API_PROXY_TARGET ?? "http://api:8000";

  return {
    plugins: [react()],
    server: {
      host: "0.0.0.0",
      port: 5173,
      proxy: {
        "/api": {
          target: apiProxyTarget,
          changeOrigin: true,
        },
      },
    },
    resolve: {
      alias: {
        "@": "/src",
      },
    },
  };
});

import preact from "@preact/preset-vite";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const backendOrigin = env.VITE_BACKEND_ORIGIN || "http://127.0.0.1:8000";
  const host = "0.0.0.0";
  const previewPort = 4173;
  const devPort = 5173;

  return {
    plugins: [preact()],
    build: {
      // Align with tsconfig.json "target": "ES2020" so vite and tsc target the
      // same language level and avoid duplicate down-transpilation.
      target: "es2020",
    },
    // Our smoke tests and preview helpers target fixed URLs, so fail fast on
    // port conflicts instead of silently hopping to the next available port.
    preview: {
      host,
      port: previewPort,
      strictPort: true,
    },
    server: {
      host,
      port: devPort,
      strictPort: true,
      proxy: {
        "/api": backendOrigin,
        "/static": backendOrigin,
        "/ws": {
          target: backendOrigin,
          ws: true,
        },
      },
    },
  };
});

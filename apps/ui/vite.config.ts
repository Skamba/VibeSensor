import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const backendOrigin = env.VITE_BACKEND_ORIGIN || "http://127.0.0.1:8000";

  return {
    build: {
      // Align with tsconfig.json "target": "ES2020" so vite and tsc target the
      // same language level and avoid duplicate down-transpilation.
      target: "es2020",
    },
    server: {
      host: "0.0.0.0",
      port: 5173,
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

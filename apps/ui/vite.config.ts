import { defineConfig } from "vite";

export default defineConfig({
  build: {
    // Align with tsconfig.json "target": "ES2020" so vite and tsc target the
    // same language level and avoid duplicate down-transpilation.
    target: "es2020",
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
  },
});

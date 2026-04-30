import preact from "@preact/preset-vite";
import { visualizer } from "rollup-plugin-visualizer";
import { defineConfig, loadEnv, type PluginOption } from "vite";

const VENDOR_CHUNK_PACKAGE_PATHS = [
  "/preact/",
  "/@preact/signals/",
  "/@preact/signals-core/",
] as const;

function matchesChunkPackage(id: string, packagePaths: readonly string[]): boolean {
  return packagePaths.some((packagePath) => id.includes(packagePath));
}

function resolveManualChunk(id: string): string | undefined {
  const normalizedId = id.replace(/\\/g, "/");
  if (!normalizedId.includes("/node_modules/")) {
    return undefined;
  }
  if (matchesChunkPackage(normalizedId, VENDOR_CHUNK_PACKAGE_PATHS)) {
    return "vendor";
  }
  return undefined;
}

function shouldOpenBundleAnalysis(): boolean {
  if (process.env.CI === "true") {
    return false;
  }
  if (process.platform === "darwin" || process.platform === "win32") {
    return true;
  }
  return Boolean(process.env.DISPLAY || process.env.WAYLAND_DISPLAY);
}

function buildPlugins(mode: string): PluginOption[] {
  const plugins: PluginOption[] = [preact()];
  if (mode === "analyze") {
    plugins.push(
      visualizer({
        brotliSize: true,
        filename: "dist/bundle-analysis.html",
        gzipSize: true,
        open: shouldOpenBundleAnalysis(),
      }),
    );
  }
  return plugins;
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const backendOrigin = env.VITE_BACKEND_ORIGIN || "http://127.0.0.1:8000";
  const host = "0.0.0.0";
  const previewPort = 4173;
  const devPort = 5173;

  return {
    plugins: buildPlugins(mode),
    build: {
      // Align with tsconfig.json "target": "ES2022" so vite and tsc target the
      // same language level and avoid duplicate down-transpilation.
      target: "es2022",
      rollupOptions: {
        output: {
          manualChunks: resolveManualChunk,
        },
      },
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

import { chromium } from "@playwright/test";
import { spawn } from "node:child_process";

const DEFAULT_BROWSER_ARGS = [
  "--no-sandbox",
  "--disable-setuid-sandbox",
  "--disable-dev-shm-usage",
];
const SERVER_READY_DELAY_MS = 300;

export async function startPreviewServer(cwd, { port, timeoutMs }) {
  return new Promise((resolve, reject) => {
    const server = spawn(
      "node",
      [
        "node_modules/.bin/vite",
        "preview",
        "--host",
        "0.0.0.0",
        "--strictPort",
        "--port",
        String(port),
      ],
      { cwd, stdio: ["ignore", "pipe", "pipe"] },
    );
    let started = false;

    const settleReady = () => {
      if (started) {
        return;
      }
      started = true;
      clearTimeout(timeout);
      server.stdout.off("data", onOutput);
      server.stderr.off("data", onOutput);
      server.off("error", onError);
      server.off("exit", onExit);
      setTimeout(() => resolve(server), SERVER_READY_DELAY_MS);
    };

    const onOutput = (data) => {
      if (data.toString().includes(String(port))) {
        settleReady();
      }
    };

    const onError = (error) => {
      if (started) {
        return;
      }
      clearTimeout(timeout);
      reject(error);
    };

    const onExit = (code) => {
      if (started) {
        return;
      }
      clearTimeout(timeout);
      reject(
        new Error(
          `Preview server exited before becoming ready (code ${code ?? "unknown"})`,
        ),
      );
    };

    const timeout = setTimeout(() => {
      if (started) {
        return;
      }
      server.kill();
      reject(new Error(`Preview server start timeout on port ${port}`));
    }, timeoutMs);

    server.stdout.on("data", onOutput);
    server.stderr.on("data", onOutput);
    server.on("error", onError);
    server.on("exit", onExit);
  });
}

export async function launchChromiumBrowser(options = {}) {
  try {
    return await chromium.launch({
      ...options,
      args: [...DEFAULT_BROWSER_ARGS, ...(options.args ?? [])],
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (message.toLowerCase().includes("executable doesn't exist")) {
      throw new Error(
        "Playwright browser not installed. Run: npx playwright install chromium",
      );
    }
    throw error;
  }
}

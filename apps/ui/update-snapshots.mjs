/**
 * Regenerates Playwright snapshot baselines using the available chromium binary.
 * Run with: node update-snapshots.mjs
 */
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

import {
  launchChromiumBrowser,
  startPreviewServer,
} from "./playwright-preview-helpers.mjs";

const CHROME_EXEC =
  "/root/.cache/ms-playwright/chromium-1194/chrome-linux/chrome";
const SERVER_PORT = 4176;
const SERVER_TIMEOUT_MS = 25_000;
const PAGE_TIMEOUT_MS = 15_000;
const SNAPSHOT_DIR = "tests/snapshots/visual.spec.ts";

const VIEWPORT_CONFIGS = [
  ["laptop-light", { width: 1280, height: 800 }, "light"],
  ["laptop-dark", { width: 1280, height: 800 }, "dark"],
  ["tablet-light", { width: 810, height: 1080 }, "light"],
  ["tablet-dark", { width: 810, height: 1080 }, "dark"],
];

function savePng(path, buf) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, buf);
  console.log("  Written:", path);
}

async function main() {
  const cwd = fileURLToPath(new URL(".", import.meta.url));
  let server;
  let browser;

  try {
    server = await startPreviewServer(cwd, {
      port: SERVER_PORT,
      timeoutMs: SERVER_TIMEOUT_MS,
    });
    console.log("Preview server up on port", SERVER_PORT);

    browser = await launchChromiumBrowser({ executablePath: CHROME_EXEC });

    // ----- Snapshot: live-view (laptop-light) -----
    console.log("\nCapturing live-view snapshots...");
    for (const [projectName, viewport, colorScheme] of VIEWPORT_CONFIGS) {
      const ctx = await browser.newContext({ viewport, colorScheme });
      const page = await ctx.newPage();
      await page.goto(`http://localhost:${SERVER_PORT}/?demo=1`, {
        timeout: PAGE_TIMEOUT_MS,
      });
      await page.waitForFunction(
        () => {
          const connected = document.querySelector("#liveConnectedSensors [data-value]");
          const activeCar = document.querySelector("#liveActiveCar [data-value]");
          return Boolean(connected?.textContent?.trim() && activeCar?.textContent?.trim());
        },
        { timeout: PAGE_TIMEOUT_MS },
      );
      const buf = await page.screenshot({
        fullPage: true,
        animations: "disabled",
      });
      savePng(`${SNAPSHOT_DIR}/live-view-${projectName}.png`, buf);
      await ctx.close();
    }

    // ----- Snapshot: settings-analysis -----
    console.log("\nCapturing settings-analysis snapshots...");
    for (const [projectName, viewport, colorScheme] of VIEWPORT_CONFIGS) {
      const ctx = await browser.newContext({ viewport, colorScheme });
      const page = await ctx.newPage();
      await page.goto(`http://localhost:${SERVER_PORT}/?demo=1`, {
        timeout: PAGE_TIMEOUT_MS,
      });
      await page.click("#tab-settings");
      await page.click('[data-settings-tab="analysisTab"]');
      await page.waitForSelector("#analysisTab.active", { timeout: 8_000 });
      const buf = await page.screenshot({
        fullPage: true,
        animations: "disabled",
      });
      savePng(`${SNAPSHOT_DIR}/settings-analysis-${projectName}.png`, buf);
      await ctx.close();
    }

    console.log("\nAll snapshots updated.");
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (server) server.kill();
  }
}

main().catch((err) => {
  console.error("Snapshot update failed:", err.message);
  process.exit(1);
});

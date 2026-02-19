/**
 * Regenerates Playwright snapshot baselines using the available chromium binary.
 * Run with: node update-snapshots.mjs
 */
import { chromium } from "playwright-core";
import { spawn } from "child_process";
import { writeFileSync, mkdirSync } from "fs";
import { dirname } from "path";

const CHROME_EXEC = "/root/.cache/ms-playwright/chromium-1194/chrome-linux/chrome";
const SERVER_PORT = 4176;
const SERVER_TIMEOUT_MS = 25_000;
const PAGE_TIMEOUT_MS = 15_000;
const SNAPSHOT_DIR = "tests/snapshots/visual.spec.ts";

async function startServer(cwd) {
  return new Promise((resolve, reject) => {
    const server = spawn(
      "node",
      ["node_modules/.bin/vite", "preview", "--host", "0.0.0.0", "--port", String(SERVER_PORT)],
      { cwd, stdio: ["ignore", "pipe", "pipe"] },
    );
    let started = false;
    const timer = setTimeout(() => {
      if (!started) { server.kill(); reject(new Error("Server start timeout")); }
    }, SERVER_TIMEOUT_MS);
    server.stdout.on("data", (d) => {
      if (!started && d.toString().includes(String(SERVER_PORT))) {
        started = true;
        clearTimeout(timer);
        setTimeout(() => resolve(server), 300);
      }
    });
    server.on("error", reject);
  });
}

function savePng(path, buf) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, buf);
  console.log("  Written:", path);
}

async function main() {
  const cwd = new URL(".", import.meta.url).pathname;
  let server;
  let browser;

  try {
    server = await startServer(cwd);
    console.log("Preview server up on port", SERVER_PORT);

    browser = await chromium.launch({
      executablePath: CHROME_EXEC,
      args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
    });

    // ----- Snapshot: live-view (laptop-light) -----
    console.log("\nCapturing live-view snapshots...");
    for (const [projectName, viewport, colorScheme] of [
      ["laptop-light", { width: 1280, height: 800 }, "light"],
      ["laptop-dark",  { width: 1280, height: 800 }, "dark"],
      ["tablet-light", { width: 810, height: 1080 }, "light"],
      ["tablet-dark",  { width: 810, height: 1080 }, "dark"],
    ]) {
      const ctx = await browser.newContext({ viewport, colorScheme });
      const page = await ctx.newPage();
      await page.goto(`http://localhost:${SERVER_PORT}/?demo=1`, { timeout: PAGE_TIMEOUT_MS });
      await page.waitForSelector(".car-map-dot--visible", { timeout: PAGE_TIMEOUT_MS });
      await page.waitForFunction(
        () => document.querySelector(".log-row .log-time") !== null,
        { timeout: PAGE_TIMEOUT_MS },
      );
      const buf = await page.screenshot({ fullPage: true, animations: "disabled" });
      savePng(`${SNAPSHOT_DIR}/live-view-${projectName}.png`, buf);
      await ctx.close();
    }

    // ----- Snapshot: settings-analysis -----
    console.log("\nCapturing settings-analysis snapshots...");
    for (const [projectName, viewport, colorScheme] of [
      ["laptop-light", { width: 1280, height: 800 }, "light"],
      ["laptop-dark",  { width: 1280, height: 800 }, "dark"],
      ["tablet-light", { width: 810, height: 1080 }, "light"],
      ["tablet-dark",  { width: 810, height: 1080 }, "dark"],
    ]) {
      const ctx = await browser.newContext({ viewport, colorScheme });
      const page = await ctx.newPage();
      await page.goto(`http://localhost:${SERVER_PORT}/?demo=1`, { timeout: PAGE_TIMEOUT_MS });
      await page.click('[data-view="settingsView"]');
      await page.click('[data-settings-tab="analysisTab"]');
      await page.waitForSelector("#analysisTab.active", { timeout: 8_000 });
      const buf = await page.screenshot({ fullPage: true, animations: "disabled" });
      savePng(`${SNAPSHOT_DIR}/settings-analysis-${projectName}.png`, buf);
      await ctx.close();
    }

    console.log("\nAll snapshots updated.");
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (server) server.kill();
  }
}

main().catch((err) => { console.error("Snapshot update failed:", err.message); process.exit(1); });

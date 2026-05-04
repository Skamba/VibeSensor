/**
 * Screenshot utility for VibeSensor UI.
 * Takes a screenshot of the live view in demo mode.
 * Usage: node take-screenshot.mjs [output-path]
 * Exits with code 1 on failure (timeout, no graph data, etc.)
 */
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { launchChromiumBrowser, startPreviewServer } from "./playwright-preview-helpers.mjs";

const OUTPUT_PATH = process.argv[2] || "/tmp/vibesensor-screenshot.png";
const SERVER_PORT = 4175;
const SERVER_TIMEOUT_MS = 20_000;
const PAGE_TIMEOUT_MS = 15_000;

async function main() {
  const cwd = fileURLToPath(new URL(".", import.meta.url));
  let server;
  let browser;
  try {
    server = await startPreviewServer(cwd, { port: SERVER_PORT, timeoutMs: SERVER_TIMEOUT_MS });
    console.log("Preview server started on port", SERVER_PORT);

    browser = await launchChromiumBrowser();
    const page = await browser.newPage();
    await page.setViewportSize({ width: 1280, height: 800 });

    await page.goto(`http://localhost:${SERVER_PORT}/?demo=1`, {
      timeout: PAGE_TIMEOUT_MS,
    });

    // Wait for car map dots (confirms demo data applied)
    await page.waitForSelector(".car-map-dot--visible", {
      timeout: PAGE_TIMEOUT_MS,
    });

    // Wait for vibration event log entry (confirms event payload applied)
    await page.waitForFunction(
      () => document.querySelector(".log-row .log-time") !== null,
      { timeout: PAGE_TIMEOUT_MS },
    );

    // Verify spectrum canvas has rendered data.
    const hasCanvas = await page.evaluate(() => {
      const canvas = document.querySelector("#specChart canvas");
      if (!canvas) return false;
      const ctx = /** @type {HTMLCanvasElement} */ (canvas).getContext("2d");
      if (!ctx) return false;
      // Sample pixels in the chart area to check for non-background color
      const imageData = ctx.getImageData(
        50,
        10,
        canvas.clientWidth - 100,
        canvas.clientHeight - 20,
      );
      const data = imageData.data;
      for (let i = 0; i < data.length; i += 4) {
        const r = data[i],
          g = data[i + 1],
          b = data[i + 2];
        // Look for any non-white, non-light-gray pixel (spectrum line color)
        if (r < 200 && (r !== g || g !== b)) return true;
      }
      return false;
    });

    if (!hasCanvas) {
      throw new Error("FAIL: Spectrum chart canvas has no visible graph data");
    }
    console.log("Graph data verified in canvas");

    const screenshot = await page.screenshot({ fullPage: true });
    writeFileSync(OUTPUT_PATH, screenshot);
    console.log("Screenshot saved to", OUTPUT_PATH);
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (server) server.kill();
  }
}

main().catch((err) => {
  console.error("Screenshot failed:", err.message);
  process.exit(1);
});

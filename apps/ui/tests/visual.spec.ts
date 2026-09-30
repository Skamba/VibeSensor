import { expect, test, type Page } from "@playwright/test";

import { defaultAnalysisSettings } from "../src/constants";
import { installSettingsRoutes, speedSourceSettings } from "./smoke.helpers";

/**
 * Screenshot the whole page without Playwright's `fullPage` capture.
 *
 * In Chromium, a `fullPage` capture under touch emulation (the tablet audit
 * projects) drops the touch emulation: `navigator.maxTouchPoints` becomes 0
 * and `(pointer: coarse)` stops matching for the rest of the page's life.
 * That switches the app out of its tablet sizing mode mid-assertion, so the
 * first capture and the retries render different layouts (e.g. 1804 px vs
 * 1761 px tall). Growing the viewport to the document height and taking a
 * plain viewport capture keeps the emulated device intact.
 */
async function expectFullPageScreenshot(
  page: Page,
  name: string,
): Promise<void> {
  const viewport = page.viewportSize();
  if (!viewport) {
    throw new Error("visual tests need a fixed viewport");
  }
  let height = viewport.height;
  // Resizing can reflow the page, so repeat until the height settles.
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const documentHeight = await page.evaluate(
      () => document.documentElement.scrollHeight,
    );
    const nextHeight = Math.max(viewport.height, documentHeight);
    if (nextHeight === height && attempt > 0) {
      break;
    }
    height = nextHeight;
    await page.setViewportSize({ width: viewport.width, height });
  }
  await expect(page).toHaveScreenshot(name);
}

/** Assert the spectrum canvas has visible coloured (non-background) pixels (i.e. plotted graph data). */
async function assertSpectrumHasData(page: Page): Promise<void> {
  await expect
    .poll(
      async () =>
        page.evaluate(() => {
          const canvas =
            document.querySelector<HTMLCanvasElement>("#specChart canvas");
          if (!canvas) return false;
          const ctx = canvas.getContext("2d");
          if (!ctx) return false;
          const w = canvas.width;
          const h = canvas.height;
          if (!w || !h) return false;
          // Sample the inner chart area (avoid axes/borders)
          const margin = Math.floor(Math.min(w, h) * 0.1);
          const imageData = ctx.getImageData(
            margin,
            margin,
            w - margin * 2,
            h - margin * 2,
          );
          const data = imageData.data;
          for (let i = 0; i < data.length; i += 4) {
            const r = data[i],
              g = data[i + 1],
              b = data[i + 2],
              a = data[i + 3];
            if (a < 128) continue; // skip transparent pixels
            // Coloured (non-grey) pixels indicate a plotted series line
            if (r < 200 && (Math.abs(r - g) > 15 || Math.abs(g - b) > 15))
              return true;
          }
          return false;
        }),
      {
        message: "Spectrum chart must contain visible graph data",
        timeout: 5_000,
      },
    )
    .toBe(true);
}

test.describe("Live view", () => {
  test("renders the live overview dashboard", async ({ page }) => {
    await page.goto("/?demo=1");

    await expect(page.locator("#dashboardView")).toHaveJSProperty(
      "hidden",
      false,
    );
    // Demo mode streams five sensors (four wheels plus the engine bay).
    await expect(page.locator("#liveSensorRoster article")).toHaveCount(5);
    await assertSpectrumHasData(page);

    await expectFullPageScreenshot(page, "live-view.png");
  });
});

test.describe("Settings view", () => {
  test("renders analysis tab", async ({ page }) => {
    // Demo mode only simulates the live feed. Opening Settings waits for the
    // speed-source and analysis settings from the server, and the preview
    // server has no backend, so serve deterministic payloads here.
    await installSettingsRoutes(page, {
      "GET /api/settings/analysis": defaultAnalysisSettings,
      "GET /api/settings/speed-source": speedSourceSettings(),
    });
    await page.goto("/?demo=1");
    await page.click('[data-view="settingsView"]');
    await page.click('[data-settings-tab="analysisTab"]');
    await expect(page.locator("#analysisTab")).toHaveJSProperty(
      "hidden",
      false,
    );
    await expect(page.locator("#analysisGuidanceHelp")).toContainText(
      "Safe starting point",
    );
    await expect(page.locator("#saveAnalysisBtn")).toBeVisible();
    await expectFullPageScreenshot(page, "settings-analysis.png");
  });
});

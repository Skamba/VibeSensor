import { test, expect } from "@playwright/test";

/** Assert the spectrum canvas has visible coloured (non-background) pixels (i.e. plotted graph data). */
async function assertSpectrumHasData(
  page: import("@playwright/test").Page,
): Promise<void> {
  await expect.poll(async () => page.evaluate(() => {
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
  }), {
    message: "Spectrum chart must contain visible graph data",
    timeout: 5_000,
  }).toBe(true);
}

test.describe("Live view", () => {
  test("renders the live overview dashboard", async ({ page }) => {
    await page.goto("/?demo=1");

    // Verify the spectrum chart has visible graph data (not just an empty canvas)
    await assertSpectrumHasData(page);

    await expect(page).toHaveScreenshot("live-view.png", { fullPage: true });
  });
});

test.describe("Settings view", () => {
  test("renders analysis tab", async ({ page }) => {
    await page.goto("/?demo=1");
    // Navigate to Settings
    await page.click('[data-view="settingsView"]');
    // Click the Analysis tab
    await page.click('[data-settings-tab="analysisTab"]');
    // Wait for the analysis panel to become the active visible tabpanel.
    await expect(page.locator("#analysisTab")).toHaveJSProperty(
      "hidden",
      false,
    );
    await expect(page).toHaveScreenshot("settings-analysis.png", {
      fullPage: true,
    });
  });
});

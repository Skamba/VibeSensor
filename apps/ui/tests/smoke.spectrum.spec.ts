import { expect, test } from "@playwright/test";

test("spectrum controls simplify the chart and update the inspector", async ({ page }) => {
  await page.goto("/?demo=1");

  const inspector = page.locator("#spectrumInspector");
  const bandToggle = page.locator("#spectrumBandToggle");
  const bandLegend = page.locator("#bandLegend");
  const allTracesChip = page.getByRole("button", { name: /All sensor traces/i });
  const sensorChip = page.getByRole("button", { name: /Front Right Wheel/i });

  await expect(bandToggle).toBeVisible();
  await expect(bandToggle).toHaveAttribute("aria-pressed", "false");
  await expect(bandLegend).toBeHidden();
  await expect(inspector).toContainText("Strongest trace:");
  await sensorChip.click();
  await expect(sensorChip).toHaveAttribute("aria-pressed", "true");
  await expect(inspector).toContainText("Focused trace:");
  await expect(inspector).toContainText("Front Right Wheel");

  await bandToggle.click();
  await expect(bandToggle).toHaveAttribute("aria-pressed", "true");
  await expect(bandToggle).toHaveText("Hide reference bands");
  await expect(bandLegend).toBeVisible();
  await expect(bandLegend).toContainText("Wheel 1x");

  await allTracesChip.click();
  await expect(allTracesChip).toHaveAttribute("aria-pressed", "true");
  await expect(sensorChip).toHaveAttribute("aria-pressed", "false");
  await expect(inspector).toContainText("Strongest trace:");
});

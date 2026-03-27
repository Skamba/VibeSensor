import { expect, test } from "@playwright/test";

test("spectrum legend focus updates the inspector", async ({ page }) => {
  await page.goto("/?demo=1");

  const inspector = page.locator("#spectrumInspector");
  const sensorChip = page.getByRole("button", { name: /Front Right Wheel/i });

  await expect(inspector).toContainText("Focus:");
  await sensorChip.click();
  await expect(sensorChip).toHaveAttribute("aria-pressed", "true");
  await expect(inspector).toContainText("Front Right Wheel");
  await sensorChip.click();
  await expect(sensorChip).toHaveAttribute("aria-pressed", "false");
  await expect(inspector).toContainText("Focus:");
});

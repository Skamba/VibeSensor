import { expect, test, type Page, type Route } from "@playwright/test";

import {
  bootLiveDashboard,
  fulfillJson,
  openAnalysisTab,
  requestPath,
} from "./smoke.helpers";

test.describe.configure({ timeout: 20_000 });

type AnalysisServer = {
  saved: Record<string, number>;
  puts: Array<Record<string, number>>;
  failPut: boolean;
  hasCar: boolean;
};

const SAVED = {
  speed_uncertainty_pct: 2.5,
  tire_diameter_uncertainty_pct: 3,
  final_drive_uncertainty_pct: 1,
  gear_uncertainty_pct: 2,
};

// Backend defaults (src/constants.ts defaultAnalysisSettings).
const DEFAULTS = {
  speed_uncertainty_pct: 1,
  tire_diameter_uncertainty_pct: 1,
  final_drive_uncertainty_pct: 0.1,
  gear_uncertainty_pct: 0.2,
};

async function bootWithAnalysisServer(page: Page, server: AnalysisServer) {
  await bootLiveDashboard(page, {
    settingsHandler: async (route: Route) => {
      const path = requestPath(route);
      if (path.startsWith("/api/settings/cars")) {
        await fulfillJson(
          route,
          server.hasCar
            ? {
                cars: [
                  {
                    id: "car-1",
                    name: "Test Hatch",
                    type: "sedan",
                    aspects: {},
                  },
                ],
                active_car_id: "car-1",
              }
            : { cars: [], active_car_id: null },
        );
        return;
      }
      if (path === "/api/settings/analysis") {
        if (route.request().method() === "PUT") {
          const body = route.request().postDataJSON() as Record<string, number>;
          server.puts.push(body);
          if (server.failPut) {
            await route.fulfill({
              status: 500,
              contentType: "application/json",
              body: JSON.stringify({ detail: "database is locked" }),
            });
            return;
          }
          server.saved = { ...server.saved, ...body };
        }
        await fulfillJson(route, server.saved);
        return;
      }
      await fulfillJson(route, {});
    },
  });
}

function createServer(overrides: Partial<AnalysisServer> = {}): AnalysisServer {
  return {
    saved: { ...SAVED },
    puts: [],
    failPut: false,
    hasCar: true,
    ...overrides,
  };
}

test("journey: analysis settings validate, confirm risky values, and reset to defaults", async ({
  page,
}) => {
  const server = createServer();
  await bootWithAnalysisServer(page, server);
  await openAnalysisTab(page);
  const speed = page.locator("#speedUncertaintyInput");
  await expect(speed).toHaveValue("2.5");

  // An empty field is rejected with focus and opened guidance.
  await speed.fill("");
  await page.locator("#saveAnalysisBtn").click();
  await expect(page.locator("#speedUncertaintyGuidance")).toContainText(
    "Enter a number for Speed Uncertainty (%).",
  );
  await expect(speed).toBeFocused();
  await expect(speed).toHaveAttribute("aria-invalid", "true");
  await expect(page.locator("#analysisGuidanceHelp")).toHaveAttribute(
    "open",
    "",
  );
  expect(server.puts).toEqual([]);

  // Values outside the guided range need a confirmation.
  await speed.fill("12");
  await expect(speed).not.toHaveAttribute("aria-invalid", "true");
  await page.locator("#saveAnalysisBtn").click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText(
    "These values are outside the guided range for everyday use:",
  );
  await dialog.getByRole("button", { name: "Cancel" }).click();
  expect(server.puts).toEqual([]);
  await page.locator("#saveAnalysisBtn").click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: "Confirm" })
    .click();
  await expect.poll(() => server.puts.length).toBe(1);
  expect(server.puts[0]).toMatchObject({ speed_uncertainty_pct: 12 });

  await page.locator("#resetAnalysisBtn").click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: "Confirm" })
    .click();
  await expect.poll(() => server.puts.length).toBe(2);
  expect(server.puts[1]).toEqual(DEFAULTS);
  await expect(speed).toHaveValue("1");
});

test("journey: a failed analysis save keeps the edits and explains why", async ({
  page,
}) => {
  const server = createServer({ failPut: true });
  await bootWithAnalysisServer(page, server);
  await openAnalysisTab(page);
  await page.locator("#gearUncertaintyInput").fill("3");
  await page.locator("#saveAnalysisBtn").click();
  await expect(page.locator("#analysisSaveFeedback")).toContainText(
    "Analysis settings were not saved.",
  );
  await expect(page.locator("#analysisSaveFeedback")).toContainText(
    "database is locked",
  );
  await expect(page.locator("#appErrorBanner")).toContainText(
    "database is locked",
  );
  await expect(page.locator("#gearUncertaintyInput")).toHaveValue("3");
});

test("journey: analysis settings stay locked until a car is active", async ({
  page,
}) => {
  await bootWithAnalysisServer(page, createServer({ hasCar: false }));
  await openAnalysisTab(page);
  await expect(page.locator("#analysisNoCarMessage")).toBeVisible();
  await expect(page.locator("#saveAnalysisBtn")).toBeDisabled();
  await expect(page.locator("#resetAnalysisBtn")).toBeDisabled();
});

import { expect, test, type Page } from "@playwright/test";

import {
  fulfillJson,
  installCommonRoutes,
  installFakeWebSocket,
  requestPath,
} from "./smoke.helpers";

test.describe.configure({ timeout: 20_000 });

type PreferenceServer = {
  language: string;
  speedUnit: string;
  puts: Array<{ path: string; body: unknown }>;
  failSpeedUnitPut: boolean;
};

async function installPreferenceRoutes(
  page: Page,
  server: PreferenceServer,
): Promise<void> {
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      const path = requestPath(route);
      const method = route.request().method();
      if (method === "PUT") {
        const body = route.request().postDataJSON() as Record<string, string>;
        server.puts.push({ path, body });
        if (path === "/api/settings/speed-unit" && server.failSpeedUnitPut) {
          await route.fulfill({
            status: 500,
            contentType: "application/json",
            body: JSON.stringify({ detail: "disk full" }),
          });
          return;
        }
        if (path === "/api/settings/language") {
          server.language = body.language;
        } else if (path === "/api/settings/speed-unit") {
          server.speedUnit = body.speed_unit;
        }
      }
      if (path === "/api/settings/language") {
        await fulfillJson(route, { language: server.language });
        return;
      }
      if (path === "/api/settings/speed-unit") {
        await fulfillJson(route, { speed_unit: server.speedUnit });
        return;
      }
      if (path.startsWith("/api/settings/cars")) {
        await fulfillJson(route, { cars: [], active_car_id: null });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await installFakeWebSocket(page, {
    payload: { speed_mps: 10, clients: [], spectra: { clients: {} } },
  });
}

test("journey: speed unit and language switch persist and re-render the UI", async ({
  page,
}) => {
  const server: PreferenceServer = {
    language: "en",
    speedUnit: "kmh",
    puts: [],
    failSpeedUnitPut: false,
  };
  await installPreferenceRoutes(page, server);
  await page.goto("/");

  const speed = page.locator("#speed");
  await expect(speed).toContainText("36.0 km/h");

  await page.locator("#speedUnitSelect").selectOption("mps");
  await expect(speed).toContainText("10.0 m/s");
  await expect.poll(() => server.speedUnit).toBe("mps");

  await page.locator("#languageSelect").selectOption("nl");
  await expect(page.locator("#tab-history")).toHaveText("Geschiedenis");
  await expect(page.locator("html")).toHaveAttribute("lang", "nl");
  await expect.poll(() => server.language).toBe("nl");

  // Persisted preferences are applied on the next boot.
  await page.reload();
  await expect(page.locator("#tab-settings")).toHaveText("Instellingen");
  await expect(page.locator("#languageSelect")).toHaveValue("nl");
  await expect(page.locator("#speedUnitSelect")).toHaveValue("mps");
  await expect(speed).toContainText("10.0 m/s");

  await page.locator("#languageSelect").selectOption("en");
  await expect(page.locator("#tab-history")).toHaveText("History");
  expect(server.puts.map((put) => put.path)).toEqual([
    "/api/settings/speed-unit",
    "/api/settings/language",
    "/api/settings/language",
  ]);
});

test("journey: a failed speed unit save keeps the active unit and explains why", async ({
  page,
}) => {
  const server: PreferenceServer = {
    language: "en",
    speedUnit: "kmh",
    puts: [],
    failSpeedUnitPut: true,
  };
  await installPreferenceRoutes(page, server);
  await page.goto("/");
  await expect(page.locator("#speed")).toContainText("36.0 km/h");

  await page.locator("#speedUnitSelect").selectOption("mps");
  const feedback = page.locator("#speedUnitFeedback");
  await expect(feedback).toBeVisible();
  await expect(feedback).toContainText("km/h remains active");
  await expect(feedback).toContainText("disk full");
  await expect(page.locator("#speedUnitSelect")).toHaveValue("kmh");
  await expect(page.locator("#speed")).toContainText("36.0 km/h");
});

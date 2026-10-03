import { expect, test, type Page, type Route } from "@playwright/test";

import {
  bootLiveDashboard,
  fulfillJson,
  openAnalysisTab,
  openCarsTab,
  requestPath,
} from "./smoke.helpers";

test.describe.configure({ timeout: 25_000 });

type Car = Record<string, unknown> & { id: string; name: string };

type CarsServer = {
  cars: Car[];
  activeCarId: string | null;
  posts: Array<Record<string, unknown>>;
  activations: string[];
  deletes: string[];
  failActivation: boolean;
  /** Per-path response delays in ms, to reorder library responses. */
  delays: Record<string, number>;
  failLibrary: Set<string>;
};

const GEARBOX = {
  name: "6-speed manual",
  final_drive_ratio: 3.94,
  top_gear_ratio: 0.79,
  final_drive_ratio_confidence: "official_exact",
  top_gear_ratio_confidence: "reputable_secondary_crosschecked",
  transmission_confidence: "official_exact",
  requires_manual_confirmation: true,
  source_status: "exact_row",
};

const TIRE = {
  name: "Standard",
  default_axle_for_speed: "rear",
  front: { width_mm: 205, aspect_pct: 55, rim_in: 16 },
  rear: null,
  tire_width_mm: 205,
  tire_aspect_pct: 55,
  rim_in: 16,
  source_confidence: "official_exact",
};

const GOLF = {
  brand: "VW",
  type: "Hatchback",
  model: "Golf",
  tire_width_mm: 205,
  tire_aspect_pct: 55,
  rim_in: 16,
  tire_options: [TIRE],
  gearboxes: [GEARBOX],
  variants: [
    { name: "1.4 TSI", drivetrain: "FWD", engine: "1.4 petrol" },
    { name: "GTD", drivetrain: "FWD", engine: "2.0 diesel" },
  ],
};

function completeCar(id: string, name: string): Car {
  return {
    id,
    name,
    type: "Hatchback",
    aspects: {
      tire_width_mm: 205,
      tire_aspect_pct: 55,
      rim_in: 16,
      final_drive_ratio: 3.94,
      current_gear_ratio: 0.79,
    },
  };
}

function createServer(overrides: Partial<CarsServer> = {}): CarsServer {
  return {
    cars: [],
    activeCarId: null,
    posts: [],
    activations: [],
    deletes: [],
    failActivation: false,
    delays: {},
    failLibrary: new Set(),
    ...overrides,
  };
}

async function bootWithCars(page: Page, server: CarsServer) {
  const snapshot = () => ({
    cars: server.cars,
    active_car_id: server.activeCarId,
  });
  await bootLiveDashboard(page, {
    settingsHandler: async (route: Route) => {
      const path = requestPath(route);
      const method = route.request().method();
      if (path === "/api/settings/cars" && method === "POST") {
        const body = route.request().postDataJSON() as Record<string, unknown>;
        server.posts.push(body);
        server.cars = [
          ...server.cars,
          { ...body, id: `car-${server.cars.length + 1}` } as Car,
        ];
        await fulfillJson(route, snapshot());
        return;
      }
      if (path === "/api/settings/cars/active" && method === "PUT") {
        const { car_id } = route.request().postDataJSON() as { car_id: string };
        server.activations.push(car_id);
        if (server.failActivation) {
          await route.fulfill({
            status: 500,
            body: "{}",
            contentType: "application/json",
          });
          return;
        }
        server.activeCarId = car_id;
        await fulfillJson(route, snapshot());
        return;
      }
      if (path.startsWith("/api/settings/cars/") && method === "DELETE") {
        const carId = decodeURIComponent(path.split("/").pop() ?? "");
        server.deletes.push(carId);
        server.cars = server.cars.filter((car) => car.id !== carId);
        if (server.activeCarId === carId) {
          server.activeCarId = null;
        }
        await fulfillJson(route, snapshot());
        return;
      }
      if (path.startsWith("/api/settings/cars")) {
        await fulfillJson(route, snapshot());
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await page.route("**/api/car-library/**", async (route) => {
    const url = new URL(route.request().url());
    const key = `${url.pathname}?${url.searchParams.toString()}`;
    const delay = server.delays[key] ?? 0;
    if (delay) {
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
    if (server.failLibrary.has(url.pathname)) {
      await route.fulfill({
        status: 503,
        body: "{}",
        contentType: "application/json",
      });
      return;
    }
    if (url.pathname.endsWith("/brands")) {
      await fulfillJson(route, { brands: ["VW", "Volvo"] });
    } else if (url.pathname.endsWith("/types")) {
      await fulfillJson(route, { types: ["Hatchback", "Estate"] });
    } else {
      const type = url.searchParams.get("type");
      await fulfillJson(route, {
        models:
          type === "Estate"
            ? [{ ...GOLF, type: "Estate", model: "Golf Variant", variants: [] }]
            : [GOLF],
      });
    }
  });
}

test("journey: the library path creates a car with its source confidence", async ({
  page,
}) => {
  const server = createServer();
  await bootWithCars(page, server);
  await openCarsTab(page);
  await expect(page.locator("#carListBody")).toContainText(
    "Add the first car profile.",
  );
  await page.locator("#addCarBtn").click();
  const wizard = page.locator("#addCarWizard");
  await expect(wizard).toBeVisible();
  await expect(page.locator("#wizardBrandList .wiz-opt").first()).toBeFocused();

  await wizard.locator('#wizardBrandList [data-value="VW"]').click();
  await wizard.locator('#wizardTypeList [data-value="Hatchback"]').click();
  await wizard.locator('#wizardModelList [data-idx="0"]').click();
  await expect(wizard.locator("#wizardVariantList")).toContainText(
    "2.0 diesel",
  );
  await wizard.locator('#wizardVariantList [data-idx="1"]').click();

  await expect(page.locator("#wizardProgressText")).toContainText("5");
  // The first library tire is preselected; finishing needs a gearbox too.
  await expect(wizard.locator('[data-tire-idx="0"]')).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.locator("#wizardManualAddBtn")).toBeDisabled();
  await wizard.locator('#wizardGearboxList [data-idx="0"]').click();
  await expect(page.locator("#wizardActionHint")).toContainText(
    "Review or override these values",
  );
  await expect(page.locator("#wizardSummaryPanel")).toContainText(
    "VW Golf GTD",
  );
  await page.locator("#wizardManualAddBtn").click();

  await expect(wizard).toBeHidden();
  expect(server.posts).toHaveLength(1);
  expect(server.posts[0]).toMatchObject({
    name: "VW Golf GTD",
    type: "Hatchback",
    variant: "GTD",
    aspects: {
      final_drive_ratio: 3.94,
      current_gear_ratio: 0.79,
      tire_width_mm: 205,
    },
    order_reference_status: {
      tire_dimensions_confidence: "official_exact",
      current_gear_ratio_confidence: "reputable_secondary_crosschecked",
      requires_manual_confirmation: true,
      selection_source_status: "exact_row",
      transmission_name: "6-speed manual",
    },
  });
  const row = page.locator('#carListBody tr[data-car-id="car-1"]');
  await expect(row).toContainText("Active");
  await expect(row.locator(".car-created-pill")).toHaveText("New");
  await expect(page.locator("#carSelectionGuidance")).toContainText(
    "VW Golf GTD",
  );
  // Leaving the tab dismisses the creation feedback.
  await openAnalysisTab(page);
  await openCarsTab(page);
  await expect(row.locator(".car-created-pill")).toHaveCount(0);
});

test("journey: a failed library load recovers through manual specs and back", async ({
  page,
}) => {
  const server = createServer();
  server.failLibrary.add("/api/car-library/brands");
  await bootWithCars(page, server);
  await openCarsTab(page);
  await page.locator("#addCarBtn").click();
  const wizard = page.locator("#addCarWizard");
  await expect(wizard.locator(".wizard-load-error")).toBeVisible();
  await expect(page.locator("#wizardCustomBrand")).toBeFocused();

  // A blank custom entry just refocuses the input.
  await page.locator("#wizardCustomBrandBtn").click();
  await expect(page.locator("#wizardCustomBrand")).toBeFocused();
  await expect(page.locator("#wizardStep0")).toBeVisible();

  await wizard.locator('[data-wizard-recovery="manual"]').click();
  await expect(page.locator("#wizardStep4")).toBeVisible();
  await expect(page.locator("#addCarWizard")).toHaveAttribute(
    "data-spec-branch",
    "manual",
  );
  // Back skips the steps that were never chosen.
  await page.locator("#wizardBackBtn").click();
  await expect(page.locator("#wizardStep0")).toBeVisible();

  server.failLibrary.clear();
  await wizard.locator('[data-wizard-recovery="retry"]').click();
  await expect(
    wizard.locator('#wizardBrandList [data-value="VW"]'),
  ).toBeVisible();
});

test("journey: a slow older model list never replaces the newer one", async ({
  page,
}) => {
  const server = createServer();
  server.delays["/api/car-library/models?brand=VW&type=Hatchback"] = 800;
  await bootWithCars(page, server);
  await openCarsTab(page);
  await page.locator("#addCarBtn").click();
  const wizard = page.locator("#addCarWizard");
  await wizard.locator('#wizardBrandList [data-value="VW"]').click();
  await wizard.locator('#wizardTypeList [data-value="Hatchback"]').click();
  await page.locator("#wizardBackBtn").click();
  await wizard.locator('#wizardTypeList [data-value="Estate"]').click();
  await expect(wizard.locator("#wizardModelList")).toContainText(
    "Golf Variant",
  );
  await page.waitForTimeout(1000);
  await expect(wizard.locator("#wizardModelList")).toContainText(
    "Golf Variant",
  );
  await expect(wizard.locator("#wizardModelList .wiz-opt")).toHaveCount(1);
});

test("journey: a kept library tire keeps its confidence; edited manual values are user-confirmed", async ({
  page,
}) => {
  const server = createServer();
  await bootWithCars(page, server);
  await openCarsTab(page);
  await page.locator("#addCarBtn").click();
  const wizard = page.locator("#addCarWizard");
  await wizard.locator('#wizardBrandList [data-value="VW"]').click();
  await wizard.locator('#wizardTypeList [data-value="Hatchback"]').click();
  await wizard.locator('#wizardModelList [data-idx="0"]').click();
  await wizard.locator('#wizardVariantList [data-idx="0"]').click();
  // Typing into the manual specs switches to the manual branch.
  await expect(page.locator("#wizTireWidth")).toHaveValue("205");
  await page.locator("#wizFinalDrive").fill("4.1");
  await page.locator("#wizGearRatio").fill("0.8");
  await expect(wizard).toHaveAttribute("data-spec-branch", "manual");
  await page.locator("#wizardManualAddBtn").click();
  await expect(wizard).toBeHidden();
  expect(server.posts[0]).toMatchObject({
    aspects: {
      final_drive_ratio: 4.1,
      current_gear_ratio: 0.8,
      tire_width_mm: 205,
    },
    order_reference_status: {
      tire_dimensions_confidence: "official_exact",
      final_drive_ratio_confidence: "user_confirmed",
      selection_source_status: "manual_entry",
      requires_manual_confirmation: false,
    },
  });

  await page.locator("#addCarBtn").click();
  await wizard.locator('#wizardBrandList [data-value="VW"]').click();
  await wizard.locator('#wizardTypeList [data-value="Hatchback"]').click();
  await wizard.locator('#wizardModelList [data-idx="0"]').click();
  await wizard.locator('#wizardVariantList [data-idx="0"]').click();
  await page.locator("#wizTireWidth").fill("215");
  await page.locator("#wizardManualAddBtn").click();
  await expect(wizard).toBeHidden();
  expect(server.posts[1]).toMatchObject({
    aspects: { tire_width_mm: 215 },
    order_reference_status: { tire_dimensions_confidence: "user_confirmed" },
  });
});

test("journey: saved cars activate, finish setup, delete, and report failures", async ({
  page,
}) => {
  const server = createServer({
    cars: [
      completeCar("car-a", "Daily"),
      completeCar("car-b", "Weekend"),
      {
        id: "car-c",
        name: "Project",
        type: "Coupe",
        aspects: { tire_width_mm: 225 },
      },
    ],
    activeCarId: "car-a",
  });
  await bootWithCars(page, server);
  await openCarsTab(page);
  const row = (id: string) =>
    page.locator(`#carListBody tr[data-car-id="${id}"]`);
  await expect(row("car-a")).toContainText("Active");
  await expect(row("car-c")).toContainText("Needs specs");

  await row("car-b").locator('[data-car-action="activate"]').click();
  await expect(row("car-b")).toContainText("Active");
  expect(server.activations).toEqual(["car-b"]);

  // Finishing an incomplete car activates it and opens the Analysis tab.
  await row("car-c").locator('[data-car-action="complete"]').click();
  await expect(page.locator("#analysisTab")).toBeVisible();
  expect(server.activations).toEqual(["car-b", "car-c"]);
  await openCarsTab(page);

  await row("car-a").locator('[data-car-action="delete"]').click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: "Confirm" })
    .click();
  await expect(row("car-a")).toHaveCount(0);
  expect(server.deletes).toEqual(["car-a"]);

  server.failActivation = true;
  await row("car-b").locator('[data-car-action="activate"]').click();
  await expect(page.locator("#appErrorBanner")).toContainText(
    "Failed to activate",
  );
});

test("journey: an activation failure after creating keeps the wizard open", async ({
  page,
}) => {
  const server = createServer({ failActivation: true });
  await bootWithCars(page, server);
  await openCarsTab(page);
  await page.locator("#addCarBtn").click();
  await page.locator("#wizardCustomBrand").fill("Track");
  await page.locator("#wizardCustomBrandBtn").click();
  await page.locator("#wizardCustomType").fill("Coupe");
  await page.locator("#wizardCustomTypeBtn").click();
  await page.locator("#wizardCustomModel").fill("Demo");
  await page.locator("#wizardCustomModelBtn").click();
  for (const [id, value] of [
    ["#wizTireWidth", "225"],
    ["#wizTireAspect", "45"],
    ["#wizRim", "18"],
    ["#wizFinalDrive", "3.08"],
    ["#wizGearRatio", "0.64"],
  ]) {
    await page.locator(id).fill(value);
  }
  await page.locator("#wizardManualAddBtn").click();
  await expect(page.locator("#appErrorBanner")).toContainText(
    "Failed to activate",
  );
  await expect(page.locator("#addCarWizard")).toBeVisible();
  await expect(page.locator("#wizardManualAddBtn")).toBeFocused();
  expect(server.posts).toHaveLength(1);
});

test("journey: the dashboard's add-car prompt opens the wizard", async ({
  page,
}) => {
  await bootWithCars(page, createServer());
  await page
    .locator("#loggingSummary")
    .getByRole("button", { name: "Add a car" })
    .click();
  await expect(page.locator("#carTab")).toBeVisible();
  await expect(page.locator("#addCarWizard")).toBeVisible();
  await expect(page.locator("#wizardBrandList .wiz-opt").first()).toBeFocused();
});

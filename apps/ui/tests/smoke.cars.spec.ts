import { expect, test, type Page, type Route } from "@playwright/test";

import type {
  CarLibraryBrandsPayload,
  CarLibraryGearbox,
  CarLibraryModel,
  CarLibraryModelsPayload,
  CarLibraryTireOption,
  CarLibraryTypesPayload,
  CarRecord,
  CarsPayload,
  CarUpsertRequest,
} from "../src/api/types";
import {
  bootLiveDashboard,
  fulfillJson,
  openAnalysisTab,
  openCarsTab,
  requestPath,
} from "./smoke.helpers";

test.describe.configure({ timeout: 25_000 });

type CarsServer = {
  cars: CarRecord[];
  activeCarId: string | null;
  posts: CarUpsertRequest[];
  puts: Array<{ carId: string; body: CarUpsertRequest }>;
  activations: string[];
  deletes: string[];
  failActivation: boolean;
  /** Per-path response delays in ms, to reorder library responses. */
  delays: Record<string, number>;
  failLibrary: Set<string>;
  /** Every car-library path requested, to prove a fetch was skipped. */
  libraryPaths: string[];
};

const GEARBOX: CarLibraryGearbox = {
  name: "6-speed manual",
  final_drive_ratio: 3.94,
  top_gear_ratio: 0.79,
  fuel_type: "ICE",
  final_drive_ratio_confidence: "official_exact",
  top_gear_ratio_confidence: "reputable_secondary_crosschecked",
  transmission_confidence: "official_exact",
  requires_manual_confirmation: true,
  source_status: "exact_row",
};

const TIRE: CarLibraryTireOption = {
  name: "Standard",
  default_axle_for_speed: "rear",
  front: { width_mm: 205, aspect_pct: 55, rim_in: 16 },
  rear: null,
  tire_width_mm: 205,
  tire_aspect_pct: 55,
  rim_in: 16,
  source_confidence: "official_exact",
};

const GOLF: CarLibraryModel = {
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

function completeCar(id: string, name: string): CarRecord {
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
    puts: [],
    activations: [],
    deletes: [],
    failActivation: false,
    delays: {},
    failLibrary: new Set(),
    libraryPaths: [],
    ...overrides,
  };
}

async function bootWithCars(page: Page, server: CarsServer) {
  const snapshot = (): CarsPayload => ({
    cars: server.cars,
    active_car_id: server.activeCarId,
  });
  await bootLiveDashboard(page, {
    settingsHandler: async (route: Route) => {
      const path = requestPath(route);
      const method = route.request().method();
      if (path === "/api/settings/cars" && method === "POST") {
        const body = route.request().postDataJSON() as CarUpsertRequest;
        server.posts.push(body);
        server.cars = [
          ...server.cars,
          { ...body, id: `car-${server.cars.length + 1}` } as CarRecord,
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
      if (path.startsWith("/api/settings/cars/") && method === "PUT") {
        const carId = decodeURIComponent(path.split("/").pop() ?? "");
        const body = route.request().postDataJSON() as CarUpsertRequest;
        server.puts.push({ carId, body });
        server.cars = server.cars.map((car) => {
          if (car.id !== carId) {
            return car;
          }
          const aspects = { ...car.aspects, ...body.aspects };
          for (const [key, value] of Object.entries(aspects)) {
            if (value === null) {
              delete aspects[key as keyof typeof aspects];
            }
          }
          return { ...car, aspects };
        });
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
    server.libraryPaths.push(url.pathname);
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
      await fulfillJson<CarLibraryBrandsPayload>(route, {
        brands: ["VW", "Volvo"],
      });
    } else if (url.pathname.endsWith("/types")) {
      await fulfillJson<CarLibraryTypesPayload>(route, {
        types: ["Hatchback", "Estate"],
      });
    } else {
      const type = url.searchParams.get("type");
      await fulfillJson<CarLibraryModelsPayload>(route, {
        models:
          type === "Estate"
            ? [{ ...GOLF, type: "Estate", model: "Golf Variant", variants: [] }]
            : [GOLF],
      });
    }
  });
}

test("journey: the library path prefills the car and shows what it can test", async ({
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
  // The first tire and the only gearbox are preselected and fill the specs.
  await expect(wizard.locator('[data-tire-idx="0"]')).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  const gearbox = wizard.locator('#wizardGearboxList [data-idx="0"]');
  await expect(gearbox).toHaveAttribute("aria-pressed", "true");
  await expect(gearbox.locator(".ref-chip")).toHaveText(["exact", "checked"]);
  await expect(page.locator("#wizTireWidth")).toHaveValue("205");
  await expect(page.locator("#wizFinalDrive")).toHaveValue("3.94");
  await expect(page.locator("#wizGearRatio")).toHaveValue("0.79");
  const capabilities = page.locator("#wizardCapabilities");
  await expect(
    capabilities.locator('[data-family="driveline"]'),
  ).toHaveAttribute("data-mark", "ok");
  await expect(capabilities.locator('[data-family="engine"]')).toContainText(
    "assuming top gear",
  );
  await expect(page.locator("#wizardActionHint")).toContainText("Ready to add");
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
    fuel_type: "ICE",
    aspects: {
      final_drive_ratio: 3.94,
      current_gear_ratio: 0.79,
      tire_width_mm: 205,
    },
    order_reference_status: {
      tire_dimensions_confidence: "official_exact",
      current_gear_ratio_confidence: "reputable_secondary_crosschecked",
      requires_manual_confirmation: false,
      selection_source_status: "exact_row",
      transmission_name: "6-speed manual",
    },
  });
  const row = page.locator('#carListBody tr[data-car-id="car-1"]');
  await expect(row).toContainText("Active");
  await expect(row.locator(".ref-chip")).toHaveText([
    "exact",
    "exact",
    "checked",
  ]);
  await expect(row.locator('[data-family="wheel"]')).toHaveAttribute(
    "data-mark",
    "ok",
  );
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
  await expect(page.locator("#wizardSpecsForm")).toBeVisible();
  await expect(page.locator("#wizardTireList")).toHaveCount(0);
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

test("journey: typed values become the user's; a pasted size and an unknown ratio are saved as such", async ({
  page,
}) => {
  const server = createServer();
  await bootWithCars(page, server);
  await openCarsTab(page);
  const wizard = page.locator("#addCarWizard");
  const openGolf = async () => {
    await page.locator("#addCarBtn").click();
    await wizard.locator('#wizardBrandList [data-value="VW"]').click();
    await wizard.locator('#wizardTypeList [data-value="Hatchback"]').click();
    await wizard.locator('#wizardModelList [data-idx="0"]').click();
    await wizard.locator('#wizardVariantList [data-idx="0"]').click();
    await expect(page.locator("#wizTireWidth")).toHaveValue("205");
  };

  await openGolf();
  await page.locator("#wizFinalDrive").fill("4.1");
  await expect(page.locator('label[for="wizFinalDrive"] .ref-chip')).toHaveText(
    "yours",
  );
  await page.locator("#wizardManualAddBtn").click();
  await expect(wizard).toBeHidden();
  expect(server.posts[0]).toMatchObject({
    aspects: { final_drive_ratio: 4.1, current_gear_ratio: 0.79 },
    order_reference_status: {
      tire_dimensions_confidence: "official_exact",
      final_drive_ratio_confidence: "user_confirmed",
      current_gear_ratio_confidence: "reputable_secondary_crosschecked",
      selection_source_status: "manual_entry",
      requires_manual_confirmation: false,
    },
  });

  await openGolf();
  await page.locator("#wizTireSize").fill("18 inch");
  await expect(page.locator("#wizTireSizeHelp")).toContainText("Couldn't read");
  await page.locator("#wizTireSize").fill("215/50 R17 91V");
  await expect(page.locator("#wizTireWidth")).toHaveValue("215");
  await expect(page.locator("#wizTireAspect")).toHaveValue("50");
  await expect(page.locator("#wizRim")).toHaveValue("17");
  // "I don't know" leaves the top gear unknown: the engine can't be tested.
  await wizard.locator('[data-ratio-unknown="topGear"]').click();
  await expect(page.locator("#wizGearRatio")).toHaveValue("");
  await expect(
    page.locator('#wizardCapabilities [data-family="engine"]'),
  ).toHaveAttribute("data-mark", "no");
  await page.locator("#wizardManualAddBtn").click();
  await expect(wizard).toBeHidden();
  expect(server.posts[1]).toMatchObject({
    aspects: {
      tire_width_mm: 215,
      tire_aspect_pct: 50,
      rim_in: 17,
      final_drive_ratio: 3.94,
      current_gear_ratio: null,
    },
    order_reference_status: {
      tire_dimensions_confidence: "user_confirmed",
      current_gear_ratio_confidence: null,
    },
  });
});

test("journey: saved cars activate, are edited in place, delete, and report failures", async ({
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
  const wizard = page.locator("#addCarWizard");
  await expect(row("car-a")).toContainText("Active");
  await expect(row("car-c")).toContainText("Needs specs");
  await expect(
    row("car-c").locator('[data-car-action="activate"]'),
  ).toHaveCount(0);

  await row("car-b").locator('[data-car-action="activate"]').click();
  await expect(row("car-b")).toContainText("Active");
  expect(server.activations).toEqual(["car-b"]);

  // Finishing an incomplete car edits it in place through the car update.
  await row("car-c").locator('[data-car-action="edit"]').click();
  await expect(wizard).toHaveAttribute("data-mode", "edit");
  await expect(page.locator("#wizardTitle")).toContainText("Edit Project");
  await expect(page.locator("#wizardBackBtn")).toBeHidden();
  await expect(page.locator("#wizTireWidth")).toHaveValue("225");
  await page.locator("#wizTireSize").fill("225/45R18");
  await expect(page.locator("#wizardManualAddBtn")).toHaveText("Save changes");
  await page.locator("#wizardManualAddBtn").click();
  await expect(wizard).toBeHidden();
  expect(server.puts).toEqual([
    {
      carId: "car-c",
      body: {
        aspects: { tire_width_mm: 225, tire_aspect_pct: 45, rim_in: 18 },
      },
    },
  ]);
  await expect(row("car-c")).toContainText("Ready");
  await expect(
    row("car-c").locator('[data-family="driveline"]'),
  ).toHaveAttribute("data-mark", "no");

  // Clearing a ratio on a complete car sends only that change.
  await row("car-b").locator('[data-car-action="edit"]').click();
  await expect(page.locator("#wizFinalDrive")).toHaveValue("3.94");
  await wizard.locator('[data-ratio-unknown="finalDrive"]').click();
  await page.locator("#wizardManualAddBtn").click();
  await expect(wizard).toBeHidden();
  expect(server.puts[1]).toEqual({
    carId: "car-b",
    body: { aspects: { final_drive_ratio: null } },
  });

  await row("car-a").locator('[data-car-action="delete"]').click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: "Confirm" })
    .click();
  await expect(row("car-a")).toHaveCount(0);
  expect(server.deletes).toEqual(["car-a"]);

  server.failActivation = true;
  await row("car-c").locator('[data-car-action="activate"]').click();
  await expect(page.locator("#appErrorBanner")).toContainText(
    "Failed to activate",
  );
});

test("journey: a custom brand skips the library; ratios stay optional", async ({
  page,
}) => {
  const server = createServer({ failActivation: true });
  await bootWithCars(page, server);
  await openCarsTab(page);
  await page.locator("#addCarBtn").click();
  await expect(
    page.locator('#wizardBrandList [data-value="VW"]'),
  ).toBeVisible();
  await page.locator("#wizardCustomBrand").fill("Track");
  await page.locator("#wizardCustomBrandBtn").click();
  await expect(page.locator("#wizardCustomType")).toBeFocused();
  await expect(page.locator("#addCarWizard")).toContainText(
    "No library data for Track",
  );
  await page.locator("#wizardCustomType").fill("Coupe");
  await page.locator("#wizardCustomTypeBtn").click();
  await page.locator("#wizardCustomModel").fill("Demo");
  await page.locator("#wizardCustomModelBtn").click();
  expect(server.libraryPaths).not.toContain("/api/car-library/types");
  expect(server.libraryPaths).not.toContain("/api/car-library/models");
  await page.locator("#wizTireSize").fill("225/45 R18");
  await page.locator("#wizardManualAddBtn").click();
  await expect(page.locator("#appErrorBanner")).toContainText(
    "Failed to activate",
  );
  await expect(page.locator("#addCarWizard")).toBeVisible();
  await expect(page.locator("#wizardManualAddBtn")).toBeFocused();
  expect(server.posts).toHaveLength(1);
  expect(server.posts[0]).toMatchObject({
    name: "Track Demo",
    type: "Coupe",
    aspects: {
      tire_width_mm: 225,
      final_drive_ratio: null,
      current_gear_ratio: null,
    },
    order_reference_status: {
      tire_dimensions_confidence: "user_confirmed",
      selection_source_status: "manual_entry",
    },
  });
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

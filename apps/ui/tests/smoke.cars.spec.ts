import {
  expect,
  type Locator,
  type Page,
  type Route,
  test,
} from "@playwright/test";

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

/** A library row that leaves its top gear unresolved: served as null. */
const NO_TOP_GEAR: CarLibraryGearbox = {
  name: "7-speed DSG",
  final_drive_ratio: 3.94,
  top_gear_ratio: null,
  fuel_type: "ICE",
  final_drive_ratio_confidence: "official_exact",
  transmission_confidence: "official_exact",
  requires_manual_confirmation: false,
  source_status: "exact_row",
};

/** A library EV: one official reduction ratio (its final drive), no top gear. */
const EV_REDUCTION: CarLibraryGearbox = {
  name: "Single-speed fixed gear (EV)",
  final_drive_ratio: 11.53,
  top_gear_ratio: null,
  fuel_type: "EV",
  final_drive_ratio_confidence: "official_exact",
  transmission_confidence: "official_exact",
  requires_manual_confirmation: false,
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

const SPORT_TIRE: CarLibraryTireOption = {
  ...TIRE,
  name: "Sport",
  front: { width_mm: 225, aspect_pct: 45, rim_in: 17 },
  tire_width_mm: 225,
  tire_aspect_pct: 45,
  rim_in: 17,
  source_confidence: "reputable_secondary_crosschecked",
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
    {
      name: "1.4 TSI",
      drivetrain: "FWD",
      engine: "1.4 petrol",
      tire_options: [TIRE, SPORT_TIRE],
    },
    { name: "GTD", drivetrain: "FWD", engine: "2.0 diesel" },
  ],
};

/** One generation; the GTI's final drive changed, so the year picks the row. */
const POLO: CarLibraryModel = {
  ...GOLF,
  model: "Polo (AW, 2018\u20132024)",
  variants: [
    {
      name: "1.0 TSI",
      drivetrain: "FWD",
      engine: "1.0 petrol",
      gearboxes: [GEARBOX],
      production_start_year: 2018,
      production_end_year: 2024,
    },
    {
      name: "GTI (2018\u20132020)",
      drivetrain: "FWD",
      engine: "2.0 petrol",
      gearboxes: [{ ...GEARBOX, name: "6-speed DSG", final_drive_ratio: 3.65 }],
      production_start_year: 2018,
      production_end_year: 2020,
    },
    {
      name: "GTI (2021\u20132024)",
      drivetrain: "FWD",
      // Long enough to wrap under the name on a phone.
      engine: "2.0 TSI EA888 evo4 turbo petrol",
      gearboxes: [{ ...GEARBOX, name: "6-speed DSG", final_drive_ratio: 3.24 }],
      production_start_year: 2021,
      production_end_year: 2024,
    },
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
            ? [
                {
                  ...GOLF,
                  type: "Estate",
                  model: "Golf Variant",
                  gearboxes: [NO_TOP_GEAR],
                  variants: [
                    {
                      name: "1.5 TSI",
                      drivetrain: "FWD",
                      engine: "1.5 petrol",
                      gearboxes: [NO_TOP_GEAR],
                    },
                  ],
                },
                {
                  ...GOLF,
                  type: "Estate",
                  model: "ID.7 Tourer",
                  gearboxes: [EV_REDUCTION],
                  variants: [
                    {
                      name: "Pro S",
                      drivetrain: "RWD",
                      engine: "Electric Single Motor",
                      gearboxes: [EV_REDUCTION],
                    },
                  ],
                },
              ]
            : [GOLF, POLO],
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

test("journey: a library gearbox without a top gear is saved without one", async ({
  page,
}) => {
  const server = createServer();
  await bootWithCars(page, server);
  await openCarsTab(page);
  await page.locator("#addCarBtn").click();
  const wizard = page.locator("#addCarWizard");
  await wizard.locator('#wizardBrandList [data-value="VW"]').click();
  await wizard.locator('#wizardTypeList [data-value="Estate"]').click();
  await wizard.locator('#wizardModelList [data-idx="0"]').click();
  await wizard.locator('#wizardVariantList [data-idx="0"]').click();

  // The gearbox says its top gear is unknown; the field stays empty, not a default.
  const gearbox = wizard.locator('#wizardGearboxList [data-idx="0"]');
  await expect(gearbox).toHaveAttribute("aria-pressed", "true");
  await expect(gearbox).toContainText("Top gear unknown");
  await expect(gearbox.locator(".ref-chip")).toHaveText(["exact", "unknown"]);
  await expect(page.locator("#wizFinalDrive")).toHaveValue("3.94");
  await expect(page.locator("#wizGearRatio")).toHaveValue("");
  // Wheel and driveline checks run; the engine needs a top gear or OBD-II.
  const capabilities = page.locator("#wizardCapabilities");
  await expect(capabilities.locator('[data-family="wheel"]')).toHaveAttribute(
    "data-mark",
    "ok",
  );
  await expect(
    capabilities.locator('[data-family="driveline"]'),
  ).toHaveAttribute("data-mark", "ok");
  await expect(capabilities.locator('[data-family="engine"]')).toContainText(
    "Needs the top gear ratio, or OBD-II.",
  );
  await expect(page.locator("#wizardActionHint")).toContainText("Ready to add");
  await page.locator("#wizardManualAddBtn").click();

  await expect(wizard).toBeHidden();
  expect(server.posts[0]).toMatchObject({
    variant: "1.5 TSI",
    fuel_type: "ICE",
    aspects: { final_drive_ratio: 3.94, current_gear_ratio: null },
    order_reference_status: {
      final_drive_ratio_confidence: "official_exact",
      current_gear_ratio_confidence: null,
      requires_manual_confirmation: false,
      selection_source_status: "exact_row",
      transmission_name: "7-speed DSG",
    },
  });
  const row = page.locator('#carListBody tr[data-car-id="car-1"]');
  await expect(row.locator('[data-family="engine"]')).toContainText(
    "Needs the top gear ratio, or OBD-II.",
  );
});

test("journey: a library EV with an official reduction ratio needs no confirmation", async ({
  page,
}) => {
  const server = createServer();
  await bootWithCars(page, server);
  await openCarsTab(page);
  await page.locator("#addCarBtn").click();
  const wizard = page.locator("#addCarWizard");
  await wizard.locator('#wizardBrandList [data-value="VW"]').click();
  await wizard.locator('#wizardTypeList [data-value="Estate"]').click();
  await wizard.locator('#wizardModelList [data-idx="1"]').click();
  await wizard.locator('#wizardVariantList [data-idx="0"]').click();

  // One reduction ratio and no top gear: no gearbox estimate to confirm.
  const gearbox = wizard.locator('#wizardGearboxList [data-idx="0"]');
  await expect(gearbox).toHaveAttribute("aria-pressed", "true");
  await expect(gearbox).toContainText("Reduction 11.53");
  await expect(gearbox).not.toContainText("Top gear");
  await expect(gearbox.locator(".ref-chip")).toHaveText(["exact"]);
  await expect(page.locator("#wizFinalDrive")).toHaveValue("11.53");
  await expect(page.locator("#wizGearRatio")).toHaveCount(0);
  await expect(page.locator("#wizardActionHint")).toHaveText(
    "Ready to add. \u201cThis car can test\u201d shows what it can check.",
  );
  await page.locator("#wizardManualAddBtn").click();

  await expect(wizard).toBeHidden();
  expect(server.posts[0]).toMatchObject({
    variant: "Pro S",
    fuel_type: "EV",
    aspects: { final_drive_ratio: 11.53, current_gear_ratio: null },
    order_reference_status: {
      final_drive_ratio_confidence: "official_exact",
      current_gear_ratio_confidence: null,
      requires_manual_confirmation: false,
      selection_source_status: "exact_row",
    },
  });
  const row = page.locator('#carListBody tr[data-car-id="car-1"]');
  await expect(row).toContainText("Reduction ratio");
  await expect(row.locator(".ref-chip")).toHaveText(["exact", "exact"]);
  await expect(row).not.toContainText("Edit the car if you know");
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

test("journey: one model per generation; the variant step picks the model year", async ({
  page,
}) => {
  const server = createServer();
  await bootWithCars(page, server);
  await openCarsTab(page);
  await page.locator("#addCarBtn").click();
  const wizard = page.locator("#addCarWizard");
  await wizard.locator('#wizardBrandList [data-value="VW"]').click();
  await wizard.locator('#wizardTypeList [data-value="Hatchback"]').click();
  await expect(wizard.locator("#wizardModelList .wiz-opt")).toHaveCount(2);
  await wizard.locator('#wizardModelList [data-idx="1"]').click();

  const variants = wizard.locator("#wizardVariantList .wiz-opt");
  await expect(variants).toHaveCount(3);
  await expect(variants.nth(0)).toContainText(
    "FWD · 1.0 petrol · 2018\u20132024",
  );
  await expect(variants.nth(2)).toContainText("GTI (2021\u20132024)");
  // The year-split name carries the years; its detail doesn't repeat them.
  await expect(variants.nth(2).locator(".wiz-opt-detail")).toHaveText(
    "FWD · 2.0 TSI EA888 evo4 turbo petrol",
  );
  await expect(wizard.locator("#wizardStep3")).toContainText(
    "Pick the one that matches your car's year",
  );
  await variants.nth(2).click();

  await expect(page.locator("#wizFinalDrive")).toHaveValue("3.24");
  await page.locator("#wizardManualAddBtn").click();
  await expect(wizard).toBeHidden();
  expect(server.posts[0]).toMatchObject({
    name: "VW Polo (AW, 2018\u20132024) GTI (2021\u20132024)",
    variant: "GTI (2021\u20132024)",
    aspects: { final_drive_ratio: 3.24 },
    order_reference_status: { transmission_name: "6-speed DSG" },
  });
});

test("journey: on a phone the header carries the picks and no option is covered", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const server = createServer();
  await bootWithCars(page, server);
  // Enough variants that the variant step scrolls.
  const fillers = [55, 60, 63, 66, 70, 75, 81, 85, 90, 95, 110, 125].map(
    (kw) => ({
      name: `1.0 TSI ${kw} kW`,
      drivetrain: "FWD" as const,
      engine: "1.0 petrol",
    }),
  );
  await page.route("**/api/car-library/models?*", (route) =>
    fulfillJson<CarLibraryModelsPayload>(route, {
      models: [
        GOLF,
        { ...POLO, variants: [...(POLO.variants ?? []), ...fillers] },
      ],
    }),
  );
  await openCarsTab(page);
  await page.locator("#addCarBtn").click();
  const wizard = page.locator("#addCarWizard");
  const body = wizard.locator(".wizard-shell");
  const trail = page.locator("#wizardTrail");
  await wizard.locator('#wizardBrandList [data-value="VW"]').click();
  await expect(trail).toHaveText("VW");
  await wizard.locator('#wizardTypeList [data-value="Hatchback"]').click();
  await wizard.locator('#wizardModelList [data-idx="1"]').click();
  await expect(trail).toHaveText("VW · Hatchback · Polo (AW, 2018\u20132024)");
  // The picks live in the header; the side card waits for the specs step.
  await expect(wizard.locator(".wizard-summary-card")).toBeHidden();
  await expect(wizard.locator(".wizard-step-indicators")).toBeHidden();

  const variants = wizard.locator("#wizardVariantList .wiz-opt");
  await variants.nth(2).click();
  await expect(trail).toHaveText(
    "VW · Hatchback · Polo (AW, 2018\u20132024) · GTI (2021\u20132024)",
  );
  // On the specs step the card follows the form, inside the scroll area,
  // while the buttons stay on screen.
  await page.locator("#wizardSummaryPanel").scrollIntoViewIfNeeded();
  await expect(page.locator("#wizardSummaryPanel")).toBeInViewport();
  await expect(page.locator("#wizardManualAddBtn")).toBeInViewport({
    ratio: 1,
  });
  expect(await body.evaluate((element) => element.scrollTop)).toBeGreaterThan(
    0,
  );

  // Back starts the variant step at its top and drops the variant from the
  // trail.
  await page.locator("#wizardBackBtn").click();
  await expect(trail).toHaveText("VW · Hatchback · Polo (AW, 2018\u20132024)");
  await expect(
    wizard.getByText("Pick the one that matches your car's year"),
  ).toBeInViewport({ ratio: 1 });
  const box = async (locator: Locator) => {
    const rect = await locator.boundingBox();
    if (!rect) throw new Error("not rendered");
    return rect;
  };
  const header = await box(wizard.locator(".wizard-header"));
  const scrollArea = await box(body);
  const first = await box(variants.first());
  expect(first.y).toBeGreaterThanOrEqual(header.y + header.height);
  expect(first.y).toBeGreaterThanOrEqual(scrollArea.y);
  expect(first.y + first.height).toBeLessThanOrEqual(
    scrollArea.y + scrollArea.height,
  );
  // Nothing is painted over the first option.
  const hit = await page.evaluate(
    ([x, y]) =>
      document.elementFromPoint(x, y)?.closest(".wiz-opt")?.textContent,
    [first.x + first.width / 2, first.y + first.height / 2],
  );
  expect(hit).toContain("1.0 TSI");
  // A long detail wraps under the name and stays inside its option.
  const row = await box(variants.nth(2));
  const detail = await box(variants.nth(2).locator(".wiz-opt-detail"));
  expect(detail.y).toBeGreaterThan(row.y + 10);
  expect(detail.y + detail.height).toBeLessThanOrEqual(row.y + row.height);
  expect(detail.x + detail.width).toBeLessThanOrEqual(row.x + row.width);
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
  await expect(wizard.locator("#wizardModelList")).not.toContainText("Polo");
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
  // The sidewall-size field shows the library size and follows the fields.
  const tireChip = page.locator('label[for="wizTireSize"] .ref-chip');
  const tireCard = (index: number) =>
    wizard.locator(`[data-tire-idx="${index}"]`);
  await expect(page.locator("#wizTireSize")).toHaveValue("205/55 R16");
  await expect(tireCard(0)).toHaveAttribute("aria-pressed", "true");
  await expect(tireChip).toHaveText("exact");
  await page.locator("#wizTireWidth").fill("215");
  await expect(page.locator("#wizTireSize")).toHaveValue("215/55 R16");
  // The highlighted tire follows the size: no option has 215/55 R16.
  await expect(tireCard(0)).toHaveAttribute("aria-pressed", "false");
  await expect(tireCard(1)).toHaveAttribute("aria-pressed", "false");
  await expect(tireChip).toHaveText("yours");
  // Typing another option's size highlights it, with its source.
  await page.locator("#wizTireSize").fill("225/45 R17");
  await expect(tireCard(1)).toHaveAttribute("aria-pressed", "true");
  await expect(tireChip).toHaveText("checked");
  await page.locator("#wizTireSize").fill("205/55 R16");
  await expect(tireCard(0)).toHaveAttribute("aria-pressed", "true");
  await expect(tireCard(1)).toHaveAttribute("aria-pressed", "false");
  await expect(tireChip).toHaveText("exact");
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
  // Clearing the size clears the three fields it fills.
  await page.locator("#wizTireSize").fill("");
  await expect(page.locator("#wizRim")).toHaveValue("");
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
  // The library does not know this car, so the wizard asks its powertrain.
  // An EV has no top gear and no engine to check.
  await expect(page.locator("#wizGearRatio")).toBeVisible();
  await page.locator("#wizPowertrain").selectOption("EV");
  await expect(page.locator("#wizGearRatio")).toHaveCount(0);
  await expect(page.locator('label[for="wizFinalDrive"]')).toContainText(
    "Reduction ratio",
  );
  const capabilities = page.locator("#wizardCapabilities");
  await expect(capabilities.locator('[data-family="engine"]')).toHaveAttribute(
    "data-mark",
    "na",
  );
  await expect(capabilities.locator('[data-family="driveline"]')).toContainText(
    "Electric motor",
  );
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
    fuel_type: "EV",
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

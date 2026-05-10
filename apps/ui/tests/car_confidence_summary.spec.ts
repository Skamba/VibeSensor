import { expect, test } from "vitest";
import type {
  CarLibraryGearbox,
  CarLibraryTireOption,
  CarRecord,
  CarOrderReferenceStatus,
} from "../src/api/types";
import {
  buildGearboxConfidenceHint,
  buildOrderReferenceConfidenceDetail,
} from "../src/app/features/car_confidence_summary";
import {
  createInitialWizardState,
  getWizardActionHint,
} from "../src/app/features/cars_wizard_state";
import { buildSettingsCarListRenderModel } from "../src/app/views/settings_car_list_view";

const labels: Record<string, string> = {
  "settings.car.confidence.part_tires": "Tires {value}",
  "settings.car.confidence.part_drive": "Drive {value}",
  "settings.car.confidence.part_gear": "Top gear {value}",
  "settings.car.confidence.part_transmission": "Transmission {value}",
  "settings.car.confidence.official_exact": "official source",
  "settings.car.confidence.official_derived": "officially derived",
  "settings.car.confidence.reputable_secondary_crosschecked":
    "secondary cross-check",
  "settings.car.confidence.family_default": "family default",
  "settings.car.confidence.unverified": "unverified",
  "settings.car.confidence.user_confirmed": "user confirmed",
  "settings.car.confidence.review_detail":
    "Review or override these values in Analysis before trusting driveshaft or engine-order results.",
  "settings.car.col_tires": "Tires",
  "settings.car.col_drive": "Drive",
  "settings.car.col_gear": "Top Gear",
  "settings.car.active_label": "Active",
  "settings.car.inactive_label": "Inactive",
  "settings.car.ready_label": "Ready",
  "settings.car.incomplete_label": "Needs specs",
  "settings.car.value_missing": "Not set",
  "settings.car.tires_missing": "Tire size not set",
  "settings.car.incomplete_detail":
    "Open Analysis to finish the missing tire and drivetrain specs before using this car.",
  "settings.car.activate": "Activate",
  "settings.car.delete": "Delete",
  "settings.car.finish_setup": "Finish setup",
  "settings.car.open_analysis": "Open Analysis",
  "settings.car.finish_choose_path":
    "Choose a library gearbox or edit the manual specs to finish.",
  "settings.car.finish_manual_ready":
    "Manual path selected. Add Car will use the values entered below.",
  "settings.car.finish_manual_missing":
    "Enter positive tire and gearbox values to finish.",
};

function t(key: string, vars?: Record<string, unknown>): string {
  if (key.startsWith("settings.car.confidence.part_")) {
    return (labels[key] ?? key).replace("{value}", String(vars?.value ?? ""));
  }
  return labels[key] ?? key;
}

function fmt(value: number, digits = 0): string {
  return Number(value).toFixed(digits);
}

function makeOrderStatus(
  overrides: Partial<CarOrderReferenceStatus> = {},
): CarOrderReferenceStatus {
  return {
    selection_source_status: "exact_row",
    tire_dimensions_confidence: "official_exact",
    final_drive_ratio_confidence: "official_exact",
    current_gear_ratio_confidence: "official_exact",
    transmission_name: "8-speed automatic",
    transmission_confidence: "official_exact",
    requires_manual_confirmation: false,
    ...overrides,
  };
}

function makeGearbox(
  overrides: Partial<CarLibraryGearbox> = {},
): CarLibraryGearbox {
  return {
    name: "8-speed automatic",
    final_drive_ratio: 3.15,
    top_gear_ratio: 0.67,
    final_drive_ratio_confidence: "official_exact",
    top_gear_ratio_confidence: "official_exact",
    transmission_confidence: "official_exact",
    requires_manual_confirmation: false,
    source_status: "exact_row",
    ...overrides,
  };
}

function makeTireOption(
  overrides: Partial<CarLibraryTireOption> = {},
): CarLibraryTireOption {
  return {
    default_axle_for_speed: "rear",
    front: {
      width_mm: 225,
      aspect_pct: 45,
      rim_in: 18,
    },
    name: "Factory rear",
    rear: null,
    rim_in: 18,
    source_confidence: "official_exact",
    tire_aspect_pct: 45,
    tire_width_mm: 225,
    ...overrides,
  };
}

function makeCar(overrides: Partial<CarRecord> = {}): CarRecord {
  return {
    id: "car-1",
    name: "Demo Car",
    type: "Coupe",
    variant: null,
    aspects: {
      tire_width_mm: 245,
      tire_aspect_pct: 40,
      rim_in: 18,
      final_drive_ratio: 3.91,
      current_gear_ratio: 0.82,
    },
    ...overrides,
  };
}

test("buildOrderReferenceConfidenceDetail distinguishes exact and approximate status", () => {
  expect(buildOrderReferenceConfidenceDetail(makeOrderStatus(), t)).toBe(
    "Tires official source · Drive official source · Top gear official source · Transmission official source",
  );
  expect(
    buildOrderReferenceConfidenceDetail(
      makeOrderStatus({
        tire_dimensions_confidence: "family_default",
        final_drive_ratio_confidence: "family_default",
        current_gear_ratio_confidence: "family_default",
        transmission_confidence: "family_default",
        requires_manual_confirmation: true,
      }),
      t,
    ),
  ).toBe(
    "Tires family default · Drive family default · Top gear family default · Transmission family default. Review or override these values in Analysis before trusting driveshaft or engine-order results.",
  );
});

test("buildOrderReferenceConfidenceDetail preserves user-confirmed manual values", () => {
  expect(
    buildOrderReferenceConfidenceDetail(
      makeOrderStatus({
        selection_source_status: "manual_entry",
        tire_dimensions_confidence: "user_confirmed",
        final_drive_ratio_confidence: "user_confirmed",
        current_gear_ratio_confidence: "user_confirmed",
        transmission_name: null,
        transmission_confidence: null,
      }),
      t,
    ),
  ).toBe(
    "Tires user confirmed · Drive user confirmed · Top gear user confirmed",
  );
});

test("buildGearboxConfidenceHint feeds the wizard action hint for approximate library selections", () => {
  const state = createInitialWizardState();
  state.step = 4;
  state.specBranch = "library";
  state.selectedTire = makeTireOption();
  state.selectedGearbox = makeGearbox({
    final_drive_ratio_confidence: "reputable_secondary_crosschecked",
    top_gear_ratio_confidence: "family_default",
    transmission_confidence: "unverified",
    requires_manual_confirmation: true,
  });
  state.selectedModel = {
    brand: "BMW",
    gearboxes: [state.selectedGearbox],
    model: "M340i",
    rim_in: 18,
    tire_aspect_pct: 45,
    tire_options: [state.selectedTire],
    tire_width_mm: 225,
    type: "Sedan",
    variants: [],
  };

  expect(buildGearboxConfidenceHint(state.selectedGearbox, t)).toBe(
    "Drive secondary cross-check · Top gear family default · Transmission unverified. Review or override these values in Analysis before trusting driveshaft or engine-order results.",
  );
  expect(
    getWizardActionHint(state, {
      fmt,
      manualGearbox: null,
      manualTire: null,
      t,
    }),
  ).toBe(
    "Drive secondary cross-check · Top gear family default · Transmission unverified. Review or override these values in Analysis before trusting driveshaft or engine-order results.",
  );
});

test("buildSettingsCarListRenderModel shows exact confidence detail for ready cars", () => {
  const model = buildSettingsCarListRenderModel({
    cars: [makeCar({ order_reference_status: makeOrderStatus() })],
    activeCarId: "car-1",
    fmt,
    t,
  });

  expect(model.kind).toBe("rows");
  if (model.kind !== "rows") {
    throw new Error("Expected rows");
  }
  expect(model.rows[0].completionDetailText).toBe(
    "Tires official source · Drive official source · Top gear official source · Transmission official source",
  );
});

import { expect, test } from "vitest";
import type {
  CarLibraryGearbox,
  CarLibraryModel,
  CarLibraryTireOption,
  CarRecord,
} from "../src/api/types";
import { getCarCompleteness } from "../src/car_selection";
import { carRows, guidance } from "../src/pages/cars/car_list_model";
import {
  formatCarLibraryTireOption,
  tireSetupAspectsFromOption,
} from "../src/pages/cars/tires";
import {
  actionHint,
  canFinish,
  carRequest,
  EMPTY_MANUAL_INPUTS,
  firstMissingManualField,
  gearboxDetail,
  INITIAL_WIZARD_STATE,
  progressText,
  specBranch,
  summary,
  type WizardState,
} from "../src/pages/cars/wizard_model";

function makeCar(overrides: Partial<CarRecord> = {}): CarRecord {
  return {
    id: "car-1",
    name: "Demo Car",
    type: "Coupe",
    variant: null,
    aspects: {},
    ...overrides,
  };
}

const labels: Record<string, string> = {
  "settings.car.empty.title": "Add the first car profile.",
  "settings.car.empty.body":
    "Cars define the setup used for recording, saved runs, and analysis settings.",
  "settings.car.empty.detail":
    "Start with the add-car wizard so the next recording has the right context.",
  "settings.car.empty.action": "Add a car",
  "settings.car.col_tires": "Tires",
  "settings.car.col_drive": "Drive",
  "settings.car.col_gear": "Top Gear",
  "settings.car.active_label": "Active",
  "settings.car.inactive_label": "Inactive",
  "settings.car.ready_label": "Ready",
  "settings.car.incomplete_label": "Needs specs",
  "settings.car.just_added": "New",
  "settings.car.activate": "Activate",
  "settings.car.delete": "Delete",
  "settings.car.finish_setup": "Finish setup",
  "settings.car.open_analysis": "Open Analysis",
  "settings.car.value_missing": "Not set",
  "settings.car.tires_missing": "Tire size not set",
  "settings.car.incomplete_detail":
    "Open Analysis to finish the missing tire and drivetrain specs before using this car.",
  "settings.car.approximate_detail":
    "Approximate drivetrain ratios need review.",
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
  "settings.car.created_title": "Car added",
  "settings.car.created_body": "{name} was added and selected for this setup.",
  "settings.car.created_detail":
    "Review the highlighted row below or open Analysis to confirm the setup before the next run.",
  "settings.car.guidance.no_active_title": "Activate one car for this setup.",
  "settings.car.guidance.no_active":
    "Activate a car from the list below or add a new one to unlock analysis settings.",
  "settings.car.guidance.no_active_detail":
    "Use Activate on a ready row, or Finish setup on an incomplete row, to unlock the rest of Settings.",
};

function t(key: string, vars?: Record<string, unknown>): string {
  if (key === "settings.car.created_body") {
    return `${vars?.name ?? "Unknown"} was added and selected for this setup.`;
  }
  if (key === "settings.car.confidence.part_tires") {
    return `Tires ${vars?.value ?? ""}`.trim();
  }
  if (key === "settings.car.confidence.part_drive") {
    return `Drive ${vars?.value ?? ""}`.trim();
  }
  if (key === "settings.car.confidence.part_gear") {
    return `Top gear ${vars?.value ?? ""}`.trim();
  }
  if (key === "settings.car.confidence.part_transmission") {
    return `Transmission ${vars?.value ?? ""}`.trim();
  }
  return labels[key] ?? key;
}

function fmt(value: number, digits = 0): string {
  return Number(value).toFixed(digits);
}

const complete = {
  tire_width_mm: 225,
  tire_aspect_pct: 45,
  rim_in: 18,
  final_drive_ratio: 3.08,
  current_gear_ratio: 0.64,
};

test("getCarCompleteness needs only the tire size; ratios are optional", () => {
  expect(getCarCompleteness(makeCar({ aspects: complete }))).toEqual({
    isComplete: true,
    missingKeys: [],
  });
  expect(
    getCarCompleteness(
      makeCar({
        aspects: {
          ...complete,
          final_drive_ratio: null,
          current_gear_ratio: null,
        },
      }),
    ).isComplete,
  ).toBe(true);
  expect(
    getCarCompleteness(makeCar({ aspects: { tire_width_mm: 245, rim_in: 0 } }))
      .missingKeys,
  ).toEqual(["tire_aspect_pct", "rim_in"]);
});

test("car rows carry readiness, highlight, and the next action", () => {
  const rows = carRows(
    [
      makeCar({ id: "active", name: "Ready Car", aspects: complete }),
      makeCar({ id: "inactive", name: "Ready Inactive", aspects: complete }),
      makeCar({
        id: "new",
        name: "Needs Work",
        variant: "Project",
        aspects: { tire_width_mm: 245 },
      }),
    ],
    "active",
    "new",
    fmt,
    t,
  );
  expect(rows[0]).toMatchObject({
    activeText: "Active",
    isComplete: true,
    detail: null,
    primaryAction: null,
    readinessText: "Ready",
  });
  expect(rows[1].primaryAction).toEqual({
    type: "activate",
    label: "Activate",
    className: "btn car-activate-btn",
  });
  expect(rows[2]).toMatchObject({
    isHighlighted: true,
    variant: "Project",
    readinessText: "Needs specs",
    detail:
      "Open Analysis to finish the missing tire and drivetrain specs before using this car.",
    primaryAction: {
      type: "complete",
      label: "Finish setup",
      className: "btn btn--primary car-complete-btn",
    },
    metrics: [
      { label: "Tires", value: "Tire size not set", code: true },
      { label: "Drive", value: "Not set" },
      { label: "Top Gear", value: "Not set" },
    ],
  });
});

test("ready cars explain approximate drivetrain sources", () => {
  const [row] = carRows(
    [
      makeCar({
        aspects: complete,
        order_reference_status: {
          selection_source_status: "exact_row",
          final_drive_ratio_confidence: "family_default",
          current_gear_ratio_confidence: "family_default",
          transmission_name: "8-speed automatic",
          transmission_confidence: "family_default",
          requires_manual_confirmation: true,
        },
      }),
    ],
    null,
    null,
    fmt,
    t,
  );
  expect(row.detail).toBe(
    "Drive family default · Top gear family default · Transmission family default. Review or override these values in Analysis before trusting driveshaft or engine-order results.",
  );
  const [userConfirmed] = carRows(
    [
      makeCar({
        aspects: complete,
        order_reference_status: {
          tire_dimensions_confidence: "user_confirmed",
          final_drive_ratio_confidence: "user_confirmed",
          current_gear_ratio_confidence: "user_confirmed",
          requires_manual_confirmation: false,
          selection_source_status: "manual_entry",
        },
      }),
    ],
    null,
    null,
    fmt,
    t,
  );
  expect(userConfirmed.detail).toBe(
    "Tires user confirmed · Drive user confirmed · Top gear user confirmed",
  );
});

test("staggered tires show front and rear sizes", () => {
  const [row] = carRows(
    [
      makeCar({
        aspects: {
          ...complete,
          front_tire_width_mm: 275,
          front_tire_aspect_pct: 35,
          front_rim_in: 22,
          rear_tire_width_mm: 315,
          rear_tire_aspect_pct: 30,
          rear_rim_in: 22,
        },
      }),
    ],
    null,
    null,
    fmt,
    t,
  );
  expect(row.metrics[0].value).toBe("Front 275/35R22 · Rear 315/30R22");
});

test("guidance shows creation feedback or asks for an active car", () => {
  const car = makeCar();
  expect(guidance({ kind: "loading" }, null, t)).toBeNull();
  expect(guidance({ kind: "no_cars" }, null, t)).toBeNull();
  expect(guidance({ kind: "active", car }, null, t)).toBeNull();
  expect(
    guidance({ kind: "active", car }, { carName: "Demo Car" }, t),
  ).toMatchObject({
    title: "Car added",
    body: "Demo Car was added and selected for this setup.",
    tone: "success",
  });
  expect(guidance({ kind: "no_active_car" }, null, t)).toMatchObject({
    title: "Activate one car for this setup.",
    tone: "default",
  });
});

const GEARBOX: CarLibraryGearbox = {
  name: "6-speed manual",
  final_drive_ratio: 3.94,
  top_gear_ratio: 0.79,
  final_drive_ratio_confidence: "family_default",
  top_gear_ratio_confidence: "family_default",
  requires_manual_confirmation: true,
};

const TIRE: CarLibraryTireOption = {
  name: "Sport",
  default_axle_for_speed: "front",
  front: { width_mm: 225, aspect_pct: 40, rim_in: 18 },
  rear: { width_mm: 255, aspect_pct: 35, rim_in: 18 },
  tire_width_mm: 225,
  tire_aspect_pct: 40,
  rim_in: 18,
  source_confidence: "official_exact",
};

const MODEL: CarLibraryModel = {
  brand: "VW",
  type: "Hatchback",
  model: "Golf",
  tire_width_mm: 225,
  tire_aspect_pct: 40,
  rim_in: 18,
  tire_options: [TIRE],
  gearboxes: [GEARBOX],
  variants: [],
};

function specs(overrides: Partial<WizardState> = {}): WizardState {
  return {
    ...INITIAL_WIZARD_STATE,
    step: 4,
    brand: "VW",
    carType: "Hatchback",
    model: "Golf",
    selectedModel: MODEL,
    ...overrides,
  };
}

test("tire options format staggered sizes and keep front/rear aspects", () => {
  expect(formatCarLibraryTireOption(TIRE, fmt)).toBe(
    "Front 225/40R18 · Rear 255/35R18",
  );
  expect(tireSetupAspectsFromOption(TIRE)).toMatchObject({
    front_tire_width_mm: 225,
    rear_tire_width_mm: 255,
    default_axle_for_speed: "front",
  });
});

test("the specs step needs both a library tire and gearbox, or every manual value", () => {
  expect(specBranch(specs())).toBeNull();
  expect(
    canFinish(
      specs({ selectedTire: TIRE, specBranch: "library" }),
      EMPTY_MANUAL_INPUTS,
    ),
  ).toBe(false);
  const library = specs({
    selectedTire: TIRE,
    selectedGearbox: GEARBOX,
    specBranch: "library",
  });
  expect(canFinish(library, EMPTY_MANUAL_INPUTS)).toBe(true);
  expect(actionHint(library, EMPTY_MANUAL_INPUTS, t)).toBe(
    "Drive family default · Top gear family default. Review or override these values in Analysis before trusting driveshaft or engine-order results.",
  );
  // Without library gearboxes the manual branch is forced.
  const noGearbox = specs({ selectedModel: { ...MODEL, gearboxes: [] } });
  expect(specBranch(noGearbox)).toBe("manual");
  const inputs = {
    tireWidth: "225",
    tireAspect: "40",
    rim: "18",
    finalDrive: "",
    topGear: "0.8",
  };
  expect(firstMissingManualField(inputs)).toBe("finalDrive");
  expect(canFinish(noGearbox, inputs)).toBe(false);
  expect(canFinish(noGearbox, { ...inputs, finalDrive: "4.1" })).toBe(true);
});

test("the created car records where each spec came from", () => {
  expect(
    carRequest(
      specs({ selectedTire: TIRE, specBranch: "library" }),
      EMPTY_MANUAL_INPUTS,
    ),
  ).toEqual({ ok: false, focus: "gearbox-option" });
  const library = carRequest(
    specs({
      selectedTire: TIRE,
      selectedGearbox: GEARBOX,
      specBranch: "library",
    }),
    EMPTY_MANUAL_INPUTS,
  );
  expect(library).toMatchObject({
    ok: true,
    aspects: {
      final_drive_ratio: 3.94,
      current_gear_ratio: 0.79,
      front_tire_width_mm: 225,
    },
    status: {
      tire_dimensions_confidence: "official_exact",
      final_drive_ratio_confidence: "family_default",
      transmission_confidence: "unverified",
      requires_manual_confirmation: true,
      selection_source_status: "exact_row",
      transmission_name: "6-speed manual",
    },
  });
  const manual = specs({ selectedTire: TIRE, specBranch: "manual" });
  const kept = {
    tireWidth: "225",
    tireAspect: "40",
    rim: "18",
    finalDrive: "4.1",
    topGear: "0.8",
  };
  expect(carRequest(manual, kept)).toMatchObject({
    ok: true,
    aspects: { rear_tire_width_mm: 255, final_drive_ratio: 4.1 },
    status: {
      tire_dimensions_confidence: "official_exact",
      final_drive_ratio_confidence: "user_confirmed",
      selection_source_status: "manual_entry",
    },
  });
  expect(carRequest(manual, { ...kept, tireWidth: "235" })).toMatchObject({
    ok: true,
    aspects: { tire_width_mm: 235 },
    status: { tire_dimensions_confidence: "user_confirmed" },
  });
  expect(carRequest(manual, { ...kept, rim: "" })).toEqual({
    ok: false,
    focus: "rim",
  });
});

test("a library gearbox without a final drive saves it as unknown", () => {
  const noFinalDrive: CarLibraryGearbox = {
    ...GEARBOX,
    final_drive_ratio: null,
    final_drive_ratio_confidence: null,
  };
  expect(gearboxDetail(noFinalDrive, fmt, t)).toBe(
    "FD: settings.car.ratio_unknown · Top Gear: 0.79",
  );
  expect(
    carRequest(
      specs({
        selectedTire: TIRE,
        selectedGearbox: noFinalDrive,
        specBranch: "library",
      }),
      EMPTY_MANUAL_INPUTS,
    ),
  ).toMatchObject({
    ok: true,
    aspects: { final_drive_ratio: null, current_gear_ratio: 0.79 },
    status: { final_drive_ratio_confidence: null },
  });
});

test("the summary fills in as the wizard advances", () => {
  const early = summary(
    { ...INITIAL_WIZARD_STATE, step: 1, brand: "VW" },
    EMPTY_MANUAL_INPUTS,
    fmt,
    t,
  );
  expect(early.profileName).toBe("settings.car.wizard_summary_pending");
  expect(early.rows).toEqual([
    { label: "settings.car.wizard_summary_brand", value: "VW" },
  ]);
  const done = summary(
    specs({
      selectedTire: TIRE,
      selectedGearbox: GEARBOX,
      specBranch: "library",
    }),
    EMPTY_MANUAL_INPUTS,
    fmt,
    t,
  );
  expect(done.profileName).toBe("VW Golf");
  expect(done.rows.map((row) => row.value)).toEqual([
    "VW",
    "Hatchback",
    "Golf",
    "settings.car.wizard_summary_not_needed",
    "Sport · Front 225/40R18 · Rear 255/35R18",
    "6-speed manual",
  ]);
  expect(progressText(4, t)).toBe("settings.car.wizard_progress");
});

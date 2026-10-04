import { expect, test } from "vitest";
import type {
  CarLibraryGearbox,
  CarLibraryModel,
  CarLibraryTireOption,
  CarRecord,
} from "../src/api/types";
import {
  capabilityMark,
  capabilityNoteKey,
  carCapabilities,
} from "../src/capabilities";
import type { ReferenceProvenance } from "../src/car_references";
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
  editRequest,
  editTarget,
  firstInvalidField,
  gearboxParts,
  INITIAL_WIZARD_STATE,
  parseTireSize,
  progressText,
  specProvenance,
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

/** Echoes the key, plus its variables, so tests pin the catalog key used. */
function t(key: string, vars?: Record<string, unknown>): string {
  return vars ? `${key}:${JSON.stringify(vars)}` : key;
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

test("car rows show each reference's source and what the car can test", () => {
  const rows = carRows(
    [
      makeCar({
        id: "active",
        name: "Ready Car",
        aspects: complete,
        order_reference_status: {
          tire_dimensions_confidence: "official_exact",
          final_drive_ratio_confidence: "reputable_secondary_crosschecked",
          current_gear_ratio_confidence: "user_confirmed",
          requires_manual_confirmation: false,
          selection_source_status: "manual_entry",
        },
      }),
      makeCar({
        id: "estimated",
        aspects: complete,
        order_reference_status: {
          final_drive_ratio_confidence: "family_default",
          current_gear_ratio_confidence: "family_default",
          requires_manual_confirmation: true,
          selection_source_status: "exact_row",
        },
      }),
      makeCar({
        id: "new",
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
    isComplete: true,
    detail: null,
    activateLabel: null,
    editLabel: "settings.car.edit",
    capabilities: {
      wheel: "ok",
      driveline: "ok",
      engine: "estimated_top_gear",
    },
  });
  expect(rows[0].metrics.map((metric) => [metric.value, metric.tier])).toEqual([
    ["225/45R18", "exact"],
    ["3.08", "checked"],
    ["0.64", "user"],
  ]);
  // Library estimates are flagged on the row, with what they mean for a run.
  expect(rows[1]).toMatchObject({
    activateLabel: "settings.car.activate",
    detail: "settings.car.estimate.both settings.car.confidence.review_detail",
    capabilities: {
      driveline: "estimated_final_drive",
      engine: "estimated_ratios",
    },
  });
  // A value saved without a confidence was typed in by the user.
  expect(rows[1].metrics[0].tier).toBe("user");
  expect(rows[2]).toMatchObject({
    isHighlighted: true,
    variant: "Project",
    readinessText: "settings.car.incomplete_label",
    detail: "settings.car.incomplete_detail",
    activateLabel: null,
    editLabel: "settings.car.finish_setup",
    capabilities: {
      wheel: "missing_tire",
      driveline: "missing_tire",
      engine: "missing_tire",
    },
  });
  expect(rows[2].metrics.map((metric) => [metric.value, metric.tier])).toEqual([
    ["settings.car.tires_missing", "missing"],
    ["settings.car.value_missing", "missing"],
    ["settings.car.value_missing", "missing"],
  ]);
});

test("a car's capabilities follow its references like the server's readiness", () => {
  const refs = (
    tire: ReferenceProvenance,
    finalDrive: ReferenceProvenance,
    topGear: ReferenceProvenance,
  ) => carCapabilities({ tire, finalDrive, topGear });
  expect(refs("user_confirmed", "missing", "missing")).toEqual({
    wheel: "ok",
    driveline: "missing_final_drive",
    engine: "missing_ratios",
  });
  // The engine note names exactly the ratio that is missing.
  expect(refs("official_exact", "official_derived", "missing")).toEqual({
    wheel: "ok",
    driveline: "ok",
    engine: "missing_top_gear",
  });
  expect(refs("official_exact", "missing", "user_confirmed")).toEqual({
    wheel: "ok",
    driveline: "missing_final_drive",
    engine: "missing_final_drive",
  });
  expect(refs("official_exact", "unverified", "official_exact")).toEqual({
    wheel: "ok",
    driveline: "estimated_final_drive",
    engine: "estimated_ratios",
  });
  expect(refs("official_exact", "official_exact", "family_default")).toEqual({
    wheel: "ok",
    driveline: "ok",
    engine: "estimated_ratios",
  });
  expect(refs("missing", "official_exact", "official_exact").engine).toBe(
    "missing_tire",
  );
  expect(
    [
      "ok",
      "measured",
      "estimated_final_drive",
      "estimated_ratios",
      "missing_tire",
      "manual_speed",
    ].map(capabilityMark),
  ).toEqual(["ok", "ok", "caveat", "caveat", "no", "no"]);
  expect(capabilityNoteKey("wheel", "ok")).toBeNull();
  expect(capabilityNoteKey("engine", "missing_top_gear")).toBe(
    "capabilities.engine.missing_top_gear",
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
    title: "settings.car.created_title",
    body: 'settings.car.created_body:{"name":"Demo Car"}',
    tone: "success",
  });
  expect(guidance({ kind: "no_active_car" }, null, t)).toMatchObject({
    title: "settings.car.guidance.no_active_title",
    tone: "default",
  });
});

const GEARBOX: CarLibraryGearbox = {
  name: "6-speed manual",
  final_drive_ratio: 3.94,
  top_gear_ratio: 0.79,
  fuel_type: "PHEV",
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

test("a pasted tire size reads the common sidewall spellings", () => {
  const size = { tireWidth: "225", tireAspect: "45", rim: "18" };
  for (const text of [
    "225/45 R18",
    "225/45ZR18",
    "P225/45R18 94W",
    "225 45 18",
    "225/45-18",
  ]) {
    expect(parseTireSize(text)).toEqual(size);
  }
  expect(parseTireSize("205/55 R16,5")).toEqual({
    tireWidth: "205",
    tireAspect: "55",
    rim: "16.5",
  });
  expect(parseTireSize("18 inch")).toBeNull();
});

const TYPED = {
  tireWidth: "225",
  tireAspect: "40",
  rim: "18",
  finalDrive: "",
  topGear: "",
};

test("the specs step needs a tire size; the ratios are optional but must be readable", () => {
  expect(firstInvalidField(EMPTY_MANUAL_INPUTS)).toBe("tireWidth");
  expect(firstInvalidField({ ...TYPED, rim: "0" })).toBe("rim");
  expect(firstInvalidField(TYPED)).toBeNull();
  expect(firstInvalidField({ ...TYPED, topGear: "abc" })).toBe("topGear");
  expect(canFinish(specs(), TYPED)).toBe(true);
  expect(canFinish(specs({ step: 3 }), TYPED)).toBe(false);

  const hint = (state: WizardState, inputs: typeof TYPED) =>
    actionHint(state, inputs, 1, t);
  expect(hint(specs(), EMPTY_MANUAL_INPUTS)).toBe(
    "settings.car.finish_needs_tire",
  );
  expect(hint(specs(), { ...TYPED, finalDrive: "-1" })).toBe(
    "settings.car.finish_ratio_invalid",
  );
  // The library has a gearbox the user has not picked yet.
  expect(hint(specs(), TYPED)).toBe("settings.car.finish_pick_gearbox");
  expect(actionHint(specs(), TYPED, 0, t)).toBe("settings.car.finish_ready");
  // A kept family-default gearbox says what the estimate means for a run.
  const kept = { ...TYPED, finalDrive: "3.94", topGear: "0.79" };
  expect(hint(specs({ selectedGearbox: GEARBOX }), kept)).toBe(
    "settings.car.estimate.both settings.car.estimate.edit_hint",
  );
});

test("each saved spec records where it came from", () => {
  const library = specs({ selectedTire: TIRE, selectedGearbox: GEARBOX });
  const kept = { ...TYPED, finalDrive: "3.94", topGear: "0.79" };
  expect(specProvenance(library, kept)).toEqual({
    tire: "official_exact",
    finalDrive: "family_default",
    topGear: "family_default",
  });
  expect(carRequest(library, kept)).toMatchObject({
    ok: true,
    aspects: {
      final_drive_ratio: 3.94,
      current_gear_ratio: 0.79,
      front_tire_width_mm: 225,
      rear_tire_width_mm: 255,
    },
    status: {
      tire_dimensions_confidence: "official_exact",
      final_drive_ratio_confidence: "family_default",
      requires_manual_confirmation: true,
      selection_source_status: "exact_row",
      transmission_name: "6-speed manual",
      transmission_confidence: "unverified",
    },
    fuelType: "PHEV",
  });

  // Typing the exact figure over an estimate makes it the user's.
  const corrected = carRequest(library, { ...kept, finalDrive: "4.1" });
  expect(corrected).toMatchObject({
    ok: true,
    aspects: { final_drive_ratio: 4.1 },
    status: {
      final_drive_ratio_confidence: "user_confirmed",
      current_gear_ratio_confidence: "family_default",
      requires_manual_confirmation: true,
      selection_source_status: "manual_entry",
    },
  });

  // "I don't know" saves no value and no confidence, never a default.
  const unknown = carRequest(library, { ...kept, finalDrive: "", topGear: "" });
  expect(unknown).toMatchObject({
    ok: true,
    aspects: { final_drive_ratio: null, current_gear_ratio: null },
    status: {
      final_drive_ratio_confidence: null,
      current_gear_ratio_confidence: null,
      requires_manual_confirmation: false,
    },
  });

  // A custom car is all the user's; an unreadable ratio is refused.
  const custom = specs({ libraryMiss: "brand", selectedModel: null });
  expect(carRequest(custom, { ...TYPED, rim: "17" })).toEqual({
    ok: true,
    aspects: {
      current_gear_ratio: null,
      final_drive_ratio: null,
      rim_in: 17,
      tire_aspect_pct: 40,
      tire_width_mm: 225,
    },
    status: {
      tire_dimensions_confidence: "user_confirmed",
      final_drive_ratio_confidence: null,
      current_gear_ratio_confidence: null,
      requires_manual_confirmation: false,
      selection_source_status: "manual_entry",
    },
    fuelType: null,
  });
  expect(carRequest(custom, { ...TYPED, topGear: "x" })).toEqual({
    ok: false,
    focus: "topGear",
  });
});

test("gearbox options carry a confidence chip per ratio", () => {
  expect(
    gearboxParts(
      {
        ...GEARBOX,
        final_drive_ratio: null,
        final_drive_ratio_confidence: null,
        top_gear_ratio_confidence: "official_exact",
      },
      fmt,
      t,
    ),
  ).toEqual([
    {
      text: 'settings.car.gearbox_final_drive:{"value":"settings.car.ratio_unknown"}',
      tier: "missing",
    },
    { text: 'settings.car.gearbox_top_gear:{"value":"0.79"}', tier: "exact" },
  ]);
});

test("editing a car sends only what changed, and clearing a ratio unsets it", () => {
  const car = makeCar({
    aspects: complete,
    order_reference_status: {
      tire_dimensions_confidence: "official_exact",
      final_drive_ratio_confidence: "family_default",
      current_gear_ratio_confidence: "family_default",
      requires_manual_confirmation: true,
      selection_source_status: "exact_row",
    },
  });
  const { target, inputs } = editTarget(car, fmt);
  expect(inputs).toEqual({
    tireWidth: "225",
    tireAspect: "45",
    rim: "18",
    finalDrive: "3.08",
    topGear: "0.64",
  });
  expect(target.staggeredTire).toBeNull();
  const editing = { ...INITIAL_WIZARD_STATE, step: 4, editing: target };
  // Unchanged values keep their saved source.
  expect(specProvenance(editing, inputs)).toEqual({
    tire: "official_exact",
    finalDrive: "family_default",
    topGear: "family_default",
  });
  expect(editRequest(target, inputs)).toEqual({ ok: true, aspects: {} });
  const changed = { ...inputs, finalDrive: "3.15", topGear: "" };
  expect(specProvenance(editing, changed)).toMatchObject({
    finalDrive: "user_confirmed",
    topGear: "missing",
  });
  expect(editRequest(target, changed)).toEqual({
    ok: true,
    aspects: { final_drive_ratio: 3.15, current_gear_ratio: null },
  });
  expect(editRequest(target, { ...inputs, rim: "19" })).toEqual({
    ok: true,
    aspects: { tire_width_mm: 225, tire_aspect_pct: 45, rim_in: 19 },
  });
  expect(editRequest(target, { ...inputs, tireWidth: "" })).toEqual({
    ok: false,
    focus: "tireWidth",
  });

  const staggered = editTarget(
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
    fmt,
  );
  expect(staggered.inputs.tireWidth).toBe("275");
  expect(staggered.target.staggeredTire).toBe(
    "Front 275/35R22 · Rear 315/30R22",
  );
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
    specs({ selectedTire: TIRE, selectedGearbox: GEARBOX }),
    { ...TYPED, finalDrive: "3.94", topGear: "" },
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
    '6-speed manual · settings.car.wizard_summary_manual_gearbox:{"finalDrive":"3.94","topGear":"settings.car.ratio_unknown"}',
  ]);
  expect(progressText(4, t)).toBe(
    'settings.car.wizard_progress:{"current":5,"step":"settings.car.step_specs_short","total":5}',
  );
});

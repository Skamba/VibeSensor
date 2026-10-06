import { expect, test } from "vitest";
import type {
  CarLibraryGearbox,
  CarLibraryModel,
  CarLibraryTireOption,
  CarRecord,
} from "../src/api/types";
import {
  capabilityFamilyKey,
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
  asksDriveLayout,
  asksPowertrain,
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
  ratioInputsFromGearbox,
  selectionTrail,
  specProvenance,
  summary,
  tireSizeFromInputs,
  type WizardState,
  variantDetail,
  wizardDriveLayout,
  wizardFuelType,
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
    ["settings.car.drive_layout.unknown", undefined],
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
    ["settings.car.drive_layout.unknown", undefined],
  ]);
});

test("a car's capabilities follow its references like the server's readiness", () => {
  const refs = (
    tire: ReferenceProvenance,
    finalDrive: ReferenceProvenance,
    topGear: ReferenceProvenance,
  ) => carCapabilities({ tire, finalDrive, topGear }, null);
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

test("an EV row names its reduction ratio and motor, not a final drive", () => {
  const [estimated, incomplete] = carRows(
    [
      makeCar({
        id: "ev",
        fuel_type: "EV",
        aspects: complete,
        order_reference_status: {
          final_drive_ratio_confidence: "family_default",
          requires_manual_confirmation: true,
          selection_source_status: "exact_row",
        },
      }),
      makeCar({
        id: "new-ev",
        fuel_type: "EV",
        aspects: { tire_width_mm: 245 },
      }),
    ],
    "ev",
    null,
    fmt,
    t,
  );
  expect(estimated.metrics.map((metric) => metric.label)).toEqual([
    "settings.car.col_tires",
    "settings.car.col_reduction",
    "settings.car.col_drive_layout",
  ]);
  expect(estimated.detail).toBe(
    "settings.car.estimate.final_drive_ev settings.car.confidence.review_detail",
  );
  expect(incomplete.detail).toBe("settings.car.incomplete_detail_ev");
});

test("the powertrain decides what the engine check can do", () => {
  const estimated = {
    tire: "official_exact",
    finalDrive: "official_exact",
    topGear: "family_default",
  } as const;
  // An EV has no engine: its motor is the driveline order.
  expect(carCapabilities(estimated, "EV")).toEqual({
    wheel: "ok",
    driveline: "ok",
    engine: "not_applicable",
  });
  expect(capabilityMark("not_applicable")).toBe("na");
  expect(capabilityFamilyKey("driveline", "EV")).toBe(
    "capabilities.family.motor",
  );
  expect(capabilityFamilyKey("engine", "EV")).toBe(
    "capabilities.family.combustion_engine",
  );
  expect(capabilityFamilyKey("driveline", "PHEV")).toBe(
    "capabilities.family.driveline",
  );
  // A plug-in hybrid's estimate is hedged (its engine may be off); a missing
  // reference still names what is missing.
  expect(carCapabilities(estimated, "PHEV").engine).toBe("hybrid_estimated");
  expect(capabilityMark("hybrid_estimated")).toBe("caveat");
  expect(
    carCapabilities({ ...estimated, topGear: "missing" }, "PHEV").engine,
  ).toBe("missing_top_gear");
  expect(carCapabilities(estimated, "ICE").engine).toBe("estimated_ratios");
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

test("the three tire fields read back as a sidewall size the parser accepts", () => {
  const fields = { tireWidth: "225", tireAspect: "55", rim: "17.5" };
  const size = tireSizeFromInputs({ ...EMPTY_MANUAL_INPUTS, ...fields });
  expect(size).toBe("225/55 R17.5");
  expect(parseTireSize(size)).toEqual(fields);
  expect(
    tireSizeFromInputs({ ...EMPTY_MANUAL_INPUTS, ...fields, rim: "" }),
  ).toBe("");
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
    driveLayout: null,
    finalDriveAxle: null,
  });
  expect(carRequest(custom, { ...TYPED, topGear: "x" })).toEqual({
    ok: false,
    focus: "topGear",
  });
});

test("the wizard asks the powertrain only where the library does not say", () => {
  // A library gearbox carries its powertrain: nothing to ask.
  const library = specs({ selectedTire: TIRE, selectedGearbox: GEARBOX });
  expect(asksPowertrain(library)).toBe(false);
  expect(wizardFuelType({ ...library, fuelType: "EV" })).toBe("PHEV");

  // A car entered by hand: the user's pick is saved; unpicked stays unknown.
  const custom = specs({ libraryMiss: "brand", selectedModel: null });
  expect(asksPowertrain(custom)).toBe(true);
  expect(carRequest(custom, TYPED)).toMatchObject({ fuelType: null });
  const ev = { ...custom, fuelType: "EV" as const };
  expect(carRequest(ev, TYPED)).toMatchObject({ ok: true, fuelType: "EV" });
  // An EV has no top gear: the specs need only the tire size and reduction.
  expect(actionHint(ev, TYPED, 0, t)).toBe("settings.car.finish_ready");
  expect(
    summary(ev, { ...TYPED, finalDrive: "9.05" }, fmt, t).rows.at(-1)?.value,
  ).toBe('settings.car.wizard_summary_ev_gearbox:{"finalDrive":"9.05"}');
  // A library EV has no top gear: its single reduction is the final drive.
  const evGearbox = {
    ...GEARBOX,
    fuel_type: "EV" as const,
    final_drive_ratio: 9.05,
    final_drive_ratio_confidence: "official_exact",
    top_gear_ratio: null,
    top_gear_ratio_confidence: null,
  };
  const evPick = specs({ selectedTire: TIRE, selectedGearbox: evGearbox });
  const evInputs = ratioInputsFromGearbox(evGearbox, TYPED);
  expect(evInputs).toMatchObject({ finalDrive: "9.05", topGear: "" });
  expect(actionHint(evPick, evInputs, 1, t)).toBe("settings.car.finish_ready");
  // With an official reduction ratio there is nothing to confirm.
  expect(carRequest(evPick, evInputs)).toMatchObject({
    ok: true,
    fuelType: "EV",
    aspects: { final_drive_ratio: 9.05, current_gear_ratio: null },
    status: {
      final_drive_ratio_confidence: "official_exact",
      current_gear_ratio_confidence: null,
      requires_manual_confirmation: false,
    },
  });
  expect(gearboxParts(evGearbox, fmt, t)).toEqual([
    { text: 'settings.car.gearbox_reduction:{"value":"9.05"}', tier: "exact" },
  ]);
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
  expect(editRequest(editing, inputs)).toEqual({
    ok: true,
    aspects: {},
    fuelType: null,

    driveLayout: null,
  });
  // The editor sets a powertrain the saved car lacks.
  expect(editRequest({ ...editing, fuelType: "EV" }, inputs)).toEqual({
    ok: true,
    aspects: {},
    fuelType: "EV",

    driveLayout: null,
  });
  const changed = { ...inputs, finalDrive: "3.15", topGear: "" };
  expect(specProvenance(editing, changed)).toMatchObject({
    finalDrive: "user_confirmed",
    topGear: "missing",
  });
  expect(editRequest(editing, changed)).toEqual({
    ok: true,
    aspects: { final_drive_ratio: 3.15, current_gear_ratio: null },
    fuelType: null,

    driveLayout: null,
  });
  expect(editRequest(editing, { ...inputs, rim: "19" })).toEqual({
    ok: true,
    aspects: { tire_width_mm: 225, tire_aspect_pct: 45, rim_in: 19 },
    fuelType: null,

    driveLayout: null,
  });
  expect(editRequest(editing, { ...inputs, tireWidth: "" })).toEqual({
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
  // The header trail shows the picks before the current step, so a model
  // left over after Back is not shown on the model step.
  const variant = {
    name: "GTD",
    drivetrain: "FWD",
    engine: "2.0 diesel",
  } as const;
  expect(selectionTrail(specs({ selectedVariant: variant }))).toEqual([
    "VW",
    "Hatchback",
    "Golf",
    "GTD",
  ]);
  expect(selectionTrail(specs({ step: 2 }))).toEqual(["VW", "Hatchback"]);
  expect(selectionTrail(INITIAL_WIZARD_STATE)).toEqual([]);
});

test("a variant names its drivetrain, engine and model years", () => {
  const variant = {
    name: "xDrive25d",
    drivetrain: "AWD",
    engine: "2.0 diesel",
  } as const;
  expect(
    variantDetail({
      ...variant,
      production_start_year: 2016,
      production_end_year: 2022,
    }),
  ).toBe("AWD · 2.0 diesel · 2016\u20132022");
  expect(
    variantDetail({
      ...variant,
      production_start_year: 2021,
      production_end_year: 2021,
    }),
  ).toBe("AWD · 2.0 diesel · 2021");
  expect(variantDetail(variant)).toBe("AWD · 2.0 diesel");
  // A variant split by model year names its years; the detail doesn't repeat them.
  expect(
    variantDetail({
      ...variant,
      name: "xDrive25d (2021)",
      production_start_year: 2021,
      production_end_year: 2021,
    }),
  ).toBe("AWD · 2.0 diesel");
  expect(
    variantDetail({
      ...variant,
      name: "xDrive25d (2016\u20132020)",
      production_start_year: 2016,
      production_end_year: 2020,
    }),
  ).toBe("AWD · 2.0 diesel");
});

test("the wizard asks the drive layout only where the library does not say", () => {
  // A library variant names its layout; its gearbox says which axle its final
  // drive is on.
  const golf = {
    name: "GTD",
    drivetrain: "FWD",
    engine: "2.0 diesel",
  } as const;
  const library = specs({
    selectedVariant: golf,
    selectedTire: TIRE,
    selectedGearbox: { ...GEARBOX, final_drive_axle: "front" },
  });
  expect(asksDriveLayout(library)).toBe(false);
  expect(wizardDriveLayout({ ...library, driveLayout: "RWD" })).toBe("FWD");
  const kept = { ...TYPED, finalDrive: "3.94", topGear: "0.79" };
  expect(carRequest(library, kept)).toMatchObject({
    ok: true,
    driveLayout: "FWD",
    finalDriveAxle: "front",
  });
  // The axle is the gearbox's, whatever final drive is typed: an e-AWD hybrid
  // (225xe: engine on the front axle) stays one when its ratio is corrected.
  expect(
    carRequest(
      { ...library, selectedVariant: { ...golf, drivetrain: "AWD" } },
      { ...kept, finalDrive: "4.1" },
    ),
  ).toMatchObject({ ok: true, driveLayout: "AWD", finalDriveAxle: "front" });
  // A gearbox that doesn't say keeps the axle unknown.
  expect(
    carRequest(
      {
        ...library,
        selectedVariant: { ...golf, drivetrain: "AWD" },
        selectedGearbox: { ...GEARBOX, final_drive_axle: null },
      },
      kept,
    ),
  ).toMatchObject({ ok: true, driveLayout: "AWD", finalDriveAxle: null });

  // A car entered by hand: the user's pick is saved; "don't know" stays unknown.
  const custom = specs({ libraryMiss: "brand", selectedModel: null });
  expect(asksDriveLayout(custom)).toBe(true);
  expect(carRequest(custom, TYPED)).toMatchObject({
    ok: true,
    driveLayout: null,
    finalDriveAxle: null,
  });
  expect(carRequest({ ...custom, driveLayout: "RWD" }, TYPED)).toMatchObject({
    ok: true,
    driveLayout: "RWD",
  });
});

test("the editor sets or changes a saved car's drive layout", () => {
  const { target, inputs } = editTarget(
    makeCar({ aspects: complete, drive_layout: "FWD" }),
    fmt,
  );
  expect(target.driveLayout).toBe("FWD");
  const editing = { ...INITIAL_WIZARD_STATE, step: 4, editing: target };
  expect(asksDriveLayout(editing)).toBe(true);
  expect(wizardDriveLayout(editing)).toBe("FWD");
  expect(editRequest(editing, inputs)).toMatchObject({ driveLayout: null });
  expect(editRequest({ ...editing, driveLayout: "AWD" }, inputs)).toMatchObject(
    { ok: true, aspects: {}, driveLayout: "AWD" },
  );
});

test("car rows show the drive layout, or that it was not given", () => {
  const rows = carRows(
    [
      makeCar({ id: "fwd", aspects: complete, drive_layout: "FWD" }),
      makeCar({ id: "unknown", aspects: complete }),
    ],
    "fwd",
    null,
    fmt,
    t,
  );
  const layout = (index: number) =>
    rows[index].metrics.find(
      (metric) => metric.label === "settings.car.col_drive_layout",
    );
  expect(layout(0)).toEqual({
    label: "settings.car.col_drive_layout",
    value: "settings.car.drive_layout.FWD",
  });
  expect(layout(1)).toEqual({
    label: "settings.car.col_drive_layout",
    value: "settings.car.drive_layout.unknown",
  });
});

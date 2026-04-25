import { expect, test } from "vitest";
import { getCarCompleteness } from "../src/app/car_selection_state";
import {
  buildCarsGuidanceRenderModel,
  buildSettingsCarListRenderModel,
  createSettingsCarListRenderModelMemo,
} from "../src/app/views/settings_car_list_view";
import type { CarRecord } from "../src/api/types";

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
  "settings.car.empty.body": "Cars define the setup used for recording, saved runs, and analysis settings.",
  "settings.car.empty.detail": "Start with the add-car wizard so the next recording has the right context.",
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
  "settings.car.incomplete_detail": "Open Analysis to finish the missing tire and drivetrain specs before using this car.",
  "settings.car.approximate_detail": "Approximate drivetrain ratios need review.",
  "settings.car.created_title": "Car added",
  "settings.car.created_body": "{name} was added and selected for this setup.",
  "settings.car.created_detail": "Review the highlighted row below or open Analysis to confirm the setup before the next run.",
  "settings.car.guidance.no_active_title": "Activate one car for this setup.",
  "settings.car.guidance.no_active": "Activate a car from the list below or add a new one to unlock analysis settings.",
  "settings.car.guidance.no_active_detail": "Use Activate on a ready row, or Finish setup on an incomplete row, to unlock the rest of Settings.",
};

function t(key: string, vars?: Record<string, unknown>): string {
  if (key === "settings.car.created_body") {
    return `${vars?.name ?? "Unknown"} was added and selected for this setup.`;
  }
  return labels[key] ?? key;
}

function fmt(value: number, digits = 0): string {
  return Number(value).toFixed(digits);
}

test("getCarCompleteness reports whether the required car specs are present", () => {
  const complete = getCarCompleteness(makeCar({
    aspects: {
      tire_width_mm: 245,
      tire_aspect_pct: 40,
      rim_in: 18,
      final_drive_ratio: 3.91,
      current_gear_ratio: 0.82,
    },
  }));
  const incomplete = getCarCompleteness(makeCar({
    aspects: {
      tire_width_mm: 245,
      rim_in: 18,
    },
  }));

  expect(complete).toEqual({ isComplete: true, missingKeys: [] });
  expect(incomplete.isComplete).toBe(false);
  expect(incomplete.missingKeys).toEqual([
    "tire_aspect_pct",
    "final_drive_ratio",
    "current_gear_ratio",
  ]);
});

test("buildSettingsCarListRenderModel produces typed row state for readiness, highlight, and actions", () => {
  const model = buildSettingsCarListRenderModel({
    cars: [
      makeCar({
        id: "car-ready",
        name: "Ready Car",
        aspects: {
          tire_width_mm: 245,
          tire_aspect_pct: 40,
          rim_in: 18,
          final_drive_ratio: 3.91,
          current_gear_ratio: 0.82,
        },
      }),
      makeCar({
        id: "car-ready-inactive",
        name: "Ready Inactive",
        aspects: {
          tire_width_mm: 225,
          tire_aspect_pct: 45,
          rim_in: 18,
          final_drive_ratio: 3.08,
          current_gear_ratio: 0.64,
        },
      }),
      makeCar({
        id: "car-new",
        name: "Needs Work",
        variant: "Project",
        aspects: {
          tire_width_mm: 245,
        },
      }),
    ],
    activeCarId: "car-ready",
    highlightedCarId: "car-new",
    t,
    fmt,
  });

  expect(model.kind).toBe("rows");
  if (model.kind !== "rows") {
    return;
  }

  expect(model.rows).toHaveLength(3);
  expect(model.rows[0]).toMatchObject({
    activeState: "active",
    activeStatusText: "Active",
    carId: "car-ready",
    completionDetailText: null,
    displayName: "Ready Car",
    highlightedStatusText: null,
    isComplete: true,
    isHighlighted: false,
    primaryAction: null,
    readinessState: "ready",
    readinessStatusText: "Ready",
  });
  expect(model.rows[1].primaryAction).toEqual({
    className: "btn car-activate-btn",
    labelText: "Activate",
    type: "activate",
  });
  expect(model.rows[1].completionDetailText).toBeNull();
  expect(model.rows[2]).toMatchObject({
    activeState: "inactive",
    carId: "car-new",
    completionDetailText: "Open Analysis to finish the missing tire and drivetrain specs before using this car.",
    highlightedStatusText: "New",
    isComplete: false,
    isHighlighted: true,
    metaVariantText: "Project",
    readinessState: "incomplete",
    readinessStatusText: "Needs specs",
  });
  expect(model.rows[2].primaryAction).toEqual({
    className: "btn btn--primary car-complete-btn",
    labelText: "Finish setup",
    type: "complete",
  });
  expect(model.rows[2].setupMetrics).toEqual([
    { isCode: true, labelText: "Tires", valueText: "Tire size not set" },
    { labelText: "Drive", valueText: "Not set" },
    { labelText: "Top Gear", valueText: "Not set" },
  ]);
});

test("buildSettingsCarListRenderModel surfaces approximate drivetrain guidance for ready cars", () => {
  const model = buildSettingsCarListRenderModel({
    cars: [
      makeCar({
        id: "car-approx",
        name: "Approximate Car",
        aspects: {
          tire_width_mm: 225,
          tire_aspect_pct: 45,
          rim_in: 18,
          final_drive_ratio: 3.08,
          current_gear_ratio: 0.64,
        },
        order_reference_status: {
          selection_source_status: "compat_projection",
          final_drive_ratio_confidence: "family_default",
          current_gear_ratio_confidence: "family_default",
          transmission_name: "8-speed automatic",
          transmission_confidence: "family_default",
          requires_manual_confirmation: true,
        },
      }),
    ],
    activeCarId: null,
    t,
    fmt,
  });

  expect(model.kind).toBe("rows");
  if (model.kind !== "rows") {
    throw new Error("Expected car rows");
  }
  expect(model.rows[0]).toMatchObject({
    completionDetailText: "Approximate drivetrain ratios need review.",
    isComplete: true,
    readinessState: "ready",
  });
});

test("buildSettingsCarListRenderModel produces the actionable empty state when no cars exist", () => {
  const model = buildSettingsCarListRenderModel({
    cars: [],
    activeCarId: null,
    t,
    fmt,
  });

  expect(model).toEqual({
    kind: "empty",
    emptyState: {
      action: {
        labelText: "Add a car",
        type: "add",
        variant: "success",
      },
      bodyText: "Cars define the setup used for recording, saved runs, and analysis settings.",
      detailText: "Start with the add-car wizard so the next recording has the right context.",
      titleText: "Add the first car profile.",
    },
  });
});

test("createSettingsCarListRenderModelMemo preserves unchanged row references", () => {
  const buildMemoizedModel = createSettingsCarListRenderModelMemo();
  const readyCar = makeCar({
    id: "car-ready",
    name: "Ready Car",
    aspects: {
      tire_width_mm: 245,
      tire_aspect_pct: 40,
      rim_in: 18,
      final_drive_ratio: 3.91,
      current_gear_ratio: 0.82,
    },
  });
  const incompleteCar = makeCar({
    id: "car-new",
    name: "Needs Work",
    variant: "Project",
    aspects: {
      tire_width_mm: 245,
    },
  });

  const firstModel = buildMemoizedModel({
    cars: [readyCar, incompleteCar],
    activeCarId: "car-ready",
    highlightedCarId: null,
    t,
    fmt,
  });

  expect(firstModel.kind).toBe("rows");
  if (firstModel.kind !== "rows") {
    throw new Error("Expected car rows");
  }

  const secondModel = buildMemoizedModel({
    cars: [
      makeCar({
        ...readyCar,
        aspects: { ...readyCar.aspects },
      }),
      makeCar({
        ...incompleteCar,
        aspects: { ...incompleteCar.aspects },
      }),
    ],
    activeCarId: "car-ready",
    highlightedCarId: "car-new",
    t,
    fmt,
  });

  expect(secondModel.kind).toBe("rows");
  if (secondModel.kind !== "rows") {
    throw new Error("Expected car rows");
  }

  expect(secondModel.rows[0]).toBe(firstModel.rows[0]);
  expect(secondModel.rows[1]).not.toBe(firstModel.rows[1]);
});

test("buildCarsGuidanceRenderModel returns success, guidance, or hidden states based on selection", () => {
  expect(
    buildCarsGuidanceRenderModel({
      carSelectionState: {
        kind: "active",
        car: makeCar({ id: "car-1", name: "Track Demo" }),
      },
      highlightedCarFeedback: {
        carId: "car-1",
        carName: "Track Demo",
      },
      t,
    }),
  ).toEqual({
    bodyText: "Track Demo was added and selected for this setup.",
    detailText: "Review the highlighted row below or open Analysis to confirm the setup before the next run.",
    titleText: "Car added",
    tone: "success",
  });

  expect(
    buildCarsGuidanceRenderModel({
      carSelectionState: { kind: "no_active_car" },
      highlightedCarFeedback: null,
      t,
    }),
  ).toEqual({
    bodyText: "Activate a car from the list below or add a new one to unlock analysis settings.",
    detailText: "Use Activate on a ready row, or Finish setup on an incomplete row, to unlock the rest of Settings.",
    titleText: "Activate one car for this setup.",
    tone: "default",
  });

  expect(
    buildCarsGuidanceRenderModel({
      carSelectionState: { kind: "loading" },
      highlightedCarFeedback: {
        carId: "car-1",
        carName: "Track Demo",
      },
      t,
    }),
  ).toBeNull();
});

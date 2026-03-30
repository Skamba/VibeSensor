import { expect, test } from "@playwright/test";

import { getCarCompleteness } from "../src/app/car_selection_state";
import { renderSettingsCarList } from "../src/app/views/settings_car_list_view";
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
};

function t(key: string): string {
  return labels[key] ?? key;
}

function escapeHtml(value: unknown): string {
  return String(value ?? "");
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

test("renderSettingsCarList shows explicit readiness labels and completion actions", () => {
  const container = { innerHTML: "" } as HTMLElement;

  renderSettingsCarList(container, {
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
    escapeHtml,
    fmt,
  });

  expect(container.innerHTML).toContain('data-car-id="car-ready"');
  expect(container.innerHTML).toContain('data-car-complete="true"');
  expect(container.innerHTML).toContain("Active");
  expect(container.innerHTML).toContain("Ready");
  expect(container.innerHTML).toContain('data-car-id="car-ready-inactive"');
  expect(container.innerHTML).toContain('data-car-action="activate"');
  expect(container.innerHTML).toContain('data-car-id="car-new"');
  expect(container.innerHTML).toContain('data-car-complete="false"');
  expect(container.innerHTML).toContain("Inactive");
  expect(container.innerHTML).toContain("Needs specs");
  expect(container.innerHTML).toContain("Finish setup");
  expect(container.innerHTML).toContain("Tire size not set");
  expect(container.innerHTML).toContain("Not set");
  expect(container.innerHTML).toContain("Open Analysis to finish the missing tire and drivetrain specs before using this car.");
  expect(container.innerHTML).toContain("car-list-row--highlighted");
  expect(container.innerHTML).toContain("New");
  expect(container.innerHTML).toContain("btn--danger-quiet");
  expect(container.innerHTML).not.toContain("?");
});

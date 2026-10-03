import { describe, expect, test } from "vitest";

import type { CarRecord } from "../src/api/types";
import { deriveCarSelection } from "../src/car_selection";

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

describe("car selection", () => {
  test("distinguishes loading, empty, missing-active, and active", () => {
    expect(deriveCarSelection([], null, false)).toEqual({ kind: "loading" });
    expect(deriveCarSelection([], null, true)).toEqual({ kind: "no_cars" });
    expect(deriveCarSelection([makeCar()], null, true)).toEqual({
      kind: "no_active_car",
    });
    expect(deriveCarSelection([makeCar()], "car-1", true)).toEqual({
      kind: "active",
      car: makeCar(),
    });
    expect(deriveCarSelection([makeCar()], "missing", true)).toEqual({
      kind: "no_active_car",
    });
  });
});

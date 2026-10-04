import { expect, test } from "vitest";

import {
  locationCodeForClient,
  locationLabel,
  locationOptions,
} from "../src/sensor_locations";
import { layoutConsequence, sensorLayout } from "../src/sensor_layout";
import type { AdaptedClient } from "../src/transport/live_models";

const codes = ["front_left_wheel", "rear_right_wheel", "driver_seat", "trunk"];
const t = (key: string) => ({ "location.trunk": "Trunk" })[key] ?? key;
const options = locationOptions(codes, t);
const labels = (code: string) =>
  code === "driver_seat" ? ["Driver Seat", "Bestuurdersstoel"] : [];

function locate(fields: Partial<AdaptedClient>): string {
  return locationCodeForClient(
    { id: "x", ...fields } as AdaptedClient,
    codes,
    options,
    labels,
  );
}

test("an assigned known location wins", () => {
  expect(
    locate({ location_code: " rear_right_wheel ", name: "front left" }),
  ).toBe("rear_right_wheel");
});

test("an unknown assigned code falls back to the name", () => {
  expect(locate({ location_code: "roof", name: "Front-Left hub" })).toBe(
    "front_left_wheel",
  );
});

test("names match shorthand, any language's label, or the option label", () => {
  expect(locate({ name: "driver" })).toBe("driver_seat");
  expect(locate({ name: "Bestuurdersstoel" })).toBe("driver_seat");
  expect(locate({ name: "Trunk" })).toBe("trunk");
  expect(locate({ name: "Mystery" })).toBe("");
  expect(locate({})).toBe("");
});

test("the sensor layout says what it can localise", () => {
  const t = (key: string, vars?: Record<string, unknown>) =>
    vars ? `${key}:${JSON.stringify(vars)}` : key;
  const kind = (codes: string[]) => sensorLayout(codes)?.kind ?? null;
  expect(kind([])).toBeNull();
  expect(kind(["", ""])).toBeNull();
  expect(kind(["front_left_wheel"])).toBe("single");
  expect(kind(["driver_seat", "trunk"])).toBe("no_wheels");
  expect(kind(["front_left_wheel", "front_left_wheel", "trunk"])).toBe(
    "some_wheels",
  );
  const four = sensorLayout([
    "front_left_wheel",
    "front_right_wheel",
    "rear_left_wheel",
    "rear_right_wheel",
    "",
  ]);
  expect(four).toEqual({ kind: "four_wheels", wheelCount: 4 });
  const some = sensorLayout(["front_left_wheel", "rear_right_wheel"]);
  expect(some && layoutConsequence(some, t)).toBe(
    'sensors.layout.some_wheels:{"count":2,"total":4}',
  );
});

test("a stored location (code or English label) shows in the UI language", () => {
  expect(locationLabel("trunk", t)).toBe("Trunk");
  expect(locationLabel("Front Right Wheel", t)).toBe(
    "location.front_right_wheel",
  );
  expect(locationLabel("engine-bay", t)).toBe("location.engine_bay");
  expect(locationLabel("Roof rack", t)).toBe("Roof rack");
});

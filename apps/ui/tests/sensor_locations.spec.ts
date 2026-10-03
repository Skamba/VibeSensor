import { expect, test } from "vitest";

import {
  locationCodeForClient,
  locationOptions,
} from "../src/sensor_locations";
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

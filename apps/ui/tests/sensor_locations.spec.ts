import { expect, test } from "vitest";

import {
  assignedLocation,
  locationLabel,
  sensorLabel,
} from "../src/sensor_locations";
import { layoutConsequence, sensorLayout } from "../src/sensor_layout";
import type { AdaptedClient } from "../src/transport/live_models";

const codes = ["front_left_wheel", "rear_right_wheel", "driver_seat", "trunk"];
const t = (key: string, vars?: Record<string, unknown>) =>
  ({ "location.trunk": "Trunk" })[key] ??
  (vars ? `${key}:${JSON.stringify(vars)}` : key);
const client = (fields: Partial<AdaptedClient>) =>
  ({ id: "025a00000001", ...fields }) as AdaptedClient;

test("only an assigned, known location places a sensor; a name never does", () => {
  expect(
    assignedLocation(
      client({ location_code: " rear_right_wheel ", name: "front left" }),
      codes,
    ),
  ).toBe("rear_right_wheel");
  expect(assignedLocation(client({ location_code: "roof" }), codes)).toBe("");
  for (const name of ["front-left", "Front Left Wheel", "driver", "Trunk"]) {
    expect(assignedLocation(client({ name }), codes)).toBe("");
  }
});

test("Live names a placed sensor by location, an unplaced one by its own name", () => {
  expect(sensorLabel(client({ name: "front-left" }), "trunk", t)).toBe("Trunk");
  expect(sensorLabel(client({ name: " front-left " }), "", t)).toBe(
    'sensors.unplaced_name:{"name":"front-left"}',
  );
  expect(sensorLabel(client({ name: "" }), "", t)).toBe(
    'sensors.unplaced_name:{"name":"025a00000001"}',
  );
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
  expect(some && layoutConsequence(some, null, t)).toBe(
    'sensors.layout.some_wheels:{"count":2,"total":4}',
  );
  // One sensor tells the source type; an EV's are the wheels and its motor.
  const single = sensorLayout(["trunk"]);
  expect(single && layoutConsequence(single, "ICE", t)).toMatch(
    /^sensors\.layout\.single:/,
  );
  expect(single && layoutConsequence(single, "EV", t)).toMatch(
    /^sensors\.layout\.single_ev:/,
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

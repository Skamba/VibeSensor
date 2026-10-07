import { expect, test } from "vitest";

import { defaultLocationCodes } from "../src/constants";
import {
  placementModel,
  placesOnTap,
  SPOTS,
  sensorTitle,
  shortSensorId,
  spotLabel,
} from "../src/pages/sensors/placement_model";
import type { AdaptedClient } from "../src/transport/live_models";

function sensor(
  id: string,
  fields: Partial<AdaptedClient> = {},
): AdaptedClient {
  return {
    id,
    name: id,
    connected: true,
    mac_address: id.replace(/(..)(?!$)/g, "$1:"),
    location_code: "",
    last_seen_age_ms: 10,
    dropped_frames: 0,
    frame_loss_recent: false,
    frames_total: 100,
    frame_samples: 200,
    sample_rate_hz: 800,
    firmware_version: "fw-1",
    firmware_status: "current",
    ...fields,
  };
}

const codeOf = (client: AdaptedClient) => client.location_code ?? "";

test("the diagram has one spot per server location and no two share a cell", () => {
  expect(SPOTS.map((spot) => spot.code).sort()).toEqual(
    [...defaultLocationCodes].sort(),
  );
  const cells = new Set<string>();
  for (const spot of SPOTS) {
    for (let col = spot.col; col < spot.col + spot.span; col += 1) {
      const cell = `${spot.row}:${col}`;
      expect(cells.has(cell), cell).toBe(false);
      cells.add(cell);
    }
    // Wheels sit in the outer columns, everything else inside the body.
    expect(spot.wheel).toBe(spot.col === 1 || spot.col === 5);
  }
});

test("narrow spots get a short label, the rest the location's own label", () => {
  const t = (key: string) => key;
  expect(spotLabel("driver_seat", t)).toBe("settings.sensors.spot.driver_seat");
  expect(spotLabel("front_left_wheel", t)).toBe(
    "settings.sensors.spot.front_left_wheel",
  );
  expect(spotLabel("trunk", t)).toBe("location.trunk");
});

test("unplaced sensors are listed; the next connected one is selected by default", () => {
  const clients = [
    sensor("025a00000001", { location_code: "trunk" }),
    sensor("025a00000002", { connected: false }),
    sensor("025a00000003", { name: "front-left" }),
  ];
  const model = placementModel(clients, codeOf, undefined);
  expect(model.unplaced.map((entry) => entry.id)).toEqual([
    "025a00000002",
    "025a00000003",
  ]);
  expect(model.byCode.get("trunk")?.id).toBe("025a00000001");
  expect(model.selected?.id).toBe("025a00000003");
  // Offline sensors are still selected once nothing else is left to place.
  expect(
    placementModel(clients.slice(0, 2), codeOf, undefined).selected?.id,
  ).toBe("025a00000002");
});

test("a picked sensor stays selected, null clears, a gone one falls back", () => {
  const clients = [
    sensor("025a00000001", { location_code: "trunk" }),
    sensor("025a00000002"),
  ];
  expect(placementModel(clients, codeOf, "025a00000001").selected?.code).toBe(
    "trunk",
  );
  expect(placementModel(clients, codeOf, null).selected).toBeNull();
  expect(placementModel(clients, codeOf, "025a000000ff").selected?.id).toBe(
    "025a00000002",
  );
  // Everything placed: nothing to select by default.
  expect(placementModel(clients.slice(0, 1), codeOf, undefined).selected).toBe(
    null,
  );
});

test("a second sensor claiming a taken location stays visible as unplaced", () => {
  const clients = [
    sensor("025a00000001", { location_code: "trunk" }),
    sensor("025a00000002", { location_code: "trunk" }),
  ];
  const model = placementModel(clients, codeOf, undefined);
  expect(model.byCode.get("trunk")?.id).toBe("025a00000001");
  expect(model.unplaced.map((entry) => entry.id)).toEqual(["025a00000002"]);
});

test("a sensor is told apart by its MAC's last two bytes", () => {
  expect(shortSensorId("02:00:00:00:d8:01")).toBe("d8:01");
  expect(shortSensorId("020000000A0B")).toBe("0a:0b");
  expect(shortSensorId("x")).toBe("x");
  const [named, plain] = placementModel(
    [sensor("020000000001", { name: "front-left" }), sensor("020000000002")],
    codeOf,
    undefined,
  ).sensors;
  expect(sensorTitle(named)).toBe("front-left · 00:01");
  expect(sensorTitle(plain)).toBe("020000000002");
});

test("a tap places the selected sensor, but a default pick never displaces one", () => {
  const clients = [
    sensor("025a00000001", { location_code: "trunk" }),
    sensor("025a00000002"),
  ];
  const auto = placementModel(clients, codeOf, undefined);
  const trunk = auto.byCode.get("trunk");
  // The next sensor to place goes to a free spot; a placed one gets selected.
  expect(placesOnTap(auto, undefined)).toBe(true);
  expect(placesOnTap(auto, trunk)).toBe(false);
  // A sensor the owner picked takes the spot over.
  const picked = placementModel(clients, codeOf, "025a00000002");
  expect(placesOnTap(picked, trunk)).toBe(true);
  // Its own spot, or nothing selected, never places.
  const own = placementModel(clients, codeOf, "025a00000001");
  expect(placesOnTap(own, own.byCode.get("trunk"))).toBe(false);
  expect(placesOnTap(placementModel(clients, codeOf, null), undefined)).toBe(
    false,
  );
});

import { expect, test } from "@playwright/test";

import { buildRealtimeSensorTableRenderModel } from "../src/app/views/realtime_sensor_table_view";
import type { AdaptedClient } from "../src/transport/live_models";

const labels: Record<string, string> = {
  "actions.identify": "Identify",
  "actions.remove": "Remove",
  "settings.select_location": "Select location",
  "settings.sensors.no_sensors": "No sensors detected yet.",
  "status.offline": "Offline",
  "status.online": "Online",
};

function t(key: string): string {
  return labels[key] ?? key;
}

function makeClient(overrides: Partial<AdaptedClient> = {}): AdaptedClient {
  return {
    connected: true,
    dropped_frames: 0,
    firmware_version: "fw-1.0.0",
    frame_samples: 128,
    frames_total: 100,
    id: "sensor-1",
    last_seen_age_ms: 10,
    location_code: "",
    mac_address: "001122334455",
    name: "Chassis Sensor A",
    sample_rate_hz: 1000,
    ...overrides,
  };
}

test("buildRealtimeSensorTableRenderModel compacts sensor identity and actions into one row layout", () => {
  const model = buildRealtimeSensorTableRenderModel({
    clients: [makeClient()],
    locationOptions: [{ code: "front_left_wheel", label: "Front Left Wheel" }],
    t,
  });

  expect(model.kind).toBe("rows");
  if (model.kind !== "rows") {
    throw new Error("Expected sensor rows");
  }
  expect(model.rows).toHaveLength(1);
  expect(model.rows[0]).toMatchObject({
    clientId: "sensor-1",
    displayName: "Chassis Sensor A",
    statusText: "Online",
    statusClass: "online",
    macAddress: "001122334455",
    selectedLocationCode: "",
    locationSelectLabel: "Select location",
    identifyLabel: "Identify",
    identifyDisabled: false,
    removeLabel: "Remove",
  });
  expect(model.rows[0].locationOptions).toEqual([
    { code: "front_left_wheel", label: "Front Left Wheel" },
  ]);
});

test("buildRealtimeSensorTableRenderModel uses the compact three-column empty state", () => {
  const model = buildRealtimeSensorTableRenderModel({
    clients: [],
    locationOptions: [],
    t,
  });

  expect(model).toEqual({
    kind: "empty",
    emptyText: "No sensors detected yet.",
  });
});

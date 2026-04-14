import { expect, test } from "@playwright/test";

import { renderRealtimeSensorTable } from "../src/app/views/realtime_sensor_table_view";
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

function escapeHtml(value: unknown): string {
  return String(value ?? "");
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

test("renderRealtimeSensorTable compacts sensor identity and actions into one row layout", () => {
  const container = { innerHTML: "" } as HTMLElement;

  renderRealtimeSensorTable(container, {
    clients: [makeClient()],
    escapeHtml,
    locationOptions: [{ code: "front_left_wheel", label: "Front Left Wheel" }],
    t,
  });

  expect(container.innerHTML).toContain('data-client-id="sensor-1"');
  expect(container.innerHTML).toContain("settings-sensor-row__identity");
  expect(container.innerHTML).toContain("status-pill settings-entity-status online");
  expect(container.innerHTML).toContain("<code>001122334455</code>");
  expect(container.innerHTML).toContain("settings-sensor-row__actions");
  expect(container.innerHTML).toContain('class="btn row-identify"');
  expect(container.innerHTML).toContain('class="btn btn--danger-quiet row-remove"');
});

test("renderRealtimeSensorTable uses the compact three-column empty row", () => {
  const container = { innerHTML: "" } as HTMLElement;

  renderRealtimeSensorTable(container, {
    clients: [],
    escapeHtml,
    locationOptions: [],
    t,
  });

  expect(container.innerHTML).toContain('colspan="3"');
  expect(container.innerHTML).toContain("No sensors detected yet.");
});

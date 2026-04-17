import { expect, test } from "@playwright/test";

import { EXPECTED_SCHEMA_VERSION } from "../src/contracts/ws_payload_types";
import { fulfillJson, installCommonRoutes, requestPath } from "./smoke.helpers";

const strengthMetrics = {
  vibration_strength_db: 12,
  peak_amp_g: 0.2,
  noise_floor_amp_g: 0.01,
  strength_bucket: null,
  top_peaks: [],
};

test("shell chrome connection-state attribute follows live websocket state declaratively", async ({ page }) => {
  await installCommonRoutes(page, {
    locations: [{ code: "front_left_wheel", label: "Front Left Wheel" }],
    settingsHandler: async (route) => {
      if (requestPath(route) === "/api/settings/cars") {
        await fulfillJson(route, {
          cars: [
            {
              id: "car-1",
              name: "Test Hatch",
              type: "Simulated setup",
              variant: null,
              aspects: {},
            },
          ],
          active_car_id: "car-1",
        });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await page.route("**/api/recording/status", async (route) => {
    await fulfillJson(route, {
      enabled: false,
      run_id: null,
      write_error: null,
      analysis_in_progress: false,
      start_time_utc: null,
      samples_written: 0,
      samples_dropped: 0,
      last_completed_run_id: null,
      last_completed_run_error: null,
      capture_readiness: null,
    });
  });
  await page.addInitScript(({ schemaVersion, payload }) => {
    class FakeWebSocket {
      static OPEN = 1;
      readyState = FakeWebSocket.OPEN;
      onopen: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent<string>) => void) | null = null;
      onclose: ((event: CloseEvent) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;

      constructor() {
        (window as Window & { __lastFakeWebSocket?: FakeWebSocket }).__lastFakeWebSocket = this;
        queueMicrotask(() => this.onopen?.(new Event("open")));
        queueMicrotask(() => {
          this.onmessage?.(
            new MessageEvent("message", {
              data: JSON.stringify({
                schema_version: schemaVersion,
                server_time: new Date().toISOString(),
                speed_mps: null,
                clients: [],
                selected_client_id: null,
                rotational_speeds: null,
                ...payload,
              }),
            }),
          );
        });
      }

      send() {}

      close() {
        this.readyState = 3;
        this.onclose?.(new CloseEvent("close"));
      }
    }

    window.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
  }, {
    payload: {
      clients: [
        {
          id: "001122334455",
          name: "Front Left",
          connected: true,
          sample_rate_hz: 1000,
          last_seen_age_ms: 10,
          dropped_frames: 0,
          frames_total: 100,
          location_code: "front_left_wheel",
          mac_address: "001122334455",
          firmware_version: "fw-1.0.0",
        },
      ],
      spectra: {
        clients: {
          "001122334455": {
            freq: [1, 2, 3],
            combined_spectrum_amp_g: [0.1, 0.2, 0.15],
            strength_metrics: strengthMetrics,
          },
        },
      },
    },
    schemaVersion: EXPECTED_SCHEMA_VERSION,
  });

  await page.goto("/");

  const shellFrame = page.locator("#appShellChromeRoot > .wrap");
  await expect(shellFrame).toHaveAttribute("data-connection-state", "live");

  await page.evaluate(() => {
    (window as Window & { __lastFakeWebSocket?: { close(): void } }).__lastFakeWebSocket?.close();
  });

  await expect(shellFrame).toHaveAttribute("data-connection-state", "degraded");
});

import { expect, test, type Page, type Route } from "@playwright/test";

import {
  bootLiveDashboard,
  buildCaptureReadiness,
  fulfillJson,
  installCommonRoutes,
  type LiveClientFixture,
  requestPath,
} from "./smoke.helpers";
import type { CarsPayload, LoggingStatusPayload } from "../src/api/types";
import {
  EXPECTED_SCHEMA_VERSION,
  type WsSpectrumSeries,
} from "../src/contracts/ws_payload_types";

test.describe.configure({ timeout: 20_000 });

const FREQ = Array.from({ length: 64 }, (_, index) => 2 + index);

function spectrumSeries(
  peakHz: number,
  peakAmp: number,
  db: number,
): WsSpectrumSeries {
  return {
    freq: FREQ,
    combined_spectrum_amp_g: FREQ.map((hz) =>
      hz === peakHz ? peakAmp : 0.002 + (hz % 5) * 0.0005,
    ),
    strength_metrics: {
      vibration_strength_db: db,
      peak_amp_g: peakAmp,
      noise_floor_amp_g: 0.002,
      strength_bucket: null,
      top_peaks: [
        {
          hz: peakHz,
          amp: peakAmp,
          vibration_strength_db: db,
          strength_bucket: null,
        },
      ],
    },
  };
}

function client(
  id: string,
  name: string,
  locationCode: string,
): LiveClientFixture {
  return {
    id,
    name,
    connected: true,
    sample_rate_hz: 1000,
    last_seen_age_ms: 10,
    dropped_frames: 0,
    frames_total: 100,
    location_code: locationCode,
    mac_address: id,
    firmware_version: "fw-1.0.0",
    firmware_status: "unknown",
  };
}

// An active car and ready capture readiness: the order bands can draw.
async function installReadyDashboardRoutes(page: Page): Promise<void> {
  await installCommonRoutes(page, {
    settingsHandler: async (route: Route) => {
      if (requestPath(route).startsWith("/api/settings/cars")) {
        await fulfillJson<CarsPayload>(route, {
          cars: [
            { id: "car-1", name: "Test Hatch", type: "sedan", aspects: {} },
          ],
          active_car_id: "car-1",
        });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await page.route("**/api/recording/status", async (route) => {
    await fulfillJson<LoggingStatusPayload>(route, {
      enabled: false,
      run_id: null,
      write_error: null,
      analysis_in_progress: false,
      start_time_utc: null,
      samples_written: 0,
      samples_dropped: 0,
      last_completed_run_id: null,
      last_completed_run_error: null,
      capture_readiness: buildCaptureReadiness({
        isReady: true,
        sensors: { state: "pass", reasonKey: "sensors_ready" },
        reference: { state: "pass", reasonKey: "reference_ready" },
        speed: { state: "pass", reasonKey: "speed_stable" },
      }),
    });
  });
}

/** Counts canvas pixels that differ from the top-left background pixel. */
async function paintedPixelCount(page: Page): Promise<number> {
  return await page.locator("#specChart canvas").evaluate((element) => {
    const canvas = element as HTMLCanvasElement;
    const ctx = canvas.getContext("2d");
    if (!ctx || canvas.width === 0 || canvas.height === 0) {
      return 0;
    }
    const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height);
    let painted = 0;
    for (let index = 0; index < data.length; index += 4) {
      if (
        data[index] !== data[0] ||
        data[index + 1] !== data[1] ||
        data[index + 2] !== data[2] ||
        data[index + 3] !== data[3]
      ) {
        painted += 1;
      }
    }
    return painted;
  });
}

test("journey: live spectrum renders sensor traces, legend focus, and order bands", async ({
  page,
}) => {
  await installReadyDashboardRoutes(page);
  await bootLiveDashboard(page, {
    installRoutes: false,
    fakeWebSocket: {
      payload: {
        speed_mps: 25,
        clients: [
          client("001122334455", "Front Left", "front_left_wheel"),
          client("001122334466", "Rear Right", "rear_right_wheel"),
        ],
        spectra: {
          clients: {
            "001122334455": spectrumSeries(12, 0.08, 31),
            "001122334466": spectrumSeries(30, 0.03, 22),
          },
        },
        rotational_speeds: {
          basis_speed_source: "gps",
          wheel: { rpm: 700, mode: "calculated", reason: null },
          driveshaft: { rpm: null, mode: null, reason: "missing_final_drive" },
          engine: { rpm: null, mode: null, reason: "missing_final_drive" },
          order_bands: [{ key: "wheel_1x", center_hz: 11.7, tolerance: 0.08 }],
        },
      },
    },
  });

  await expect(page.locator("#spectrumOverlay")).toBeHidden();
  await expect(page.locator("#specChart canvas")).toBeVisible();
  await expect.poll(() => paintedPixelCount(page)).toBeGreaterThan(500);

  const legend = page.locator("#legend");
  await expect(legend.locator(".legend-item--interactive")).toHaveCount(3);
  const frontLeft = legend.getByRole("button", { name: /Front Left/ });
  await expect(frontLeft).toContainText("31");
  await frontLeft.click();
  await expect(frontLeft).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#spectrumInspector")).toContainText("Front Left");
  await legend.locator(".legend-item--reset").click();
  await expect(frontLeft).toHaveAttribute("aria-pressed", "false");

  // The band status names what each family needs.
  const bandStatus = page.locator("#bandStatus");
  await expect(
    bandStatus.locator('[data-band-family="wheel"]'),
  ).toHaveAttribute("data-band-family-state", "on");
  await expect(
    bandStatus.locator('[data-band-family="driveline"]'),
  ).toContainText("needs final drive");
  await expect(bandStatus.locator(".band-status__message")).toHaveCount(0);

  const bandToggle = page.locator("#spectrumBandToggle");
  await expect(bandToggle).toBeVisible();
  await expect(page.locator("#bandLegend")).toBeHidden();
  await bandToggle.click();
  await expect(bandToggle).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#bandLegend")).toContainText("Wheel 1x");

  // Hovering the plot inspects the nearest frequency bin.
  const box = await page.locator("#specChart canvas").boundingBox();
  if (box === null) {
    throw new Error("spectrum canvas has no layout box");
  }
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await expect(page.locator("#spectrumInspector")).toContainText("Hz");
});

test("journey: without a car the spectrum still draws and says why there are no bands", async ({
  page,
}) => {
  await bootLiveDashboard(page, {
    fakeWebSocket: {
      payload: {
        speed_mps: 0,
        clients: [client("001122334455", "Front Left", "front_left_wheel")],
        spectra: {
          clients: { "001122334455": spectrumSeries(12, 0.08, 31) },
        },
      },
    },
  });
  await expect(page.locator(".realtime-logging-shell")).toHaveAttribute(
    "data-layout",
    "setup",
  );
  await expect(page.locator("#specChart canvas")).toBeVisible();
  await expect.poll(() => paintedPixelCount(page)).toBeGreaterThan(500);
  await expect(page.locator("#bandStatus")).toContainText(
    "Order bands need an active car",
  );
});

test("journey: spectrum explains when connected sensors have no frames yet", async ({
  page,
}) => {
  await installReadyDashboardRoutes(page);
  await bootLiveDashboard(page, {
    installRoutes: false,
    fakeWebSocket: {
      payload: {
        clients: [client("001122334455", "Front Left", "front_left_wheel")],
        spectra: { clients: {} },
      },
    },
  });
  await expect(page.locator("#spectrumOverlay")).toHaveText(
    "Connected, but no spectrum frames yet.",
  );
});

test("journey: demo mode animates sensors and the spectrum without a server", async ({
  page,
}) => {
  const apiRequests: string[] = [];
  await installCommonRoutes(page);
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/")) {
      apiRequests.push(url.pathname);
    }
  });
  await page.goto("/?demo");
  await expect(page.locator("#liveConnectedSensors [data-value]")).toHaveText(
    "5 / 5",
  );
  await expect(page.locator("#spectrumOverlay")).toBeHidden();
  await expect(
    page.locator("#legend").getByRole("button", { name: /Front Left Wheel/ }),
  ).toBeVisible();
  await expect.poll(() => paintedPixelCount(page)).toBeGreaterThan(500);
  // Demo mode never polls recording status.
  expect(apiRequests).not.toContain("/api/recording/status");
});

test("journey: a bad live payload is reported, a good one recovers, and the selected sensor is sent", async ({
  page,
}) => {
  await installReadyDashboardRoutes(page);
  await page.route("**/api/clients/**", (route) => fulfillJson(route, {}));
  await page.addInitScript(() => {
    const live = window as unknown as {
      emitLive(payload: unknown): void;
      sentLive: unknown[];
    };
    live.sentLive = [];
    class ControlledWebSocket {
      static OPEN = 1;
      readyState = 1;
      onopen: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent<string>) => void) | null = null;
      onclose: ((event: CloseEvent) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      constructor() {
        queueMicrotask(() => this.onopen?.(new Event("open")));
        live.emitLive = (payload) =>
          this.onmessage?.(
            new MessageEvent("message", { data: JSON.stringify(payload) }),
          );
      }
      send(data: string) {
        live.sentLive.push(JSON.parse(data));
      }
      close() {
        this.readyState = 3;
      }
    }
    window.WebSocket = ControlledWebSocket as unknown as typeof WebSocket;
  });
  await page.goto("/");
  const emit = (payload: unknown) =>
    page.evaluate(
      (body) =>
        (window as unknown as { emitLive(p: unknown): void }).emitLive(body),
      payload,
    );
  const sent = () =>
    page.evaluate(
      () => (window as unknown as { sentLive: unknown[] }).sentLive,
    );
  const valid = (clients: unknown[]) => ({
    schema_version: EXPECTED_SCHEMA_VERSION,
    server_time: new Date().toISOString(),
    speed_mps: null,
    selected_client_id: null,
    rotational_speeds: null,
    clients,
    spectra: { clients: {} },
  });
  const sensorA = {
    ...client("aa0000000001", "Front Left", "front_left_wheel"),
    frame_samples: 200,
    frame_loss_recent: false,
  };
  const sensorB = {
    ...client("bb0000000002", "Rear Right", "rear_right_wheel"),
    frame_samples: 200,
    frame_loss_recent: false,
  };

  await emit({ ...valid([sensorA]), clients: "not a list" });
  await expect(page.locator("#spectrumOverlay")).toContainText(
    "Invalid websocket payload",
  );
  await expect(page.locator(".wrap")).toHaveAttribute(
    "data-connection-state",
    "degraded",
  );

  await emit(valid([sensorA, sensorB]));
  await expect(page.locator("#spectrumOverlay")).toHaveText(
    "Connected, but no spectrum frames yet.",
  );
  await expect(page.locator(".wrap")).toHaveAttribute(
    "data-connection-state",
    "live",
  );
  // On connect the (still empty) selection is sent, then the first live sensor.
  await expect
    .poll(sent)
    .toEqual([{ client_id: null }, { client_id: sensorA.id }]);

  // Removing the selected sensor moves the selection, and the server hears about it.
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="sensorsTab"]').click();
  await page.locator(`tr[data-client-id="${sensorA.id}"] .row-remove`).click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: "Confirm" })
    .click();
  await expect
    .poll(sent)
    .toEqual([
      { client_id: null },
      { client_id: sensorA.id },
      { client_id: sensorB.id },
    ]);
});

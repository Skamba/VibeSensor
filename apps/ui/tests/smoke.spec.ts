import { expect, test } from "@playwright/test";

test("ui bootstrap smoke: tabs, ws state, recording, history", async ({ page }) => {
  let startCalls = 0;
  let stopCalls = 0;

  await page.route("**/api/logging/status", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ enabled: false, current_file: null }),
    });
  });
  await page.route("**/api/logging/start", async (route) => {
    startCalls += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ enabled: true, current_file: "run-001.jsonl" }),
    });
  });
  await page.route("**/api/logging/stop", async (route) => {
    stopCalls += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ enabled: false, current_file: null }),
    });
  });
  await page.route("**/api/history", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        runs: [{ run_id: "run-001", start_time_utc: "2026-01-01T00:00:00Z", sample_count: 42 }],
      }),
    });
  });
  await page.route("**/api/client-locations", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        locations: [{ code: "front_left_wheel", label: "Front Left Wheel" }],
      }),
    });
  });
  await page.route("**/api/settings/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
  });
  await page.route("**/api/car-library/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ brands: [], types: [], models: [] }),
    });
  });

  await page.addInitScript(() => {
    const payload = {
      server_time: new Date().toISOString(),
      clients: [
        {
          id: "001122334455",
          name: "Front Left",
          connected: true,
          sample_rate_hz: 1000,
          last_seen_age_ms: 10,
          dropped_frames: 0,
          frames_total: 100,
        },
      ],
      diagnostics: { strength_bands: [{ key: "wheel", label: "Wheel", color: "#2f80ed" }], events: [] },
      spectra: {
        clients: {
          "001122334455": {
            freq: [1, 2, 3],
            combined_spectrum_amp_g: [0.1, 0.2, 0.15],
            strength_metrics: { vibration_strength_db: 12 },
          },
        },
      },
    };
    class FakeWebSocket {
      static OPEN = 1;
      readyState = 1;
      onopen: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent<string>) => void) | null = null;
      onclose: ((event: CloseEvent) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      constructor() {
        queueMicrotask(() => this.onopen?.(new Event("open")));
        queueMicrotask(() =>
          this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(payload) })),
        );
      }
      send() {}
      close() {
        this.readyState = 3;
        this.onclose?.(new CloseEvent("close"));
      }
    }
    window.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "VibeSensor" })).toBeVisible();
  await expect(page.locator("#linkState")).not.toHaveText(/Connecting/i);

  await page.locator("#tab-history").click();
  await expect(page.locator("#historyView")).toHaveClass(/active/);
  await expect(page.locator("#historyTableBody")).toContainText("run-001");

  await page.locator("#tab-dashboard").click();
  await page.locator("#startLoggingBtn").click();
  await expect(page.locator("#loggingStatus")).toHaveText("Running");
  await expect.poll(() => startCalls).toBe(1);

  await page.locator("#stopLoggingBtn").click();
  await expect(page.locator("#loggingStatus")).toHaveText("Stopped");
  await expect.poll(() => stopCalls).toBe(1);
});

test("gps status uses selected speed unit in settings panel", async ({ page }) => {
  await page.route("**/api/logging/status", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ enabled: false, current_file: null }),
    });
  });
  await page.route("**/api/history", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ runs: [] }) });
  });
  await page.route("**/api/client-locations", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ locations: [] }),
    });
  });
  await page.route("**/api/car-library/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ brands: [], types: [], models: [] }),
    });
  });
  await page.route("**/api/settings/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/settings/speed-unit") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ speedUnit: "mps" }),
      });
      return;
    }
    if (path === "/api/settings/speed-source/status") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          gps_enabled: true,
          connection_state: "connected",
          device: "gps0",
          last_update_age_s: 0.5,
          raw_speed_kmh: 36,
          effective_speed_kmh: 18,
          last_error: null,
          reconnect_delay_s: 1,
          fallback_active: false,
          stale_timeout_s: 5,
          fallback_mode: "hold",
        }),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
  });

  await page.addInitScript(() => {
    class FakeWebSocket {
      static OPEN = 1;
      readyState = 1;
      onopen: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent<string>) => void) | null = null;
      onclose: ((event: CloseEvent) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      constructor() {
        queueMicrotask(() => this.onopen?.(new Event("open")));
      }
      send() {}
      close() {
        this.readyState = 3;
        this.onclose?.(new CloseEvent("close"));
      }
    }
    window.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
  });

  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="speedSourceTab"]').click();

  await expect(page.locator("#gpsStatusRawSpeed")).toHaveText("10.0 m/s");
  await expect(page.locator("#gpsStatusEffectiveSpeed")).toHaveText("5.0 m/s");
});

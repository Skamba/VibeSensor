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
  await page.route("**/api/history**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (!pathname.startsWith("/api/history") || pathname.includes("/report.pdf")) {
      await route.fallback();
      return;
    }
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
    if (path === "/api/settings/language") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ language: "en" }),
      });
      return;
    }
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
          last_update_age_s: 0.333,
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
  await expect(page.locator("#gpsStatusLastUpdate")).toHaveText("0.3s ago");
});

test("analysis bandwidth and uncertainty settings persist through API round-trip", async ({ page }) => {
  let persistedAnalysisSettings: Record<string, number> = {};
  let analysisPostCalls = 0;

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
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
  });
  await page.route("**/api/analysis-settings", async (route) => {
    const method = route.request().method();
    if (method === "POST") {
      analysisPostCalls += 1;
      persistedAnalysisSettings = route.request().postDataJSON() as Record<string, number>;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(persistedAnalysisSettings),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(persistedAnalysisSettings),
    });
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
  await page.locator('[data-settings-tab="analysisTab"]').click();

  await page.locator("#wheelBandwidthInput").fill("7.5");
  await page.locator("#driveshaftBandwidthInput").fill("8.5");
  await page.locator("#engineBandwidthInput").fill("9.5");
  await page.locator("#speedUncertaintyInput").fill("3");
  await page.locator("#tireDiameterUncertaintyInput").fill("4");
  await page.locator("#finalDriveUncertaintyInput").fill("2");
  await page.locator("#gearUncertaintyInput").fill("5");
  await page.locator("#minAbsBandHzInput").fill("0.7");
  await page.locator("#maxBandHalfWidthInput").fill("12");
  await page.locator("#saveAnalysisBtn").click();

  await expect.poll(() => analysisPostCalls).toBe(1);
  expect(persistedAnalysisSettings).toMatchObject({
    wheel_bandwidth_pct: 7.5,
    driveshaft_bandwidth_pct: 8.5,
    engine_bandwidth_pct: 9.5,
    speed_uncertainty_pct: 3,
    tire_diameter_uncertainty_pct: 4,
    final_drive_uncertainty_pct: 2,
    gear_uncertainty_pct: 5,
    min_abs_band_hz: 0.7,
    max_band_half_width_pct: 12,
  });

  await page.reload();
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="analysisTab"]').click();

  await expect(page.locator("#wheelBandwidthInput")).toHaveValue("7.5");
  await expect(page.locator("#driveshaftBandwidthInput")).toHaveValue("8.5");
  await expect(page.locator("#engineBandwidthInput")).toHaveValue("9.5");
  await expect(page.locator("#speedUncertaintyInput")).toHaveValue("3");
  await expect(page.locator("#tireDiameterUncertaintyInput")).toHaveValue("4");
  await expect(page.locator("#finalDriveUncertaintyInput")).toHaveValue("2");
  await expect(page.locator("#gearUncertaintyInput")).toHaveValue("5");
  await expect(page.locator("#minAbsBandHzInput")).toHaveValue("0.7");
  await expect(page.locator("#maxBandHalfWidthInput")).toHaveValue("12");
});

  test("history PDF download revokes object URL with safe delay", async ({ page }) => {
    let reportPdfCalls = 0;

    await page.route("**/api/logging/status", async (route) => {
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
    await page.route("**/api/history/**/report.pdf**", async (route) => {
      reportPdfCalls += 1;
      await route.fulfill({
        status: 200,
        headers: {
          "content-type": "application/pdf",
          "content-disposition": "attachment; filename=\"run-001_report.pdf\"",
        },
        body: "PDF",
      });
    });
    await page.route("**/api/client-locations", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ locations: [] }) });
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
      const globalState = window as typeof window & {
        __revokeCallCount?: number;
      };
      globalState.__revokeCallCount = 0;

      URL.createObjectURL = (() => "blob:history-download-test") as typeof URL.createObjectURL;
      URL.revokeObjectURL = ((_: string) => {
        globalState.__revokeCallCount = (globalState.__revokeCallCount ?? 0) + 1;
      }) as typeof URL.revokeObjectURL;

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
    await page.locator("#tab-history").click();
    await expect(page.locator("#historyTableBody")).toContainText("run-001");
    await page.locator('[data-run-action="download-pdf"][data-run="run-001"]').click();

    await expect.poll(() => reportPdfCalls).toBe(1);
    await page.waitForTimeout(200);
    await expect(page.evaluate(() => {
      const globalState = window as typeof window & { __revokeCallCount?: number };
      return globalState.__revokeCallCount ?? 0;
    })).resolves.toBe(0);
    await page.waitForTimeout(1000);
    await expect(page.evaluate(() => {
      const globalState = window as typeof window & { __revokeCallCount?: number };
      return globalState.__revokeCallCount ?? 0;
    })).resolves.toBe(1);
  });

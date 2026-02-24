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
    if (new URL(route.request().url()).pathname.startsWith("/api/settings/esp-flash/")) {
      await route.fallback();
      return;
    }
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

test("gps status polling does not override websocket speed readout", async ({ page }) => {
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
        body: JSON.stringify({ speedUnit: "kmh" }),
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
          last_update_age_s: 0.1,
          raw_speed_kmh: 18,
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
    const payload = {
      server_time: new Date().toISOString(),
      speed_mps: 20,
      clients: [],
      diagnostics: { strength_bands: [{ key: "wheel", label: "Wheel", color: "#2f80ed" }], events: [] },
      spectra: { clients: {} },
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
  await expect(page.locator("#speed")).toContainText("72.0 km/h");
  await page.waitForTimeout(500);
  await expect(page.locator("#speed")).toContainText("72.0 km/h");
});

test("rotational assumptions effective speed follows selected unit", async ({ page }) => {
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
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ language: "en" }) });
      return;
    }
    if (path === "/api/settings/speed-unit") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ speedUnit: "mps" }) });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
  });

  await page.addInitScript(() => {
    const payload = {
      server_time: new Date().toISOString(),
      speed_mps: 10,
      clients: [],
      diagnostics: { strength_bands: [{ key: "wheel", label: "Wheel", color: "#2f80ed" }], events: [] },
      rotational_speeds: {
        basis_speed_source: "gps",
        order_bands: [{ key: "wheel_1x", center_hz: 11.2, tolerance: 0.05 }],
      },
      spectra: { clients: {} },
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
  await expect(page.locator("#rotationalAssumptionsBody")).toContainText("10.0 m/s");
});

test("history preview uses dB intensity fields from insights payload", async ({ page }) => {
  await page.route("**/api/logging/status", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ enabled: false, current_file: null }),
    });
  });
  await page.route("**/api/history/**/insights**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        run_id: "run-001",
        start_time_utc: "2026-01-01T00:00:00Z",
        duration_s: 12.3,
        sensor_count_used: 1,
        sensor_intensity_by_location: [
          {
            location: "Front Left Wheel",
            p50_intensity_db: 10,
            p95_intensity_db: 20,
            max_intensity_db: 30,
            dropped_frames_delta: 0,
            queue_overflow_drops_delta: 0,
            sample_count: 15,
          },
        ],
      }),
    });
  });
  await page.route("**/api/history**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (!pathname.startsWith("/api/history") || pathname.includes("/insights")) {
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
      body: JSON.stringify({ locations: [] }),
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
  await page.locator('tr[data-run="run-001"] td').first().click();
  await expect(page.locator(".history-details-row")).toBeVisible();
  await expect(page.locator(".history-preview-table tbody tr td").nth(1)).toHaveText("10.0");
  await expect(page.locator(".history-preview-table tbody tr td").nth(2)).toHaveText("20.0");
  await expect(page.locator(".history-preview-table tbody tr td").nth(3)).toHaveText("30.0");
  await expect(page.locator(".mini-car-dot")).toHaveAttribute("title", /20.0 dB$/);
});

test("strength chart labels update when switching language", async ({ page }) => {
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
    const method = route.request().method();
    if (path === "/api/settings/language" && method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ language: "en" }),
      });
      return;
    }
    if (path === "/api/settings/language" && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ language: "nl" }),
      });
      return;
    }
    if (path === "/api/settings/speed-unit") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ speedUnit: "kmh" }),
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
          last_update_age_s: 0.1,
          raw_speed_kmh: 72,
          effective_speed_kmh: 72,
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
    const payload = {
      server_time: new Date().toISOString(),
      speed_mps: 20,
      clients: [{ id: "c1", name: "Front Left", connected: true, frames_total: 100, dropped_frames: 0 }],
      diagnostics: {
        strength_bands: [{ key: "l1", min_db: 8 }],
        events: [],
        levels: {
          by_source: {
            wheel: { strength_db: 12 },
            driveshaft: { strength_db: 9 },
            engine: { strength_db: 6 },
            other: { strength_db: 3 },
          },
        },
      },
      spectra: { clients: {} },
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
  await expect(page.locator("#strengthChart .u-title")).toHaveText("Strength over time");
  await page.locator("#languageSelect").selectOption("nl");
  await expect(page.locator("#strengthChart .u-title")).toHaveText("Sterkte over tijd");
});

test("manual speed save uses settings endpoint only (no legacy speed-override call)", async ({ page }) => {
  let speedSourcePostCalls = 0;
  let speedOverrideCalls = 0;
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
    const method = route.request().method();
    if (path === "/api/settings/speed-source" && method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ speedSource: "gps", manualSpeedKph: null, staleTimeoutS: 5, fallbackMode: "hold" }),
      });
      return;
    }
    if (path === "/api/settings/speed-source" && method === "POST") {
      speedSourcePostCalls += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(route.request().postDataJSON()),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
  });
  await page.route("**/api/speed-override", async (route) => {
    speedOverrideCalls += 1;
    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "missing" }) });
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
  await page.locator('input[name="speedSourceRadio"][value="manual"]').check();
  await page.locator("#manualSpeedInput").fill("45");
  await page.locator("#saveSpeedSourceBtn").click();

  await expect.poll(() => speedSourcePostCalls).toBe(1);
  await expect.poll(() => speedOverrideCalls).toBe(0);
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

test("settings esp flash tab renders lifecycle state and live logs", async ({ page }) => {
  let statusState: "idle" | "running" | "success" = "idle";
  let logCursor = 0;
  const logs = ["build ok", "erase ok", "upload ok"];

  await page.route("**/api/logging/status", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ enabled: false, current_file: null }) });
  });
  await page.route("**/api/history", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ runs: [] }) });
  });
  await page.route("**/api/client-locations", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ locations: [] }) });
  });
  await page.route("**/api/car-library/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ brands: [], types: [], models: [] }) });
  });
  await page.route("**/api/settings/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/settings/esp-flash/ports") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ports: [{ port: "/dev/ttyUSB0", description: "USB UART", vid: 1, pid: 2, serial_number: "abc" }] }) });
      return;
    }
    if (path === "/api/settings/esp-flash/start") {
      statusState = "running";
      logCursor = 0;
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "started", job_id: 1 }) });
      return;
    }
    if (path === "/api/settings/esp-flash/status") {
      if (statusState === "running" && logCursor >= logs.length) statusState = "success";
      const payload = {
        state: statusState,
        phase: statusState === "running" ? "flashing" : "done",
        job_id: 1,
        selected_port: "/dev/ttyUSB0",
        auto_detect: false,
        started_at: 1,
        finished_at: statusState === "running" ? null : 2,
        last_success_at: statusState === "success" ? 2 : null,
        exit_code: statusState === "success" ? 0 : null,
        error: null,
        log_count: logCursor,
      };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
      return;
    }
    if (path === "/api/settings/esp-flash/logs") {
      const after = Number(url.searchParams.get("after") || "0");
      if (after === 0) logCursor = Math.min(logs.length, logCursor + 2);
      else logCursor = logs.length;
      const lines = logs.slice(after, logCursor);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ from_index: after, next_index: logCursor, lines }) });
      return;
    }
    if (path === "/api/settings/esp-flash/history") {
      const attempts = statusState === "success"
        ? [{ job_id: 1, state: "success", selected_port: "/dev/ttyUSB0", auto_detect: false, started_at: 1, finished_at: 2, exit_code: 0, error: null }]
        : [];
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ attempts }) });
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
  await page.locator('[data-settings-tab="espFlashTab"]').click();
  await expect(page.locator("#espFlashStartBtn")).toBeEnabled();
  await page.locator("#espFlashStartBtn").click();
  statusState = "running";
  logCursor = 2;
  await expect(page.locator("#espFlashStatusBanner")).toContainText("Running");
  await expect(page.locator("#espFlashCancelBtn")).toBeEnabled();
  await expect(page.locator("#espFlashLogPanel")).toContainText("erase ok");
  await expect(page.locator("#espFlashStatusBanner")).toContainText("Success");
  await expect(page.locator("#espFlashCancelBtn")).toBeDisabled();
  await expect(page.locator("#espFlashHistoryPanel")).toContainText("/dev/ttyUSB0");
});

test("settings esp flash status falls back to idle when API omits state", async ({ page }) => {
  await page.route("**/api/logging/status", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ enabled: false, current_file: null }) });
  });
  await page.route("**/api/history", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ runs: [] }) });
  });
  await page.route("**/api/client-locations", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ locations: [] }) });
  });
  await page.route("**/api/car-library/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ brands: [], types: [], models: [] }) });
  });
  await page.route("**/api/settings/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/settings/esp-flash/ports") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ports: [] }) });
      return;
    }
    if (path === "/api/settings/esp-flash/status") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ log_count: 0, error: null }) });
      return;
    }
    if (path === "/api/settings/esp-flash/history") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ attempts: [] }) });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
  });

  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="espFlashTab"]').click();
  await expect(page.locator("#espFlashStatusBanner")).toContainText("Idle");
});

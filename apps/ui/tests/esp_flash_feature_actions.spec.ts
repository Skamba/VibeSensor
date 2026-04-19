import { expect, test } from "@playwright/test";

import {
  createDeferred,
  flushAsyncWork,
  installTimerHarness,
  jsonResponse,
} from "./async_test_helpers";
import {
  createEspFlashFeatureHarness,
  createEspFlashPort,
  expectPollDelays,
  installFeatureFetchMock,
  installMaintenanceFeatureGlobals,
} from "./maintenance_feature_test_support";

let restoreDomGlobals = () => undefined;

test.beforeEach(() => {
  restoreDomGlobals = installMaintenanceFeatureGlobals();
});

test.afterEach(() => {
  restoreDomGlobals();
  restoreDomGlobals = () => undefined;
});

test.describe("createEspFlashFeature actions", () => {
  test("start replaces the previous poll timeout instead of creating a second chain", async () => {
    const timers = installTimerHarness();
    const restoreFetch = installFeatureFetchMock(async (url, method) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({ ports: [createEspFlashPort()] });
      }
      if (url.pathname === "/api/esp-flash/start" && method === "POST") {
        return jsonResponse({ status: "started", job_id: 1 });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse({ state: "idle", log_count: 0, error: null });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      return jsonResponse({});
    });

    try {
      const { deps, feature } = createEspFlashFeatureHarness();

      feature.bindHandlers();
      feature.startPolling();
      await expectPollDelays(timers, [4_000]);

      deps.espFlashStartBtn.click();
      await expectPollDelays(timers, [4_000]);
    } finally {
      restoreFetch();
      timers.restore();
    }
  });

  test("manual port selection is reflected in the flash start payload", async () => {
    let startBody: Record<string, unknown> | null = null;
    const restoreFetch = installFeatureFetchMock(async (url, method, body) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({
          ports: [
            createEspFlashPort(),
            createEspFlashPort({
              description: "ESP32 Bootloader",
              pid: 4,
              port: "/dev/ttyUSB1",
              serial_number: "def",
              vid: 3,
            }),
          ],
        });
      }
      if (url.pathname === "/api/esp-flash/start" && method === "POST") {
        startBody = JSON.parse(body) as Record<string, unknown>;
        return jsonResponse({ status: "started", job_id: 1 });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse({ state: "idle", log_count: 0, error: null });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      return jsonResponse({});
    });

    try {
      const { deps, feature } = createEspFlashFeatureHarness();

      feature.bindHandlers();
      feature.startPolling();
      await flushAsyncWork();

      deps.els.espFlashPortSelect.value = "/dev/ttyUSB1";
      deps.els.espFlashPortSelect.dispatchEvent(new Event("change"));
      deps.espFlashStartBtn.click();
      await flushAsyncWork();

      expect(startBody).toEqual({
        auto_detect: false,
        port: "/dev/ttyUSB1",
      });
    } finally {
      restoreFetch();
    }
  });

  test("cancel replaces the previous poll timeout instead of creating a second chain", async () => {
    const timers = installTimerHarness();
    const restoreFetch = installFeatureFetchMock(async (url, method) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({ ports: [] });
      }
      if (url.pathname === "/api/esp-flash/cancel" && method === "POST") {
        return jsonResponse({ status: "cancelled" });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse({ state: "idle", log_count: 0, error: null });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      return jsonResponse({});
    });

    try {
      const { deps, feature } = createEspFlashFeatureHarness();

      feature.bindHandlers();
      feature.startPolling();
      await expectPollDelays(timers, [4_000]);

      deps.espFlashCancelBtn.click();
      await expectPollDelays(timers, [4_000]);
    } finally {
      restoreFetch();
      timers.restore();
    }
  });

  test("stopPolling prevents an in-flight poll from reviving the loop", async () => {
    const timers = installTimerHarness();
    const deferredStatus = createDeferred<Response>();
    const restoreFetch = installFeatureFetchMock(async (url) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({ ports: [] });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return deferredStatus.promise;
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      return jsonResponse({});
    });

    try {
      const { feature } = createEspFlashFeatureHarness();

      feature.bindHandlers();
      feature.startPolling();
      await flushAsyncWork();
      expect(timers.pendingDelays().filter((delay) => delay !== 10_000)).toEqual(
        [],
      );

      feature.stopPolling();
      deferredStatus.resolve(
        jsonResponse({ state: "idle", log_count: 0, error: null }),
      );
      await flushAsyncWork();

      expect(timers.pendingDelays().filter((delay) => delay !== 10_000)).toEqual(
        [],
      );
    } finally {
      restoreFetch();
      timers.restore();
    }
  });
});

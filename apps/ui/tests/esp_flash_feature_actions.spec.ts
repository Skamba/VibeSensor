import { expect, test } from "@playwright/test";

import {
  createDeferred,
  flushAsyncWork,
  installTimerHarness,
} from "./async_test_helpers";
import {
  createEspFlashFeatureHarness,
  createEspFlashPort,
  expectPollDelays,
  installMaintenanceFeatureGlobals,
} from "./maintenance_feature_test_support";
import {
  buildEspFlashHandlers,
  makeEspFlashHistoryPayload,
  makeEspFlashLogsPayload,
  makeEspFlashPortsPayload,
  makeEspFlashStatusPayload,
} from "./msw/handlers/maintenance";
import { createUiMswTestServer } from "./msw/node";

let restoreDomGlobals = () => undefined;
const mswServer = createUiMswTestServer(test);

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
    mswServer.use(...buildEspFlashHandlers());

    try {
      const { deps, feature } = createEspFlashFeatureHarness();

      feature.bindHandlers();
      feature.startPolling();
      await expectPollDelays(timers, [4_000]);

      deps.espFlashStartBtn.click();
      await expectPollDelays(timers, [4_000]);
      feature.dispose();
    } finally {
      timers.restore();
    }
  });

  test("manual port selection is reflected in the flash start payload", async () => {
    const startRequests: Array<{ auto_detect: boolean; port: string | null }> = [];
    mswServer.use(
      ...buildEspFlashHandlers({
        ports: makeEspFlashPortsPayload({
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
        }),
        startRequests,
      }),
    );

    const { deps, feature } = createEspFlashFeatureHarness();

    feature.bindHandlers();
    feature.startPolling();
    await flushAsyncWork();

    deps.els.espFlashPortSelect.value = "/dev/ttyUSB1";
    deps.els.espFlashPortSelect.dispatchEvent(new Event("change"));
    deps.espFlashStartBtn.click();
    await flushAsyncWork();

    expect(startRequests).toEqual([{
      auto_detect: false,
      port: "/dev/ttyUSB1",
    }]);
    feature.dispose();
  });

  test("cancel replaces the previous poll timeout instead of creating a second chain", async () => {
    const timers = installTimerHarness();
    mswServer.use(
      ...buildEspFlashHandlers({
        history: makeEspFlashHistoryPayload(),
        logs: makeEspFlashLogsPayload(),
        ports: makeEspFlashPortsPayload({ ports: [] }),
        status: makeEspFlashStatusPayload(),
      }),
    );

    try {
      const { deps, feature } = createEspFlashFeatureHarness();

      feature.bindHandlers();
      feature.startPolling();
      await expectPollDelays(timers, [4_000]);

      deps.espFlashCancelBtn.click();
      await expectPollDelays(timers, [4_000]);
      feature.dispose();
    } finally {
      timers.restore();
    }
  });

  test("stopPolling prevents an in-flight poll from reviving the loop", async () => {
    const timers = installTimerHarness();
    const deferredStatus = createDeferred<void>();
    mswServer.use(
      ...buildEspFlashHandlers({
        ports: makeEspFlashPortsPayload({ ports: [] }),
        status: async () => {
          await deferredStatus.promise;
          return makeEspFlashStatusPayload();
        },
      }),
    );

    try {
      const { feature } = createEspFlashFeatureHarness();

      feature.bindHandlers();
      feature.startPolling();
      await flushAsyncWork();
      expect(timers.pendingDelays().filter((delay) => delay !== 10_000)).toEqual(
        [],
      );

      feature.stopPolling();
      deferredStatus.resolve();
      await flushAsyncWork();

      expect(timers.pendingDelays().filter((delay) => delay !== 10_000)).toEqual(
        [],
      );
      feature.dispose();
    } finally {
      timers.restore();
    }
  });
});

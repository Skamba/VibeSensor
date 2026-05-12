import assert from "node:assert/strict";
import { test } from "vitest";

import type { UpdateStartRequestPayload } from "../src/api/types";
import { createDeferred, flushAsyncWork } from "./async_test_helpers";
import {
  createEspFlashFeatureHarness,
  createUpdateFeatureHarness,
  installMaintenanceFeatureGlobals,
} from "./maintenance_feature_test_support";
import {
  createEspFlashPort,
  createHealthyUpdateStatus,
  createIdleUpdateStatus,
  createUsbInternetStatus,
} from "./maintenance_payload_test_support";
import {
  buildEspFlashHandlers,
  buildUpdateHandlers,
  makeEspFlashHistoryPayload,
  makeEspFlashLogsPayload,
  makeEspFlashPortsPayload,
  makeEspFlashStatusPayload,
  makeUpdateStartPayload,
} from "./msw/handlers/maintenance";
import { createUiMswTestScope } from "./msw/node";

function assertContains(
  text: string | null | undefined,
  expected: string,
): void {
  assert.ok(
    (text ?? "").includes(expected),
    `Expected ${JSON.stringify(text ?? "")} to contain ${JSON.stringify(expected)}`,
  );
}

function assertNotContains(
  text: string | null | undefined,
  unexpected: string,
): void {
  assert.ok(
    !(text ?? "").includes(unexpected),
    `Expected ${JSON.stringify(text ?? "")} not to contain ${JSON.stringify(unexpected)}`,
  );
}

function elementText(element: Element): string {
  return element.textContent ?? "";
}

function stageTexts(root: ParentNode): string[] {
  return Array.from(root.querySelectorAll("li"), elementText);
}

function requireStageText(root: ParentNode, title: string): string {
  const stageText = stageTexts(root).find((text) => text.includes(title));
  assert.ok(stageText, `Expected a stage containing ${JSON.stringify(title)}`);
  return stageText;
}

function assertCompletedStageCount(
  root: ParentNode,
  expectedCount: number,
): void {
  assert.equal(
    stageTexts(root).filter((text) => text.includes("Complete")).length,
    expectedCount,
  );
}

async function withMaintenanceScope(
  run: (scope: ReturnType<typeof createUiMswTestScope>) => Promise<void>,
) {
  const restoreDomGlobals = installMaintenanceFeatureGlobals();
  const scope = createUiMswTestScope();

  try {
    await run(scope);
  } finally {
    scope.close();
    restoreDomGlobals();
  }
}

async function runEspFlashStartRefreshesStatusImmediately(): Promise<void> {
  await withMaintenanceScope(async (scope) => {
    let statusRequests = 0;
    scope.server.use(
      ...buildEspFlashHandlers({
        status: () => {
          statusRequests += 1;
          return makeEspFlashStatusPayload();
        },
      }),
    );

    const { deps, feature } = await createEspFlashFeatureHarness();

    try {
      feature.bindHandlers();
      feature.startPolling();
      await flushAsyncWork();
      const initialStatusRequests = statusRequests;

      deps.espFlashStartBtn.click();
      await flushAsyncWork();

      assert.equal(statusRequests, initialStatusRequests + 1);
    } finally {
      feature.dispose();
    }
  });
}

async function runEspFlashManualPortSelection(): Promise<void> {
  await withMaintenanceScope(async (scope) => {
    const startRequests: Array<{ auto_detect: boolean; port: string | null }> =
      [];
    scope.server.use(
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

    const { deps, feature } = await createEspFlashFeatureHarness();

    try {
      feature.bindHandlers();
      feature.startPolling();
      await flushAsyncWork();

      deps.els.espFlashPortSelect.value = "/dev/ttyUSB1";
      deps.els.espFlashPortSelect.dispatchEvent(
        new Event("change", { bubbles: true }),
      );
      deps.espFlashStartBtn.click();
      await flushAsyncWork();

      assert.deepEqual(startRequests, [
        {
          auto_detect: false,
          port: "/dev/ttyUSB1",
        },
      ]);
    } finally {
      feature.dispose();
    }
  });
}

async function runEspFlashCancelRefreshesStatusImmediately(): Promise<void> {
  await withMaintenanceScope(async (scope) => {
    let statusRequests = 0;
    scope.server.use(
      ...buildEspFlashHandlers({
        history: makeEspFlashHistoryPayload(),
        logs: makeEspFlashLogsPayload(),
        ports: makeEspFlashPortsPayload({ ports: [] }),
        status: () => {
          statusRequests += 1;
          return makeEspFlashStatusPayload();
        },
      }),
    );

    const { deps, feature } = await createEspFlashFeatureHarness();

    try {
      feature.bindHandlers();
      feature.startPolling();
      await flushAsyncWork();
      const initialStatusRequests = statusRequests;

      deps.espFlashCancelBtn.click();
      await flushAsyncWork();

      assert.equal(statusRequests, initialStatusRequests + 1);
    } finally {
      feature.dispose();
    }
  });
}

async function runEspFlashLeavingPollingContextStopsFollowupRefreshes(): Promise<void> {
  await withMaintenanceScope(async (scope) => {
    const deferredStatus = createDeferred<void>();
    let statusRequests = 0;
    scope.server.use(
      ...buildEspFlashHandlers({
        ports: makeEspFlashPortsPayload({ ports: [] }),
        status: async () => {
          statusRequests += 1;
          await deferredStatus.promise;
          return makeEspFlashStatusPayload();
        },
      }),
    );

    const { feature } = await createEspFlashFeatureHarness();

    try {
      feature.bindHandlers();
      feature.startPolling();
      await flushAsyncWork();

      feature.stopPolling();
      deferredStatus.resolve();
      await flushAsyncWork();
      await flushAsyncWork();

      assert.equal(statusRequests, 1);
    } finally {
      feature.dispose();
    }
  });
}

async function runEspFlashIdleStateRendersPanels(): Promise<void> {
  await withMaintenanceScope(async (scope) => {
    scope.server.use(...buildEspFlashHandlers());

    const { deps, feature } = await createEspFlashFeatureHarness();

    try {
      feature.bindHandlers();
      feature.startPolling();
      await flushAsyncWork();

      assertContains(elementText(deps.espFlashStartSummary), "Ready to flash");
      assertContains(elementText(deps.espFlashStartSummary), "ESP port ready.");
      assert.equal(deps.espFlashStartBtn.disabled, false);
      assert.equal(deps.espFlashCancelBtn.hidden, true);
      assertContains(elementText(deps.espFlashReadinessPanel), "Ready ports");
      assertContains(
        elementText(deps.espFlashReadinessPanel),
        "1 port available",
      );
      assertContains(elementText(deps.espFlashReadinessPanel), "Auto-detect");
      assertNotContains(
        elementText(deps.espFlashReadinessPanel),
        "Flash progress",
      );
      assertNotContains(elementText(deps.espFlashReadinessPanel), "Validating");
      assertContains(elementText(deps.espFlashJourneyPanel), "Validating");
      assertContains(elementText(deps.els.espFlashLogPanel), "Flash log idle");
      assertContains(
        elementText(deps.els.espFlashHistoryPanel),
        "No flash attempts yet",
      );
    } finally {
      feature.dispose();
    }
  });
}

async function runEspFlashNoPortsBlocksAction(): Promise<void> {
  await withMaintenanceScope(async (scope) => {
    scope.server.use(
      ...buildEspFlashHandlers({
        ports: { ports: [] },
      }),
    );

    const { deps, feature } = await createEspFlashFeatureHarness();

    try {
      feature.bindHandlers();
      feature.startPolling();
      await flushAsyncWork();

      assertContains(elementText(deps.espFlashStartSummary), "Flash blocked");
      assertContains(
        elementText(deps.espFlashStartSummary),
        "No ESP port found.",
      );
      assert.equal(deps.espFlashStartBtn.disabled, true);
      assert.equal(deps.espFlashCancelBtn.hidden, true);
    } finally {
      feature.dispose();
    }
  });
}

async function runEspFlashRunningStateHighlightsStage(): Promise<void> {
  await withMaintenanceScope(async (scope) => {
    scope.server.use(
      ...buildEspFlashHandlers({
        ports: { ports: [createEspFlashPort()] },
        status: {
          state: "running",
          phase: "flashing",
          selected_port: "/dev/ttyUSB0",
          auto_detect: false,
          last_success_at: null,
          error: null,
          log_count: 0,
        },
      }),
    );

    const { deps, feature } = await createEspFlashFeatureHarness();

    try {
      feature.bindHandlers();
      feature.startPolling();
      await flushAsyncWork();

      assertContains(elementText(deps.espFlashStartSummary), "Flash running");
      assert.equal(deps.espFlashStartBtn.hidden, true);
      assert.equal(deps.espFlashCancelBtn.hidden, false);
      assertContains(
        elementText(deps.els.espFlashLogPanel),
        "Flash log running",
      );
      const activeStage = deps.espFlashJourneyPanel.querySelector(
        "li[aria-current='step']",
      );
      assert.ok(activeStage);
      assertContains(elementText(activeStage), "Flashing");
      assertContains(elementText(activeStage), "Active");
      assertContains(elementText(deps.espFlashReadinessPanel), "Current step");
      assertCompletedStageCount(deps.espFlashJourneyPanel, 3);
    } finally {
      feature.dispose();
    }
  });
}

async function runEspFlashFailedRefreshKeepsStoppedStage(): Promise<void> {
  await withMaintenanceScope(async (scope) => {
    let status = makeEspFlashStatusPayload({
      state: "running",
      phase: "flashing",
      selected_port: "/dev/ttyUSB0",
      auto_detect: false,
      error: null,
    });
    scope.server.use(
      ...buildEspFlashHandlers({
        ports: { ports: [createEspFlashPort()] },
        status: () => status,
      }),
    );

    const { deps, feature } = await createEspFlashFeatureHarness();

    try {
      feature.bindHandlers();
      feature.startPolling();
      await flushAsyncWork();

      status = {
        ...status,
        state: "failed",
        phase: "failed",
        error: "serial port disconnected",
      };
      feature.stopPolling();
      feature.startPolling();
      await flushAsyncWork();

      const stoppedStage = requireStageText(
        deps.espFlashJourneyPanel,
        "Flashing",
      );
      assertContains(stoppedStage, "Needs attention");
      assertContains(elementText(deps.espFlashStartSummary), "Flash recovery");
      assertContains(
        elementText(deps.espFlashStartSummary),
        "Reconnect the ESP and retry flashing.",
      );
      assert.equal(deps.espFlashStartBtn.textContent, "Retry flash");
      assertContains(
        elementText(deps.els.espFlashLogPanel),
        "Flash log failed",
      );
      assertContains(
        elementText(deps.els.espFlashHistoryPanel),
        "serial port disconnected",
      );
      assertCompletedStageCount(deps.espFlashJourneyPanel, 3);
      assertContains(
        elementText(deps.espFlashReadinessPanel),
        "serial port disconnected",
      );
    } finally {
      feature.dispose();
    }
  });
}

async function runUpdateStartRefreshesStatusImmediately(): Promise<void> {
  await withMaintenanceScope(async (scope) => {
    const startRequests: UpdateStartRequestPayload[] = [];
    let statusRequests = 0;
    scope.server.use(
      ...buildUpdateHandlers({
        health: createHealthyUpdateStatus(),
        internet: createUsbInternetStatus(),
        start: makeUpdateStartPayload({
          transport: "wifi",
          ssid: "MyWiFi",
        }),
        startRequests,
        status: () => {
          statusRequests += 1;
          return createIdleUpdateStatus();
        },
      }),
    );

    const { deps, feature } = await createUpdateFeatureHarness();

    try {
      feature.bindUpdateHandlers();
      feature.startPolling();
      await flushAsyncWork();
      const initialStatusRequests = statusRequests;
      deps.updatePasswordInput.value = "secret";
      deps.updatePasswordInput.dispatchEvent(
        new Event("input", { bubbles: true }),
      );
      deps.updateSsidInput.value = "MyWiFi";
      deps.updateSsidInput.dispatchEvent(new Event("input", { bubbles: true }));
      await flushAsyncWork();

      deps.updateStartBtn.click();
      await flushAsyncWork();
      assert.equal(statusRequests, initialStatusRequests + 1);
      assert.equal(deps.updatePasswordInput.value, "");
      assert.deepEqual(startRequests, [
        {
          transport: "wifi",
          ssid: "MyWiFi",
          password: "secret",
        },
      ]);
    } finally {
      feature.dispose();
    }
  });
}

async function runUpdateUsbTransportFlow(): Promise<void> {
  await withMaintenanceScope(async (scope) => {
    const startRequests: UpdateStartRequestPayload[] = [];
    scope.server.use(
      ...buildUpdateHandlers({
        health: createHealthyUpdateStatus(),
        internet: createUsbInternetStatus({
          detected: true,
          usable: true,
          interface_name: "usb0",
          connection_name: "iPhone USB",
          driver: "ipheth",
          ipv4_addresses: ["172.20.10.2/28"],
          gateway: "172.20.10.1",
          has_default_route: true,
          diagnostic: "USB internet is ready on 'usb0'.",
        }),
        start: makeUpdateStartPayload({
          transport: "usb_internet",
          ssid: null,
        }),
        startRequests,
        status: createIdleUpdateStatus(),
      }),
    );

    const { deps, feature } = await createUpdateFeatureHarness();

    try {
      deps.updateTransportWifiRadio.checked = false;
      deps.updateTransportUsbRadio.checked = true;

      feature.bindUpdateHandlers();
      feature.startPolling();
      await flushAsyncWork();
      deps.updatePasswordInput.value = "secret";
      deps.updatePasswordInput.dispatchEvent(
        new Event("input", { bubbles: true }),
      );
      await flushAsyncWork();
      deps.updateTransportWifiRadio.checked = false;
      deps.updateTransportUsbRadio.checked = true;
      deps.updateTransportUsbRadio.dispatchEvent(
        new Event("change", { bubbles: true }),
      );
      await flushAsyncWork();

      assert.equal(deps.updateTransportOptions.hidden, false);
      assert.equal(deps.updateWifiFields.hidden, true);
      assert.equal(deps.updateStartBtn.disabled, false);
      assertContains(
        elementText(deps.updateReadinessSummary),
        "USB internet ready on usb0.",
      );
      assert.equal(
        deps.updateDetailsCaption.textContent,
        "USB internet details",
      );
      assert.equal(
        deps.updateTransportNote.textContent,
        "USB internet will be used for update checks.",
      );
      assert.equal(
        deps.updateUsbTransportSummary.textContent,
        "USB interface usb0",
      );
      assert.equal(deps.updateTransportWifiRadio.checked, false);
      assert.equal(deps.updateTransportUsbRadio.checked, true);
      assert.equal(deps.updateTransportUsbRadio.disabled, false);
      assertContains(elementText(deps.internetStatusPanel), "usb0");

      deps.updateStartBtn.click();
      await flushAsyncWork();

      assert.deepEqual(startRequests, [
        {
          transport: "usb_internet",
          password: "",
        },
      ]);
    } finally {
      feature.dispose();
    }
  });
}

async function runUpdateIdleStatusRendersPanels(): Promise<void> {
  await withMaintenanceScope(async (scope) => {
    scope.server.use(...buildUpdateHandlers());

    const { deps, feature } = await createUpdateFeatureHarness();

    try {
      feature.bindUpdateHandlers();
      await flushAsyncWork();
      deps.updateSsidInput.value = "MyWiFi";
      deps.updateSsidInput.dispatchEvent(new Event("input", { bubbles: true }));
      await flushAsyncWork();
      feature.startPolling();
      await flushAsyncWork();

      assertContains(
        elementText(deps.els.updateStatusPanel),
        "Update progress",
      );
      assertContains(elementText(deps.els.updateStatusPanel), "Validating");
      assertNotContains(
        elementText(deps.els.updateStatusPanel),
        "No update issues",
      );
      assertContains(
        elementText(deps.els.updateStatusPanel),
        "No update log yet",
      );
      assertContains(
        elementText(deps.els.updateOverviewPanel),
        "Current update status",
      );
      assertContains(
        elementText(deps.els.updateOverviewPanel),
        "Update service ready",
      );
      assertContains(elementText(deps.els.updateOverviewPanel), "1.2.3");
      assertContains(
        elementText(deps.els.updateOverviewPanel),
        "Update health",
      );
      assertContains(elementText(deps.internetStatusPanel), "USB internet");
      assertContains(
        elementText(deps.internetStatusPanel),
        "No USB internet detected",
      );
      assert.equal(deps.updateTransportOptions.hidden, false);
      assert.equal(deps.updateTransportWifiRadio.checked, true);
      assert.equal(deps.updateTransportUsbRadio.checked, false);
      assert.equal(deps.updateTransportUsbRadio.disabled, true);
      assertContains(
        elementText(deps.updateReadinessSummary),
        "Ready to update",
      );
      assertContains(
        elementText(deps.updateReadinessSummary),
        "Wi-Fi connection ready.",
      );
      assert.equal(deps.updateDetailsCaption.textContent, "Wi-Fi details");
      assert.equal(deps.updateStartBtn.disabled, false);
      assert.equal(
        deps.updateUsbTransportSummary.textContent,
        "USB internet unavailable",
      );
    } finally {
      feature.dispose();
    }
  });
}

async function runUpdateDegradedHealthBlocksStart(): Promise<void> {
  await withMaintenanceScope(async (scope) => {
    const healthy = createHealthyUpdateStatus();
    scope.server.use(
      ...buildUpdateHandlers({
        health: {
          ...healthy,
          status: "degraded",
          degradation_reasons: ["persistence_write_error"],
          subsystems: {
            ...healthy.subsystems,
            recorder: {
              status: "unhealthy",
              reason_codes: ["persistence_write_error"],
            },
          },
          persistence: {
            ...healthy.persistence,
            write_error: "database locked",
          },
        },
      }),
    );

    const { deps, feature } = await createUpdateFeatureHarness();

    try {
      feature.bindUpdateHandlers();
      feature.startPolling();
      await flushAsyncWork();

      assertContains(
        elementText(deps.updateReadinessSummary),
        "Health blocks update start.",
      );
      assertContains(elementText(deps.els.updateOverviewPanel), "Subsystems");
      assertContains(
        elementText(deps.els.updateOverviewPanel),
        "recorder: Unhealthy (persistence_write_error)",
      );
      assert.equal(deps.updateStartBtn.disabled, true);
    } finally {
      feature.dispose();
    }
  });
}

async function runUpdateRunningStateHighlightsStage(): Promise<void> {
  await withMaintenanceScope(async (scope) => {
    scope.server.use(
      ...buildUpdateHandlers({
        status: createIdleUpdateStatus({
          state: "running",
          phase: "installing",
          transport: "wifi",
          ssid: "MyWiFi",
        }),
      }),
    );

    const { deps, feature } = await createUpdateFeatureHarness();

    try {
      feature.bindUpdateHandlers();
      feature.startPolling();
      await flushAsyncWork();

      assertContains(
        elementText(deps.els.updateStatusPanel),
        "Update log running",
      );
      const activeStage = deps.els.updateStatusPanel.querySelector(
        "li[aria-current='step']",
      );
      assert.ok(activeStage);
      assertContains(elementText(activeStage), "Installing");
      assertContains(elementText(activeStage), "Active");
      assertCompletedStageCount(deps.els.updateStatusPanel, 5);
    } finally {
      feature.dispose();
    }
  });
}

async function runUpdatePersistedSsidRehydratesInput(): Promise<void> {
  await withMaintenanceScope(async (scope) => {
    scope.server.use(
      ...buildUpdateHandlers({
        status: createIdleUpdateStatus({
          ssid: "Workshop Wi-Fi",
          updated_at: 123,
          last_success_at: 123,
        }),
      }),
    );

    const { deps, feature } = await createUpdateFeatureHarness();
    deps.updateSsidInput.value = "";

    try {
      feature.bindUpdateHandlers();
      feature.startPolling();
      await flushAsyncWork();

      assert.equal(deps.updateSsidInput.value, "Workshop Wi-Fi");
      assertContains(
        elementText(deps.updateReadinessSummary),
        "Ready to update",
      );
      assert.equal(deps.updateStartBtn.disabled, false);
    } finally {
      feature.dispose();
    }
  });
}

async function runUpdatePersistedSsidRespectsUserEdit(): Promise<void> {
  await withMaintenanceScope(async (scope) => {
    scope.server.use(
      ...buildUpdateHandlers({
        status: createIdleUpdateStatus({
          ssid: "Workshop Wi-Fi",
          updated_at: 123,
          last_success_at: 123,
        }),
      }),
    );

    const { deps, feature } = await createUpdateFeatureHarness();

    try {
      feature.bindUpdateHandlers();
      await flushAsyncWork();
      deps.updateSsidInput.value = "Driver-entered Wi-Fi";
      deps.updateSsidInput.dispatchEvent(new Event("input", { bubbles: true }));
      await flushAsyncWork();
      feature.startPolling();
      await flushAsyncWork();

      assert.equal(deps.updateSsidInput.value, "Driver-entered Wi-Fi");
    } finally {
      feature.dispose();
    }
  });
}

async function runUpdateFailedStateSurfacesRecovery(): Promise<void> {
  await withMaintenanceScope(async (scope) => {
    scope.server.use(
      ...buildUpdateHandlers({
        status: createIdleUpdateStatus({
          state: "failed",
          phase: "restoring_hotspot",
          transport: "wifi",
          issues: [
            {
              phase: "restoring_hotspot",
              message: "Hotspot restart timed out",
              detail: "NetworkManager is still reconnecting to the uplink.",
            },
          ],
        }),
      }),
    );

    const { deps, feature } = await createUpdateFeatureHarness();

    try {
      feature.bindUpdateHandlers();
      await flushAsyncWork();
      deps.updateSsidInput.value = "MyWiFi";
      deps.updateSsidInput.dispatchEvent(new Event("input", { bubbles: true }));
      await flushAsyncWork();
      feature.startPolling();
      await flushAsyncWork();

      assertContains(
        elementText(deps.updateReadinessSummary),
        "Update recovery",
      );
      assertContains(
        elementText(deps.updateReadinessSummary),
        "Restore network connection",
      );
      assertContains(
        elementText(deps.updateReadinessSummary),
        "Reconnect Wi-Fi or use USB internet.",
      );
      assert.equal(deps.updateStartBtn.textContent, "Retry update");
      assertContains(elementText(deps.els.updateStatusPanel), "Update issues");
      assertContains(
        elementText(deps.els.updateStatusPanel),
        "Latest update attempt",
      );
      assertContains(
        elementText(deps.els.updateStatusPanel),
        "Update log failed",
      );
      assertContains(
        elementText(deps.els.updateStatusPanel),
        "Hotspot restart timed out",
      );
      assertContains(
        elementText(deps.els.updateStatusPanel),
        "NetworkManager is still reconnecting to the uplink.",
      );
      const stoppedStage = requireStageText(
        deps.els.updateStatusPanel,
        "Restoring hotspot",
      );
      assertContains(stoppedStage, "Needs attention");
    } finally {
      feature.dispose();
    }
  });
}

async function runUpdateCancelRefreshesStatusImmediately(): Promise<void> {
  await withMaintenanceScope(async (scope) => {
    let statusRequests = 0;
    scope.server.use(
      ...buildUpdateHandlers({
        status: () => {
          statusRequests += 1;
          return createIdleUpdateStatus();
        },
      }),
    );

    const { deps, feature } = await createUpdateFeatureHarness();

    try {
      feature.bindUpdateHandlers();
      feature.startPolling();
      await flushAsyncWork();
      const initialStatusRequests = statusRequests;

      deps.updateCancelBtn.click();
      await flushAsyncWork();

      assert.equal(statusRequests, initialStatusRequests + 1);
    } finally {
      feature.dispose();
    }
  });
}

async function runUpdateLeavingPollingContextStopsFollowupRefreshes(): Promise<void> {
  await withMaintenanceScope(async (scope) => {
    const deferredStatus =
      createDeferred<ReturnType<typeof createIdleUpdateStatus>>();
    let statusRequests = 0;
    scope.server.use(
      ...buildUpdateHandlers({
        status: async () => {
          statusRequests += 1;
          return await deferredStatus.promise;
        },
      }),
    );

    const { feature } = await createUpdateFeatureHarness();

    try {
      feature.bindUpdateHandlers();
      feature.startPolling();
      await flushAsyncWork();

      feature.stopPolling();
      deferredStatus.resolve(createIdleUpdateStatus());
      await flushAsyncWork();
      await flushAsyncWork();

      assert.equal(statusRequests, 1);
    } finally {
      feature.dispose();
    }
  });
}

const maintenanceSignalTests = [
  {
    name: "esp flash start refreshes status immediately",
    run: runEspFlashStartRefreshesStatusImmediately,
  },
  {
    name: "esp flash manual port selection drives start payload",
    run: runEspFlashManualPortSelection,
  },
  {
    name: "esp flash cancel refreshes status immediately",
    run: runEspFlashCancelRefreshesStatusImmediately,
  },
  {
    name: "esp flash leaving polling context stops followup refreshes",
    run: runEspFlashLeavingPollingContextStopsFollowupRefreshes,
  },
  {
    name: "esp flash idle state renders readiness and history panels",
    run: runEspFlashIdleStateRendersPanels,
  },
  {
    name: "esp flash no ports blocks action",
    run: runEspFlashNoPortsBlocksAction,
  },
  {
    name: "esp flash running state highlights active stage",
    run: runEspFlashRunningStateHighlightsStage,
  },
  {
    name: "esp flash failed refresh keeps stopped stage",
    run: runEspFlashFailedRefreshKeepsStoppedStage,
  },
  {
    name: "update start refreshes status immediately",
    run: runUpdateStartRefreshesStatusImmediately,
  },
  {
    name: "update USB transport flow uses USB payload",
    run: runUpdateUsbTransportFlow,
  },
  {
    name: "update idle state renders readiness and journey",
    run: runUpdateIdleStatusRendersPanels,
  },
  {
    name: "update degraded health blocks start",
    run: runUpdateDegradedHealthBlocksStart,
  },
  {
    name: "update running state highlights active stage",
    run: runUpdateRunningStateHighlightsStage,
  },
  {
    name: "update persisted ssid rehydrates input",
    run: runUpdatePersistedSsidRehydratesInput,
  },
  {
    name: "update persisted ssid respects user edits",
    run: runUpdatePersistedSsidRespectsUserEdit,
  },
  {
    name: "update failed state surfaces recovery details",
    run: runUpdateFailedStateSurfacesRecovery,
  },
  {
    name: "update cancel refreshes status immediately",
    run: runUpdateCancelRefreshesStatusImmediately,
  },
  {
    name: "update leaving polling context stops followup refreshes",
    run: runUpdateLeavingPollingContextStopsFollowupRefreshes,
  },
];

for (const maintenanceSignalTest of maintenanceSignalTests) {
  test(maintenanceSignalTest.name, maintenanceSignalTest.run);
}

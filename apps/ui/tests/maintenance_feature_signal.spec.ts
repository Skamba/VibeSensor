import assert from "node:assert/strict";
import { test } from "vitest";

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

      assertContains(
        deps.espFlashStartSummary.innerHTML,
        "settings.esp_flash.start_readiness.summary_ready",
      );
      assertContains(
        deps.espFlashStartSummary.innerHTML,
        "settings.esp_flash.start_readiness.item.connection_ready",
      );
      assert.equal(deps.espFlashStartBtn.disabled, false);
      assert.equal(deps.espFlashCancelBtn.hidden, true);
      assertContains(
        deps.espFlashReadinessPanel.innerHTML,
        "settings.esp_flash.readiness.summary.ready_ports",
      );
      assertContains(
        deps.espFlashReadinessPanel.innerHTML,
        "settings.esp_flash.readiness.one_port",
      );
      assertContains(
        deps.espFlashReadinessPanel.innerHTML,
        "settings.esp_flash.auto_detect",
      );
      assertNotContains(
        deps.espFlashReadinessPanel.innerHTML,
        "settings.esp_flash.journey_title",
      );
      assertNotContains(
        deps.espFlashReadinessPanel.innerHTML,
        "settings.esp_flash.phase.validating",
      );
      assertContains(
        deps.espFlashJourneyPanel.innerHTML,
        "settings.esp_flash.phase.validating",
      );
      assertContains(
        deps.els.espFlashLogPanel.innerHTML,
        "settings.esp_flash.logs_idle_title",
      );
      assertContains(
        deps.els.espFlashHistoryPanel.innerHTML,
        "settings.esp_flash.history_empty_title",
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

      assertContains(
        deps.espFlashStartSummary.innerHTML,
        "settings.esp_flash.start_readiness.summary_blocked",
      );
      assertContains(
        deps.espFlashStartSummary.innerHTML,
        "settings.esp_flash.start_readiness.item.connection_blocked",
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

      assertContains(
        deps.espFlashStartSummary.innerHTML,
        "settings.esp_flash.start_readiness.summary_running",
      );
      assert.equal(deps.espFlashStartBtn.hidden, true);
      assert.equal(deps.espFlashCancelBtn.hidden, false);
      assertContains(
        deps.els.espFlashLogPanel.innerHTML,
        "settings.esp_flash.logs_running_title",
      );
      const html = deps.espFlashJourneyPanel.innerHTML;
      assert.match(
        html,
        /<li(?=[^>]*data-stage-phase="flashing")(?=[^>]*data-stage-state="active")(?=[^>]*aria-current="step")[^>]*>/,
      );
      assertContains(
        deps.espFlashReadinessPanel.innerHTML,
        "settings.esp_flash.readiness.current_step",
      );
      assert.equal(html.match(/data-stage-state="done"/g)?.length ?? 0, 3);
      assert.equal(
        html.match(/<span class="maintenance-stage__marker">✓<\/span>/g)
          ?.length ?? 0,
        3,
      );
    } finally {
      feature.dispose();
    }
  });
}

async function runEspFlashFailedRefreshKeepsStoppedStage(): Promise<void> {
  await withMaintenanceScope(async (scope) => {
    let status = {
      state: "running",
      phase: "flashing",
      selected_port: "/dev/ttyUSB0",
      auto_detect: false,
      last_success_at: null,
      error: null,
      log_count: 0,
    };
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

      const html = deps.espFlashJourneyPanel.innerHTML;
      assert.match(
        html,
        /<li(?=[^>]*data-stage-phase="flashing")(?=[^>]*data-stage-state="attention")[^>]*>/,
      );
      assertContains(
        deps.espFlashStartSummary.innerHTML,
        "settings.esp_flash.recovery.title",
      );
      assertContains(
        deps.espFlashStartSummary.innerHTML,
        "settings.esp_flash.recovery.flashing.detail",
      );
      assert.equal(
        deps.espFlashStartBtn.textContent,
        "settings.esp_flash.retry",
      );
      assertContains(
        deps.els.espFlashLogPanel.innerHTML,
        "settings.esp_flash.logs_failed_title",
      );
      assertContains(
        deps.els.espFlashHistoryPanel.innerHTML,
        "serial port disconnected",
      );
      assert.equal(html.match(/data-stage-state="done"/g)?.length ?? 0, 3);
      assertContains(
        deps.espFlashReadinessPanel.innerHTML,
        "serial port disconnected",
      );
    } finally {
      feature.dispose();
    }
  });
}

async function runUpdateStartRefreshesStatusImmediately(): Promise<void> {
  await withMaintenanceScope(async (scope) => {
    const startRequests: Array<{
      password: string;
      ssid?: string | null;
      transport: string;
    }> = [];
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
    const startRequests: Array<{
      password: string;
      ssid?: string | null;
      transport: string;
    }> = [];
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
        deps.updateReadinessSummary.innerHTML,
        "settings.update.readiness.item.connection_usb_ready",
      );
      assert.equal(
        deps.updateDetailsCaption.textContent,
        "settings.update.details_caption_usb",
      );
      assert.equal(
        deps.updateTransportNote.textContent,
        "settings.update.preflight_note_usb",
      );
      assert.equal(
        deps.updateUsbTransportSummary.textContent,
        "settings.update.transport.usb_summary_interface",
      );
      assert.equal(
        deps.updateTransportChoiceWifi.getAttribute("data-selected"),
        null,
      );
      assert.equal(
        deps.updateTransportChoiceWifi.getAttribute("data-choice-state"),
        null,
      );
      assert.equal(
        deps.updateTransportChoiceWifi.getAttribute("data-choice-badge"),
        null,
      );
      assert.equal(
        deps.updateTransportChoiceUsb.getAttribute("data-selected"),
        "true",
      );
      assert.equal(
        deps.updateTransportChoiceUsb.getAttribute("data-choice-state"),
        "active",
      );
      assert.equal(
        deps.updateTransportChoiceUsb.getAttribute("data-choice-badge"),
        "settings.update.transport.selected_badge",
      );
      assert.equal(
        deps.updateTransportChoiceUsb.getAttribute("data-disabled"),
        null,
      );
      assertContains(deps.internetStatusPanel.innerHTML, "usb0");

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
        deps.els.updateStatusPanel.innerHTML,
        "settings.update.journey_title",
      );
      assertContains(
        deps.els.updateStatusPanel.innerHTML,
        "settings.update.phase.validating",
      );
      assertNotContains(
        deps.els.updateStatusPanel.innerHTML,
        "settings.update.issues_empty_title",
      );
      assertContains(
        deps.els.updateStatusPanel.innerHTML,
        "settings.update.log_empty_title",
      );
      assertContains(
        deps.els.updateOverviewPanel.innerHTML,
        "settings.update.current_status_title",
      );
      assertContains(
        deps.els.updateOverviewPanel.innerHTML,
        "settings.update.current_status_summary.ready",
      );
      assertContains(deps.els.updateOverviewPanel.innerHTML, "1.2.3");
      assertContains(
        deps.els.updateOverviewPanel.innerHTML,
        "settings.update.health_card_title",
      );
      assertContains(
        deps.internetStatusPanel.innerHTML,
        "settings.internet.card_title",
      );
      assertContains(
        deps.internetStatusPanel.innerHTML,
        "settings.internet.summary.not_detected",
      );
      assert.equal(deps.updateTransportOptions.hidden, false);
      assert.equal(
        deps.updateTransportChoiceWifi.getAttribute("data-selected"),
        "true",
      );
      assert.equal(
        deps.updateTransportChoiceWifi.getAttribute("data-choice-state"),
        "active",
      );
      assert.equal(
        deps.updateTransportChoiceWifi.getAttribute("data-choice-badge"),
        "settings.update.transport.selected_badge",
      );
      assert.equal(
        deps.updateTransportChoiceUsb.getAttribute("data-disabled"),
        "true",
      );
      assert.equal(deps.updateTransportUsbRadio.disabled, true);
      assertContains(
        deps.updateReadinessSummary.innerHTML,
        "settings.update.readiness.summary_ready",
      );
      assertContains(
        deps.updateReadinessSummary.innerHTML,
        "settings.update.readiness.item.connection_wifi_ready",
      );
      assert.equal(
        deps.updateDetailsCaption.textContent,
        "settings.update.details_caption_wifi",
      );
      assert.equal(deps.updateStartBtn.disabled, false);
      assert.equal(
        deps.updateUsbTransportSummary.textContent,
        "settings.update.transport.usb_summary_unavailable",
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
        deps.updateReadinessSummary.innerHTML,
        "settings.update.readiness.item.health_blocked",
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

      const html = deps.els.updateStatusPanel.innerHTML;
      assertContains(html, "settings.update.log_running_title");
      assert.match(
        html,
        /<li(?=[^>]*data-stage-phase="installing")(?=[^>]*data-stage-state="active")(?=[^>]*aria-current="step")[^>]*>/,
      );
      assert.equal(html.match(/data-stage-state="done"/g)?.length ?? 0, 5);
      assert.equal(
        html.match(/<span class="maintenance-stage__marker">✓<\/span>/g)
          ?.length ?? 0,
        5,
      );
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
        deps.updateReadinessSummary.innerHTML,
        "settings.update.readiness.summary_ready",
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

      const html = deps.els.updateStatusPanel.innerHTML;
      assertContains(
        deps.updateReadinessSummary.innerHTML,
        "settings.update.recovery.title",
      );
      assertContains(
        deps.updateReadinessSummary.innerHTML,
        "settings.update.recovery.wifi.title",
      );
      assertContains(
        deps.updateReadinessSummary.innerHTML,
        "settings.update.recovery.wifi.detail",
      );
      assert.equal(deps.updateStartBtn.textContent, "settings.update.retry");
      assertContains(html, "settings.update.issues");
      assertContains(html, "settings.update.attempt_title");
      assertContains(html, "settings.update.log_failed_title");
      assertContains(html, "Hotspot restart timed out");
      assertContains(
        html,
        "NetworkManager is still reconnecting to the uplink.",
      );
      assert.match(
        html,
        /<li(?=[^>]*data-stage-phase="restoring_hotspot")(?=[^>]*data-stage-state="attention")[^>]*>/,
      );
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

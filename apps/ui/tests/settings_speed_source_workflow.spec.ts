import { expect, test } from "@playwright/test";

import {
  createSettingsSpeedSourceWorkflow,
  type SettingsSpeedSourceWorkflowViewPorts,
} from "../src/app/features/settings_speed_source_workflow";
import type {
  ObdDevicePayload,
  SpeedSourcePayload,
  SpeedSourceRequest,
} from "../src/api/types";
import { createAppState } from "../src/app/ui_app_state";
import { effect } from "../src/app/ui_signals";

type WorkflowHarness = {
  contextVisible: boolean;
  errors: string[];
  focuses: string[];
};

function createHarness(): WorkflowHarness {
  return {
    contextVisible: false,
    errors: [],
    focuses: [],
  };
}

function createViewPorts(
  harness: WorkflowHarness,
): SettingsSpeedSourceWorkflowViewPorts {
  return {
    focusManualSpeedInput(): void {
      harness.focuses.push("manual");
    },
    focusScanObdDevices(): void {
      harness.focuses.push("scan");
    },
    focusStaleTimeoutInput(): void {
      harness.focuses.push("stale-timeout");
    },
    isObdConfigVisible(): boolean {
      return harness.contextVisible;
    },
  };
}

function createTranslator(): (key: string, vars?: Record<string, unknown>) => string {
  return (key, vars) => {
    if (vars?.source && typeof vars.source === "string") {
      return `${key}:${vars.source}`;
    }
    if (vars?.count && typeof vars.count === "number") {
      return `${key}:${vars.count}`;
    }
    return key;
  };
}

function makeSpeedSourcePayload(
  overrides: Partial<SpeedSourcePayload> = {},
): SpeedSourcePayload {
  return {
    manual_speed_kph: null,
    obd_device_mac: null,
    obd_device_name: null,
    speed_source: "gps",
    stale_timeout_s: 5,
    ...overrides,
  };
}

function makeObdDevice(
  overrides: Partial<ObdDevicePayload> = {},
): ObdDevicePayload {
  return {
    connected: false,
    mac_address: "00:22:d9:00:1b:b1",
    name: "OBDLink CX",
    paired: false,
    rfcomm_channel: null,
    trusted: false,
    ...overrides,
  };
}

test.describe("createSettingsSpeedSourceWorkflow", () => {
  test("applies loaded payload updates as one render-state invalidation", async () => {
    const harness = createHarness();
    const appState = createAppState();
    const workflow = createSettingsSpeedSourceWorkflow({
      renderSpeedReadout: () => undefined,
      settings: appState.settings,
      showError: (message) => {
        harness.errors.push(message);
      },
      t: createTranslator(),
      transport: {
        async loadSpeedSource() {
          return makeSpeedSourcePayload({
            manual_speed_kph: 90,
            obd_device_mac: "00:22:d9:00:1b:b1",
            obd_device_name: "OBDLink CX",
            speed_source: "manual",
            stale_timeout_s: 12,
          });
        },
      },
      view: createViewPorts(harness),
    });
    const seenSnapshots: string[] = [];

    const dispose = effect(() => {
      const state = workflow.renderState.value;
      seenSnapshots.push([
        state.selectedMode,
        state.manualSpeedInputValue,
        state.staleTimeoutInputValue,
        state.settings.speedSource,
        String(state.settings.manualSpeedKph),
      ].join(":"));
    });

    expect(seenSnapshots).toEqual(["gps:::gps:null"]);

    await workflow.loadSpeedSourceFromServer();

    expect(seenSnapshots).toEqual([
      "gps:::gps:null",
      "manual:90:12:manual:90",
    ]);
    expect(harness.errors).toEqual([]);

    dispose();
  });

  test("keeps the configured GPS source when saving fallback-manual edits without a radio change", async () => {
    const harness = createHarness();
    const appState = createAppState();
    appState.settings.speedSource.value = "gps";
    appState.settings.manualSpeedKph.value = 80;
    appState.settings.resolvedSpeedSource.value = "fallback_manual";
    appState.settings.gpsEffectiveSpeedKph.value = 80;
    let savedPayload: SpeedSourceRequest | null = null;

    const workflow = createSettingsSpeedSourceWorkflow({
      renderSpeedReadout: () => undefined,
      settings: appState.settings,
      showError: (message) => {
        harness.errors.push(message);
      },
      t: createTranslator(),
      transport: {
        async saveSpeedSource(payload) {
          savedPayload = payload;
          return makeSpeedSourcePayload({
            manual_speed_kph: payload.manual_speed_kph,
            speed_source: payload.speed_source,
            stale_timeout_s: payload.stale_timeout_s ?? 5,
          });
        },
      },
      view: createViewPorts(harness),
    });

    workflow.syncFromSettings();
    workflow.handleManualSpeedInput("90");
    workflow.handleStaleTimeoutInput("5");
    await workflow.saveSpeedSource();

    expect(savedPayload).toEqual({
      manual_speed_kph: 90,
      speed_source: "gps",
      stale_timeout_s: 5,
    });
    expect(workflow.getRenderState().selectedMode).toBe("gps");
    expect(appState.settings.speedSource.value).toBe("gps");
    expect(appState.settings.manualSpeedKph.value).toBe(90);
    expect(harness.focuses).toEqual([]);
    expect(harness.errors).toEqual([]);
  });

  test("surfaces OBD save validation without DOM fixtures", async () => {
    const harness = createHarness();
    const appState = createAppState();
    const workflow = createSettingsSpeedSourceWorkflow({
      renderSpeedReadout: () => undefined,
      settings: appState.settings,
      showError: (message) => {
        harness.errors.push(message);
      },
      t: createTranslator(),
      view: createViewPorts(harness),
    });

    workflow.handleSpeedSourceChanged("obd2");
    workflow.handleStaleTimeoutInput("5");
    await workflow.saveSpeedSource();

    expect(harness.focuses).toEqual(["scan"]);
    expect(workflow.getRenderState()).toMatchObject({
      obdSelectionError: true,
      selectedMode: "obd2",
      saveFeedback: {
        body: "settings.speed.obd_missing_device_error",
        detail: "settings.speed.validation_active_detail:settings.speed.gps",
        title: "settings.speed.save_failed_title",
        tone: "error",
      },
    });
  });

  test("clears manual validation feedback in one render-state invalidation", async () => {
    const harness = createHarness();
    const appState = createAppState();
    const workflow = createSettingsSpeedSourceWorkflow({
      renderSpeedReadout: () => undefined,
      settings: appState.settings,
      showError: (message) => {
        harness.errors.push(message);
      },
      t: createTranslator(),
      view: createViewPorts(harness),
    });

    workflow.handleSpeedSourceChanged("manual");
    await workflow.saveSpeedSource();

    const seenSnapshots: string[] = [];
    const dispose = effect(() => {
      const state = workflow.renderState.value;
      seenSnapshots.push([
        state.manualSpeedInputValue,
        state.manualSpeedFeedback?.body ?? "none",
        state.saveFeedback?.body ?? "none",
      ].join(":"));
    });

    expect(seenSnapshots).toEqual([
      ":settings.speed.manual_invalid:settings.speed.manual_invalid",
    ]);

    workflow.handleManualSpeedInput("80");

    expect(seenSnapshots).toEqual([
      ":settings.speed.manual_invalid:settings.speed.manual_invalid",
      "80:none:none",
    ]);
    expect(harness.errors).toEqual([]);

    dispose();
  });

  test("scans and pairs OBD devices without DOM bindings", async () => {
    const harness = createHarness();
    const appState = createAppState();
    const scannedDevice = makeObdDevice();

    const workflow = createSettingsSpeedSourceWorkflow({
      createPollingController: () => ({
        restart() {
          /* no-op */
        },
        start() {
          /* no-op */
        },
        stop() {
          /* no-op */
        },
      }),
      renderSpeedReadout: () => undefined,
      settings: appState.settings,
      showError: (message) => {
        harness.errors.push(message);
      },
      t: createTranslator(),
      transport: {
        async pairObdDevice(macAddress) {
          return {
            configured_device_mac: macAddress,
            configured_device_name: "OBDLink CX",
            connected: true,
            paired: true,
            rfcomm_channel: 1,
            trusted: true,
          };
        },
        async scanObdDevices() {
          return {
            devices: [scannedDevice],
          };
        },
      },
      view: createViewPorts(harness),
    });

    harness.contextVisible = true;
    workflow.handleSpeedSourceChanged("obd2");
    await workflow.scanObdDevices();
    await workflow.pairObdDevice(scannedDevice.mac_address);

    expect(workflow.getRenderState().scannedDevices).toEqual([{
      ...scannedDevice,
      connected: true,
      paired: true,
      rfcomm_channel: 1,
      trusted: true,
    }]);
    expect(appState.settings.obdDeviceMac.value).toBe(scannedDevice.mac_address);
    expect(appState.settings.obdDeviceName.value).toBe("OBDLink CX");
    expect(harness.errors).toEqual([]);
  });

  test("background rescans react to navigation context changes without DOM bindings", async () => {
    const harness = createHarness();
    const appState = createAppState();
    let pollingStarts = 0;
    let pollingStops = 0;

    const workflow = createSettingsSpeedSourceWorkflow({
      createPollingController: () => ({
        restart() {
          /* no-op */
        },
        start() {
          pollingStarts += 1;
        },
        stop() {
          pollingStops += 1;
        },
      }),
      renderSpeedReadout: () => undefined,
      settings: appState.settings,
      showError: (message) => {
        harness.errors.push(message);
      },
      t: createTranslator(),
      transport: {
        async scanObdDevices() {
          return {
            devices: [makeObdDevice()],
          };
        },
      },
      view: createViewPorts(harness),
    });

    harness.contextVisible = true;
    workflow.handleSpeedSourceChanged("obd2");
    await workflow.scanObdDevices();

    expect(pollingStarts).toBeGreaterThan(0);

    harness.contextVisible = false;
    workflow.handleNavigateContext();

    expect(pollingStops).toBeGreaterThan(0);

    harness.contextVisible = true;
    workflow.handleNavigateContext();

    expect(pollingStarts).toBeGreaterThan(1);
    expect(harness.errors).toEqual([]);
  });

  test("reflects polled effective speed updates in render state", () => {
    const harness = createHarness();
    const appState = createAppState();
    const workflow = createSettingsSpeedSourceWorkflow({
      createPollingController: () => ({
        restart() {},
        start() {},
        stop() {},
      }),
      renderSpeedReadout: () => undefined,
      settings: appState.settings,
      showError: (message) => {
        harness.errors.push(message);
      },
      t: createTranslator(),
      view: createViewPorts(harness),
    });

    appState.settings.speedSource.value = "obd2";
    appState.settings.resolvedSpeedSource.value = "obd2";
    appState.settings.gpsEffectiveSpeedKph.value = 81;

    expect(workflow.getRenderState().settings.gpsEffectiveSpeedKph).toBe(81);
    expect(harness.errors).toEqual([]);
  });

  test("derives selected mode and manual input from settings when no draft exists", () => {
    const harness = createHarness();
    const appState = createAppState();
    const workflow = createSettingsSpeedSourceWorkflow({
      createPollingController: () => ({
        restart() {},
        start() {},
        stop() {},
      }),
      renderSpeedReadout: () => undefined,
      settings: appState.settings,
      showError: (message) => {
        harness.errors.push(message);
      },
      t: createTranslator(),
      view: createViewPorts(harness),
    });

    expect(workflow.getRenderState()).toMatchObject({
      manualSpeedInputValue: "",
      selectedMode: "gps",
    });

    appState.settings.manualSpeedKph.value = 88;
    appState.settings.speedSource.value = "manual";
    appState.settings.resolvedSpeedSource.value = "manual";

    expect(workflow.getRenderState()).toMatchObject({
      manualSpeedInputValue: "88",
      selectedMode: "manual",
    });
    expect(harness.errors).toEqual([]);
  });

  test("keeps local manual input draft when settings change externally", () => {
    const harness = createHarness();
    const appState = createAppState();
    appState.settings.speedSource.value = "gps";
    appState.settings.manualSpeedKph.value = 80;

    const workflow = createSettingsSpeedSourceWorkflow({
      createPollingController: () => ({
        restart() {},
        start() {},
        stop() {},
      }),
      renderSpeedReadout: () => undefined,
      settings: appState.settings,
      showError: (message) => {
        harness.errors.push(message);
      },
      t: createTranslator(),
      view: createViewPorts(harness),
    });

    workflow.handleManualSpeedInput("90");
    appState.settings.manualSpeedKph.value = 70;
    workflow.syncFromSettings();

    expect(workflow.getRenderState()).toMatchObject({
      draftDirty: false,
      manualSpeedInputValue: "90",
      selectedMode: "gps",
    });

    workflow.syncInputsFromSettings();

    expect(workflow.getRenderState()).toMatchObject({
      draftDirty: false,
      manualSpeedInputValue: "70",
      selectedMode: "gps",
    });
    expect(harness.errors).toEqual([]);
  });
});

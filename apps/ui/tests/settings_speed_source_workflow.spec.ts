import { describe, expect, test } from "vitest";
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
import { effect, signal, type Signal } from "../src/app/ui_signals";
import { createTestQueryClient } from "./query_client_test_support";

type WorkflowHarness = {
  obdConfigVisible: Signal<boolean>;
  errors: string[];
  focuses: string[];
};

function createHarness(): WorkflowHarness {
  return {
    obdConfigVisible: signal(false),
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
  };
}

function createTranslator(): (
  key: string,
  vars?: Record<string, unknown>,
) => string {
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

function deferred<T>(): {
  promise: Promise<T>;
  reject: (reason: unknown) => void;
  resolve: (value: T) => void;
} {
  let resolve: (value: T) => void = () => {};
  let reject: (reason: unknown) => void = () => {};
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, reject, resolve };
}

describe("createSettingsSpeedSourceWorkflow", () => {
  test("applies loaded payload updates as one render-state invalidation", async () => {
    const harness = createHarness();
    const appState = createAppState();
    const workflow = createSettingsSpeedSourceWorkflow({
      obdConfigVisible: harness.obdConfigVisible,
      queryClient: createTestQueryClient(),
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
      seenSnapshots.push(
        [
          state.selectedMode,
          state.manualSpeedInputValue,
          state.staleTimeoutInputValue,
          state.settings.speedSource,
          String(state.settings.manualSpeedKph),
        ].join(":"),
      );
    });

    expect(seenSnapshots).toEqual(["gps:::gps:null"]);

    await workflow.loadSpeedSourceFromServer();

    expect(seenSnapshots).toEqual(["gps:::gps:null", "manual:90:12:manual:90"]);
    expect(harness.errors).toEqual([]);

    dispose();
    workflow.dispose();
  });

  test("keeps the configured GPS source when saving fallback-manual edits without a radio change", async () => {
    const harness = createHarness();
    const appState = createAppState();
    appState.settings.speed.source.value = "gps";
    appState.settings.speed.manualSpeedKph.value = 80;
    appState.settings.speed.resolvedSource.value = "fallback_manual";
    appState.settings.speed.gpsEffectiveSpeedKph.value = 80;
    let savedPayload: SpeedSourceRequest | null = null;

    const workflow = createSettingsSpeedSourceWorkflow({
      obdConfigVisible: harness.obdConfigVisible,
      queryClient: createTestQueryClient(),
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
            speed_source: payload.speed_source ?? "gps",
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
    expect(appState.settings.speed.source.value).toBe("gps");
    expect(appState.settings.speed.manualSpeedKph.value).toBe(90);
    expect(harness.focuses).toEqual([]);
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });

  test("surfaces OBD save validation without DOM fixtures", async () => {
    const harness = createHarness();
    const appState = createAppState();
    const workflow = createSettingsSpeedSourceWorkflow({
      obdConfigVisible: harness.obdConfigVisible,
      queryClient: createTestQueryClient(),
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
    workflow.dispose();
  });

  test("clears manual validation feedback in one render-state invalidation", async () => {
    const harness = createHarness();
    const appState = createAppState();
    const workflow = createSettingsSpeedSourceWorkflow({
      obdConfigVisible: harness.obdConfigVisible,
      queryClient: createTestQueryClient(),
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
      seenSnapshots.push(
        [
          state.manualSpeedInputValue,
          state.manualSpeedFeedback?.body ?? "none",
          state.saveFeedback?.body ?? "none",
        ].join(":"),
      );
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
    workflow.dispose();
  });

  test("scans and pairs OBD devices without DOM bindings", async () => {
    const harness = createHarness();
    const appState = createAppState();
    const scannedDevice = makeObdDevice();

    const workflow = createSettingsSpeedSourceWorkflow({
      settings: appState.settings,
      queryClient: createTestQueryClient(),
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
      obdConfigVisible: harness.obdConfigVisible,
      view: createViewPorts(harness),
    });

    harness.obdConfigVisible.value = true;
    workflow.handleSpeedSourceChanged("obd2");
    await workflow.scanObdDevices();
    await workflow.pairObdDevice(scannedDevice.mac_address);

    expect(workflow.getRenderState().scannedDevices).toEqual([
      {
        ...scannedDevice,
        connected: true,
        paired: true,
        rfcomm_channel: 1,
        trusted: true,
      },
    ]);
    expect(appState.settings.speed.obdDeviceMac.value).toBe(
      scannedDevice.mac_address,
    );
    expect(appState.settings.speed.obdDeviceName.value).toBe("OBDLink CX");
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });

  test("reflects polled effective speed updates in render state", () => {
    const harness = createHarness();
    const appState = createAppState();
    const workflow = createSettingsSpeedSourceWorkflow({
      obdConfigVisible: harness.obdConfigVisible,
      queryClient: createTestQueryClient(),
      settings: appState.settings,
      showError: (message) => {
        harness.errors.push(message);
      },
      t: createTranslator(),
      view: createViewPorts(harness),
    });

    appState.settings.speed.source.value = "obd2";
    appState.settings.speed.resolvedSource.value = "obd2";
    appState.settings.speed.gpsEffectiveSpeedKph.value = 81;

    expect(workflow.getRenderState().settings.gpsEffectiveSpeedKph).toBe(81);
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });

  test("ignores load results that resolve after disposal", async () => {
    const harness = createHarness();
    const appState = createAppState();
    const load = deferred<SpeedSourcePayload>();
    const workflow = createSettingsSpeedSourceWorkflow({
      obdConfigVisible: harness.obdConfigVisible,
      queryClient: createTestQueryClient(),
      settings: appState.settings,
      showError: (message) => {
        harness.errors.push(message);
      },
      t: createTranslator(),
      transport: {
        loadSpeedSource: () => load.promise,
      },
      view: createViewPorts(harness),
    });

    const loading = workflow.loadSpeedSourceFromServer();
    workflow.dispose();
    load.resolve(
      makeSpeedSourcePayload({
        manual_speed_kph: 77,
        speed_source: "manual",
        stale_timeout_s: 12,
      }),
    );
    await loading;

    expect(appState.settings.speed.source.value).toBe("gps");
    expect(appState.settings.speed.manualSpeedKph.value).toBeNull();
    expect(workflow.getRenderState().staleTimeoutInputValue).toBe("");
    expect(harness.errors).toEqual([]);
  });

  test("ignores load errors that reject after disposal", async () => {
    const harness = createHarness();
    const appState = createAppState();
    const load = deferred<SpeedSourcePayload>();
    const workflow = createSettingsSpeedSourceWorkflow({
      obdConfigVisible: harness.obdConfigVisible,
      queryClient: createTestQueryClient(),
      settings: appState.settings,
      showError: (message) => {
        harness.errors.push(message);
      },
      t: createTranslator(),
      transport: {
        loadSpeedSource: () => load.promise,
      },
      view: createViewPorts(harness),
    });

    const loading = workflow.loadSpeedSourceFromServer();
    workflow.dispose();
    load.reject(new Error("offline"));
    await expect(loading).resolves.toBeUndefined();

    expect(appState.settings.speed.source.value).toBe("gps");
    expect(harness.errors).toEqual([]);
  });

  test("ignores save results that resolve after disposal", async () => {
    const harness = createHarness();
    const appState = createAppState();
    const save = deferred<SpeedSourcePayload>();
    const workflow = createSettingsSpeedSourceWorkflow({
      obdConfigVisible: harness.obdConfigVisible,
      queryClient: createTestQueryClient(),
      settings: appState.settings,
      showError: (message) => {
        harness.errors.push(message);
      },
      t: createTranslator(),
      transport: {
        saveSpeedSource: () => save.promise,
      },
      view: createViewPorts(harness),
    });

    workflow.handleSpeedSourceChanged("manual");
    workflow.handleManualSpeedInput("77");
    const saving = workflow.saveSpeedSource();
    workflow.dispose();
    save.resolve(
      makeSpeedSourcePayload({
        manual_speed_kph: 77,
        speed_source: "manual",
        stale_timeout_s: 5,
      }),
    );
    await saving;

    expect(appState.settings.speed.source.value).toBe("gps");
    expect(appState.settings.speed.manualSpeedKph.value).toBeNull();
    expect(workflow.getRenderState().saveFeedback).toBeNull();
    expect(harness.errors).toEqual([]);
  });

  test("ignores scan results that resolve after disposal", async () => {
    const harness = createHarness();
    const appState = createAppState();
    const scan = deferred<{ devices: ObdDevicePayload[] }>();
    const workflow = createSettingsSpeedSourceWorkflow({
      obdConfigVisible: harness.obdConfigVisible,
      queryClient: createTestQueryClient(),
      settings: appState.settings,
      showError: (message) => {
        harness.errors.push(message);
      },
      t: createTranslator(),
      transport: {
        scanObdDevices: () => scan.promise,
      },
      view: createViewPorts(harness),
    });

    const scanning = workflow.scanObdDevices();
    workflow.dispose();
    scan.resolve({ devices: [makeObdDevice()] });
    await scanning;

    expect(workflow.getRenderState().scannedDevices).toEqual([]);
    expect(workflow.getRenderState().obdScanStatusMessage).toBe(
      "settings.speed.obd_scanning",
    );
    expect(harness.errors).toEqual([]);
  });

  test("ignores pair results that resolve after disposal", async () => {
    const harness = createHarness();
    const appState = createAppState();
    const pair = deferred<{
      configured_device_mac: string;
      configured_device_name: string | null;
      connected: boolean;
      paired: boolean;
      rfcomm_channel: number | null;
      trusted: boolean;
    }>();
    const workflow = createSettingsSpeedSourceWorkflow({
      obdConfigVisible: harness.obdConfigVisible,
      queryClient: createTestQueryClient(),
      settings: appState.settings,
      showError: (message) => {
        harness.errors.push(message);
      },
      t: createTranslator(),
      transport: {
        pairObdDevice: () => pair.promise,
      },
      view: createViewPorts(harness),
    });

    const pairing = workflow.pairObdDevice("00:22:d9:00:1b:b1");
    workflow.dispose();
    pair.resolve({
      configured_device_mac: "00:22:d9:00:1b:b1",
      configured_device_name: "OBDLink CX",
      connected: true,
      paired: true,
      rfcomm_channel: 1,
      trusted: true,
    });
    await pairing;

    expect(appState.settings.speed.obdDeviceMac.value).toBeNull();
    expect(workflow.getRenderState().scannedDevices).toEqual([]);
    expect(harness.errors).toEqual([]);
  });

  test("ignores repeated save clicks while a save is in flight", async () => {
    const harness = createHarness();
    const appState = createAppState();
    const save = deferred<SpeedSourcePayload>();
    const savedPayloads: SpeedSourceRequest[] = [];
    const workflow = createSettingsSpeedSourceWorkflow({
      obdConfigVisible: harness.obdConfigVisible,
      queryClient: createTestQueryClient(),
      settings: appState.settings,
      showError: (message) => {
        harness.errors.push(message);
      },
      t: createTranslator(),
      transport: {
        saveSpeedSource(payload) {
          savedPayloads.push(payload);
          return save.promise;
        },
      },
      view: createViewPorts(harness),
    });

    workflow.handleSpeedSourceChanged("manual");
    workflow.handleManualSpeedInput("88");
    workflow.handleStaleTimeoutInput("5");
    const firstSave = workflow.saveSpeedSource();
    const secondSave = workflow.saveSpeedSource();

    expect(savedPayloads).toEqual([
      {
        manual_speed_kph: 88,
        speed_source: "manual",
        stale_timeout_s: 5,
      },
    ]);
    save.resolve(
      makeSpeedSourcePayload({
        manual_speed_kph: 88,
        speed_source: "manual",
        stale_timeout_s: 5,
      }),
    );
    await Promise.all([firstSave, secondSave]);

    expect(appState.settings.speed.source.value).toBe("manual");
    expect(appState.settings.speed.manualSpeedKph.value).toBe(88);
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });

  test("ignores repeated pair clicks while pairing is in flight", async () => {
    const harness = createHarness();
    const appState = createAppState();
    const pair = deferred<{
      configured_device_mac: string;
      configured_device_name: string | null;
      connected: boolean;
      paired: boolean;
      rfcomm_channel: number | null;
      trusted: boolean;
    }>();
    const pairedMacs: string[] = [];
    const workflow = createSettingsSpeedSourceWorkflow({
      obdConfigVisible: harness.obdConfigVisible,
      queryClient: createTestQueryClient(),
      settings: appState.settings,
      showError: (message) => {
        harness.errors.push(message);
      },
      t: createTranslator(),
      transport: {
        pairObdDevice(macAddress) {
          pairedMacs.push(macAddress);
          return pair.promise;
        },
      },
      view: createViewPorts(harness),
    });

    const firstPair = workflow.pairObdDevice("00:22:d9:00:1b:b1");
    const secondPair = workflow.pairObdDevice("00:22:d9:00:1b:b1");

    expect(pairedMacs).toEqual(["00:22:d9:00:1b:b1"]);
    pair.resolve({
      configured_device_mac: "00:22:d9:00:1b:b1",
      configured_device_name: "OBDLink CX",
      connected: true,
      paired: true,
      rfcomm_channel: 1,
      trusted: true,
    });
    await Promise.all([firstPair, secondPair]);

    expect(appState.settings.speed.obdDeviceMac.value).toBe(
      "00:22:d9:00:1b:b1",
    );
    expect(workflow.getRenderState().pairInFlightMac).toBeNull();
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });

  test("derives selected mode and manual input from settings when no draft exists", () => {
    const harness = createHarness();
    const appState = createAppState();
    const workflow = createSettingsSpeedSourceWorkflow({
      obdConfigVisible: harness.obdConfigVisible,
      queryClient: createTestQueryClient(),
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

    appState.settings.speed.manualSpeedKph.value = 88;
    appState.settings.speed.source.value = "manual";
    appState.settings.speed.resolvedSource.value = "manual";

    expect(workflow.getRenderState()).toMatchObject({
      manualSpeedInputValue: "88",
      selectedMode: "manual",
    });
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });

  test("keeps local manual input draft when settings change externally", () => {
    const harness = createHarness();
    const appState = createAppState();
    appState.settings.speed.source.value = "gps";
    appState.settings.speed.manualSpeedKph.value = 80;

    const workflow = createSettingsSpeedSourceWorkflow({
      obdConfigVisible: harness.obdConfigVisible,
      queryClient: createTestQueryClient(),
      settings: appState.settings,
      showError: (message) => {
        harness.errors.push(message);
      },
      t: createTranslator(),
      view: createViewPorts(harness),
    });

    workflow.handleManualSpeedInput("90");
    appState.settings.speed.manualSpeedKph.value = 70;
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
    workflow.dispose();
  });
});

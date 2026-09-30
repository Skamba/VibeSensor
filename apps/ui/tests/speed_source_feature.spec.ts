import { beforeEach, describe, expect, test, vi } from "vitest";
import type {
  ObdDevicePayload,
  SpeedSourcePayload,
  SpeedSourceRequest,
} from "../src/api/types";
import { createSpeedSourceFeature } from "../src/app/features/speed_source_feature";
import { createAppState } from "../src/app/ui_app_state";
import { effect, signal } from "../src/app/ui_signals";
import {
  createDeferred as deferred,
  expectSingleInFlightOperation,
  resolveAfterDisposal,
} from "./async_test_helpers";
import { createTestQueryClient } from "./query_client_test_support";

const api = vi.hoisted(() => ({
  getSettingsObdStatus: vi.fn(),
  getSettingsSpeedSource: vi.fn(),
  getSpeedSourceStatus: vi.fn(),
  pairSettingsObdDevice: vi.fn(),
  scanSettingsObdDevices: vi.fn(),
  updateSettingsSpeedSource: vi.fn(),
}));

vi.mock("../src/api/settings", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/settings")>()),
  ...api,
}));

beforeEach(() => {
  vi.resetAllMocks();
  // Status polling is not under test here; keep its startup fetch inert.
  api.getSpeedSourceStatus.mockRejectedValue(new Error("offline"));
});

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

function createHarness(
  options: {
    appState?: ReturnType<typeof createAppState>;
    speedTabVisible?: boolean;
  } = {},
) {
  const appState = options.appState ?? createAppState();
  const errors: string[] = [];
  const focuses: string[] = [];
  const feature = createSpeedSourceFeature({
    panel: {
      actions: signal(null),
      diagnostics: signal(null),
      model: signal(null),
      focusManualSpeedInput(): void {
        focuses.push("manual");
      },
      focusScanObdDevices(): void {
        focuses.push("scan");
      },
      focusStaleTimeoutInput(): void {
        focuses.push("stale-timeout");
      },
      isObdConfigVisible: () => false,
    },
    settings: appState.settings,
    queryClient: createTestQueryClient(),
    services: {
      t: createTranslator(),
      showError: (message) => {
        errors.push(message);
      },
    },
    formatting: {
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
    },
    getSpeedUnit: () => "kmh",
    activeViewId: signal(
      options.speedTabVisible ? "settingsView" : "dashboardView",
    ),
    activeSettingsTabId: signal("speedSourceTab"),
  });
  return { appState, errors, feature, focuses };
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

describe("createSpeedSourceFeature", () => {
  test("applies loaded payload updates as one render-state invalidation", async () => {
    const appState = createAppState();
    api.getSettingsSpeedSource.mockImplementation(async () => {
      return makeSpeedSourcePayload({
        manual_speed_kph: 90,
        obd_device_mac: "00:22:d9:00:1b:b1",
        obd_device_name: "OBDLink CX",
        speed_source: "manual",
        stale_timeout_s: 12,
      });
    });
    const { errors, feature, focuses } = createHarness({ appState });
    const seenSnapshots: string[] = [];

    const dispose = effect(() => {
      const state = feature.renderState.value;
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

    await feature.loadSpeedSourceFromServer();

    expect(seenSnapshots).toEqual(["gps:::gps:null", "manual:90:12:manual:90"]);
    expect(errors).toEqual([]);

    dispose();
    feature.dispose();
  });

  test("keeps the configured GPS source when saving fallback-manual edits without a radio change", async () => {
    const appState = createAppState();
    appState.settings.speed.source.value = "gps";
    appState.settings.speed.manualSpeedKph.value = 80;
    appState.settings.speed.resolvedSource.value = "fallback_manual";
    appState.settings.speed.gpsEffectiveSpeedKph.value = 80;
    let savedPayload: SpeedSourceRequest | null = null;

    api.updateSettingsSpeedSource.mockImplementation(
      async (payload: SpeedSourceRequest) => {
        savedPayload = payload;
        return makeSpeedSourcePayload({
          manual_speed_kph: payload.manual_speed_kph,
          speed_source: payload.speed_source ?? "gps",
          stale_timeout_s: payload.stale_timeout_s ?? 5,
        });
      },
    );
    const { errors, feature, focuses } = createHarness({ appState });

    feature.handleManualSpeedInput("90");
    feature.handleStaleTimeoutInput("5");
    await feature.saveSpeedSource();

    expect(savedPayload).toEqual({
      manual_speed_kph: 90,
      speed_source: "gps",
      stale_timeout_s: 5,
    });
    expect(feature.renderState.value.selectedMode).toBe("gps");
    expect(appState.settings.speed.source.value).toBe("gps");
    expect(appState.settings.speed.manualSpeedKph.value).toBe(90);
    expect(focuses).toEqual([]);
    expect(errors).toEqual([]);
    feature.dispose();
  });

  test("surfaces OBD save validation without DOM fixtures", async () => {
    const appState = createAppState();
    const { errors, feature, focuses } = createHarness({ appState });

    feature.handleSpeedSourceChanged("obd2");
    feature.handleStaleTimeoutInput("5");
    await feature.saveSpeedSource();

    expect(focuses).toEqual(["scan"]);
    expect(feature.renderState.value).toMatchObject({
      obdSelectionError: true,
      selectedMode: "obd2",
      saveFeedback: {
        body: "settings.speed.obd_missing_device_error",
        detail: "settings.speed.validation_active_detail:settings.speed.gps",
        title: "settings.speed.save_failed_title",
        tone: "error",
      },
    });
    feature.dispose();
  });

  test("clears manual validation feedback in one render-state invalidation", async () => {
    const appState = createAppState();
    const { errors, feature, focuses } = createHarness({ appState });

    feature.handleSpeedSourceChanged("manual");
    await feature.saveSpeedSource();

    const seenSnapshots: string[] = [];
    const dispose = effect(() => {
      const state = feature.renderState.value;
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

    feature.handleManualSpeedInput("80");

    expect(seenSnapshots).toEqual([
      ":settings.speed.manual_invalid:settings.speed.manual_invalid",
      "80:none:none",
    ]);
    expect(errors).toEqual([]);

    dispose();
    feature.dispose();
  });

  test("rejects manual speed values outside the production workflow bounds", async () => {
    const appState = createAppState();
    const savedPayloads: SpeedSourceRequest[] = [];
    api.updateSettingsSpeedSource.mockImplementation(
      async (payload: SpeedSourceRequest) => {
        savedPayloads.push(payload);
        return makeSpeedSourcePayload({
          manual_speed_kph: payload.manual_speed_kph,
          speed_source: "manual",
          stale_timeout_s: payload.stale_timeout_s ?? 5,
        });
      },
    );
    const { errors, feature, focuses } = createHarness({ appState });

    feature.handleSpeedSourceChanged("manual");
    feature.handleManualSpeedInput("9999");
    await feature.saveSpeedSource();

    expect(savedPayloads).toEqual([]);
    expect(focuses).toEqual(["manual"]);
    expect(feature.renderState.value).toMatchObject({
      manualSpeedFeedback: {
        body: "settings.speed.manual_invalid",
        compact: true,
        tone: "error",
      },
      saveFeedback: {
        body: "settings.speed.manual_invalid",
        detail: "settings.speed.validation_active_detail:settings.speed.gps",
        title: "settings.speed.save_failed_title",
        tone: "error",
      },
    });

    feature.handleManualSpeedInput("500");
    await feature.saveSpeedSource();

    expect(savedPayloads).toEqual([
      {
        manual_speed_kph: 500,
        speed_source: "manual",
      },
    ]);
    expect(feature.renderState.value.manualSpeedFeedback).toBeNull();
    expect(errors).toEqual([]);
    feature.dispose();
  });

  test("keeps the manual draft when a speed-source save fails", async () => {
    const appState = createAppState();
    api.updateSettingsSpeedSource.mockImplementation(async () => {
      throw new Error("Speed source save failed");
    });
    const { errors, feature, focuses } = createHarness({ appState });

    feature.handleSpeedSourceChanged("manual");
    feature.handleManualSpeedInput("45");
    await feature.saveSpeedSource();

    expect(feature.renderState.value).toMatchObject({
      manualSpeedInputValue: "45",
      saveFeedback: {
        body: "Speed source save failed",
        detail: "settings.speed.save_failed_detail:settings.speed.gps",
        title: "settings.speed.save_failed_title",
        tone: "error",
      },
      selectedMode: "manual",
    });
    expect(appState.settings.speed.source.value).toBe("gps");
    expect(appState.settings.speed.manualSpeedKph.value).toBeNull();
    expect(focuses).toEqual([]);
    expect(errors).toEqual([]);
    feature.dispose();
  });

  test("scans and pairs OBD devices without DOM bindings", async () => {
    const appState = createAppState();
    const scannedDevice = makeObdDevice();

    api.pairSettingsObdDevice.mockImplementation(async (macAddress: string) => {
      return {
        configured_device_mac: macAddress,
        configured_device_name: "OBDLink CX",
        connected: true,
        paired: true,
        rfcomm_channel: 1,
        trusted: true,
      };
    });
    api.scanSettingsObdDevices.mockImplementation(async () => {
      return {
        devices: [scannedDevice],
      };
    });
    const { errors, feature, focuses } = createHarness({
      appState,
      speedTabVisible: true,
    });

    feature.handleSpeedSourceChanged("obd2");
    await feature.scanObdDevices();
    await feature.pairObdDevice(scannedDevice.mac_address);

    expect(feature.renderState.value.scannedDevices).toEqual([
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
    expect(errors).toEqual([]);
    feature.dispose();
  });

  test("reflects polled effective speed updates in render state", () => {
    const appState = createAppState();
    const { errors, feature, focuses } = createHarness({ appState });

    appState.settings.speed.source.value = "obd2";
    appState.settings.speed.resolvedSource.value = "obd2";
    appState.settings.speed.gpsEffectiveSpeedKph.value = 81;

    expect(feature.renderState.value.settings.gpsEffectiveSpeedKph).toBe(81);
    expect(errors).toEqual([]);
    feature.dispose();
  });

  test("ignores load results that resolve after disposal", async () => {
    const appState = createAppState();
    const load = deferred<SpeedSourcePayload>();
    api.getSettingsSpeedSource.mockImplementation(() => load.promise);
    const { errors, feature, focuses } = createHarness({ appState });

    const loading = feature.loadSpeedSourceFromServer();
    feature.dispose();
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
    expect(feature.renderState.value.staleTimeoutInputValue).toBe("");
    expect(errors).toEqual([]);
  });

  test("ignores load errors that reject after disposal", async () => {
    const appState = createAppState();
    const load = deferred<SpeedSourcePayload>();
    api.getSettingsSpeedSource.mockImplementation(() => load.promise);
    const { errors, feature, focuses } = createHarness({ appState });

    const loading = feature.loadSpeedSourceFromServer();
    feature.dispose();
    load.reject(new Error("offline"));
    await expect(loading).resolves.toBeUndefined();

    expect(appState.settings.speed.source.value).toBe("gps");
    expect(errors).toEqual([]);
  });

  test("ignores save results that resolve after disposal", async () => {
    const appState = createAppState();
    const save = deferred<SpeedSourcePayload>();
    api.updateSettingsSpeedSource.mockImplementation(() => save.promise);
    const { errors, feature, focuses } = createHarness({ appState });

    feature.handleSpeedSourceChanged("manual");
    feature.handleManualSpeedInput("77");
    await resolveAfterDisposal({
      dispose: () => {
        feature.dispose();
      },
      resolve: save.resolve,
      start: () => feature.saveSpeedSource(),
      value: makeSpeedSourcePayload({
        manual_speed_kph: 77,
        speed_source: "manual",
        stale_timeout_s: 5,
      }),
    });

    expect(appState.settings.speed.source.value).toBe("gps");
    expect(appState.settings.speed.manualSpeedKph.value).toBeNull();
    expect(feature.renderState.value.saveFeedback).toBeNull();
    expect(errors).toEqual([]);
  });

  test("ignores repeated save clicks while a save is in flight", async () => {
    const appState = createAppState();
    const save = deferred<SpeedSourcePayload>();
    const savedPayloads: SpeedSourceRequest[] = [];
    api.updateSettingsSpeedSource.mockImplementation(
      (payload: SpeedSourceRequest) => {
        savedPayloads.push(payload);
        return save.promise;
      },
    );
    const { errors, feature, focuses } = createHarness({ appState });

    feature.handleSpeedSourceChanged("manual");
    feature.handleManualSpeedInput("88");
    feature.handleStaleTimeoutInput("5");
    await expectSingleInFlightOperation({
      callCount: () => savedPayloads.length,
      resolve: save.resolve,
      start: () => feature.saveSpeedSource(),
      value: makeSpeedSourcePayload({
        manual_speed_kph: 88,
        speed_source: "manual",
        stale_timeout_s: 5,
      }),
    });

    expect(savedPayloads).toEqual([
      {
        manual_speed_kph: 88,
        speed_source: "manual",
        stale_timeout_s: 5,
      },
    ]);

    expect(appState.settings.speed.source.value).toBe("manual");
    expect(appState.settings.speed.manualSpeedKph.value).toBe(88);
    expect(errors).toEqual([]);
    feature.dispose();
  });

  test("derives selected mode and manual input from settings when no draft exists", () => {
    const appState = createAppState();
    const { errors, feature, focuses } = createHarness({ appState });

    expect(feature.renderState.value).toMatchObject({
      manualSpeedInputValue: "",
      selectedMode: "gps",
    });

    appState.settings.speed.manualSpeedKph.value = 88;
    appState.settings.speed.source.value = "manual";
    appState.settings.speed.resolvedSource.value = "manual";

    expect(feature.renderState.value).toMatchObject({
      manualSpeedInputValue: "88",
      selectedMode: "manual",
    });
    expect(errors).toEqual([]);
    feature.dispose();
  });

  test("keeps local manual input draft until saved settings are reloaded", async () => {
    const appState = createAppState();
    appState.settings.speed.source.value = "gps";
    appState.settings.speed.manualSpeedKph.value = 80;
    api.getSettingsSpeedSource.mockResolvedValue(
      makeSpeedSourcePayload({ manual_speed_kph: 70 }),
    );

    const { errors, feature } = createHarness({ appState });

    feature.handleManualSpeedInput("90");
    appState.settings.speed.manualSpeedKph.value = 70;

    expect(feature.renderState.value).toMatchObject({
      draftDirty: false,
      manualSpeedInputValue: "90",
      selectedMode: "gps",
    });

    await feature.loadSpeedSourceFromServer();

    expect(feature.renderState.value).toMatchObject({
      draftDirty: false,
      manualSpeedInputValue: "70",
      selectedMode: "gps",
    });
    expect(errors).toEqual([]);
    feature.dispose();
  });
});

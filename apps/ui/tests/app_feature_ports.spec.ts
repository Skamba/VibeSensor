import { expect, test } from "@playwright/test";

import {
  createAppFeatureBundlePorts,
  createRealtimeFeatureRecordingPorts,
} from "../src/app/app_feature_bundle_ports";

test("feature port helpers expose the narrowed shell and startup contracts", async () => {
  const calls: string[] = [];

  const history = {
    bindHandlers() {
      calls.push("history.bindHandlers");
    },
    async refreshHistory() {
      calls.push("history.refreshHistory");
    },
  };
  const realtime = {
    bindHandlers() {
      calls.push("realtime.bindHandlers");
    },
    async refreshLocationOptions() {
      calls.push("realtime.refreshLocationOptions");
    },
    async refreshLoggingStatus() {
      calls.push("realtime.refreshLoggingStatus");
    },
  };
  const settings = {
    bindHandlers() {
      calls.push("settings.bindHandlers");
    },
    syncSettingsInputs() {
      calls.push("settings.syncSettingsInputs");
    },
    async loadSpeedSourceFromServer() {
      calls.push("settings.loadSpeedSourceFromServer");
    },
    async loadAnalysisSettingsFromServer() {
      calls.push("settings.loadAnalysisSettingsFromServer");
    },
    async loadCarsFromServer() {
      calls.push("settings.loadCarsFromServer");
    },
    syncCarsPayload() {
      calls.push("settings.syncCarsPayload");
    },
    syncActiveCarToInputs() {
      calls.push("settings.syncActiveCarToInputs");
    },
    showCarCreationSuccess(carId: string, carName: string) {
      calls.push(`settings.showCarCreationSuccess:${carId}:${carName}`);
    },
    renderCarList() {
      calls.push("settings.renderCarList");
    },
  };
  const cars = {
    bindWizardHandlers() {
      calls.push("cars.bindWizardHandlers");
    },
  };
  const update = {
    bindUpdateHandlers() {
      calls.push("update.bindUpdateHandlers");
    },
  };
  const espFlash = {
    bindHandlers() {
      calls.push("espFlash.bindHandlers");
    },
  };

  const recording = createRealtimeFeatureRecordingPorts(history);
  const bundle = createAppFeatureBundlePorts({
    history,
    realtime,
    settings,
    cars,
    update,
    espFlash,
  });

  expect(Object.keys(bundle).sort()).toEqual(["shell", "startup"]);

  await recording.onRecordingStatusChanged();

  bundle.shell.bindHandlers();

  await bundle.startup.history.refreshHistory();
  await bundle.startup.realtime.refreshLocationOptions();
  await bundle.startup.realtime.refreshLoggingStatus();
  await bundle.startup.settings.loadSpeedSourceFromServer();
  await bundle.startup.settings.loadAnalysisSettingsFromServer();
  await bundle.startup.settings.loadCarsFromServer();

  expect(calls).toEqual([
    "history.refreshHistory",
    "settings.bindHandlers",
    "cars.bindWizardHandlers",
    "realtime.bindHandlers",
    "history.bindHandlers",
    "update.bindUpdateHandlers",
    "espFlash.bindHandlers",
    "history.refreshHistory",
    "realtime.refreshLocationOptions",
    "realtime.refreshLoggingStatus",
    "settings.loadSpeedSourceFromServer",
    "settings.loadAnalysisSettingsFromServer",
    "settings.loadCarsFromServer",
  ]);
});

test("realtime recording port preserves history refresh failures", async () => {
  const error = new Error("history refresh failed");
  const recording = createRealtimeFeatureRecordingPorts({
    async refreshHistory() {
      throw error;
    },
  });

  await expect(recording.onRecordingStatusChanged()).rejects.toThrow(error);
});

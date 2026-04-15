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
    renderHistoryTable() {
      calls.push("history.renderHistoryTable");
    },
    reloadExpandedRunOnLanguageChange() {
      calls.push("history.reloadExpandedRunOnLanguageChange");
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

  bundle.shell.bindSettingsHandlers();
  bundle.shell.bindCarWizardHandlers();
  bundle.shell.bindRealtimeHandlers();
  bundle.shell.bindHistoryHandlers();
  bundle.shell.bindUpdateHandlers();
  bundle.shell.bindEspFlashHandlers();
  bundle.shell.languageRefresh.history.renderHistoryTable();
  bundle.shell.languageRefresh.history.reloadExpandedRunOnLanguageChange();
  bundle.shell.languageRefresh.settings.syncSettingsInputs();

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
    "history.renderHistoryTable",
    "history.reloadExpandedRunOnLanguageChange",
    "settings.syncSettingsInputs",
    "history.refreshHistory",
    "realtime.refreshLocationOptions",
    "realtime.refreshLoggingStatus",
    "settings.loadSpeedSourceFromServer",
    "settings.loadAnalysisSettingsFromServer",
    "settings.loadCarsFromServer",
  ]);
});

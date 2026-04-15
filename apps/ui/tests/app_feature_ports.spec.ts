import { expect, test } from "@playwright/test";

import {
  createAppFeatureBundlePorts,
  createRealtimeFeatureRecordingPorts,
  createSettingsFeatureRealtimePorts,
} from "../src/app/app_feature_bundle_ports";

test("feature port helpers expose explicit shell and startup contracts without a full app shell", async () => {
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
    maybeRenderSensorsSettingsList(force?: boolean) {
      calls.push(`realtime.maybeRenderSensorsSettingsList:${String(force)}`);
    },
    renderStatus() {
      calls.push("realtime.renderStatus");
    },
    renderLoggingStatus() {
      calls.push("realtime.renderLoggingStatus");
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
    startGpsStatusPolling() {
      calls.push("settings.startGpsStatusPolling");
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
    startPolling() {
      calls.push("update.startPolling");
    },
  };
  const espFlash = {
    bindHandlers() {
      calls.push("espFlash.bindHandlers");
    },
    startPolling() {
      calls.push("espFlash.startPolling");
    },
  };

  const settingsRealtime = createSettingsFeatureRealtimePorts(realtime);
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

  settingsRealtime.renderRealtimeStatus();
  settingsRealtime.renderRealtimeLoggingStatus();
  await recording.onRecordingStatusChanged();

  bundle.shell.bindSettingsHandlers();
  bundle.shell.bindCarWizardHandlers();
  bundle.shell.bindRealtimeHandlers();
  bundle.shell.bindHistoryHandlers();
  bundle.shell.bindUpdateHandlers();
  bundle.shell.bindEspFlashHandlers();
  bundle.shell.languageRefresh.realtime.maybeRenderSensorsSettingsList(true);
  bundle.shell.languageRefresh.realtime.renderLoggingStatus();
  bundle.shell.languageRefresh.realtime.renderStatus();
  bundle.shell.languageRefresh.history.renderHistoryTable();
  bundle.shell.languageRefresh.history.reloadExpandedRunOnLanguageChange();
  bundle.shell.languageRefresh.settings.syncSettingsInputs();

  await bundle.startup.history.refreshHistory();
  await bundle.startup.realtime.refreshLocationOptions();
  await bundle.startup.realtime.refreshLoggingStatus();
  await bundle.startup.settings.loadSpeedSourceFromServer();
  await bundle.startup.settings.loadAnalysisSettingsFromServer();
  await bundle.startup.settings.loadCarsFromServer();
  bundle.startup.settings.startGpsStatusPolling();
  bundle.startup.update.startPolling();
  bundle.startup.espFlash.startPolling();

  expect(calls).toEqual([
    "realtime.renderStatus",
    "realtime.renderLoggingStatus",
    "history.refreshHistory",
    "settings.bindHandlers",
    "cars.bindWizardHandlers",
    "realtime.bindHandlers",
    "history.bindHandlers",
    "update.bindUpdateHandlers",
    "espFlash.bindHandlers",
    "realtime.maybeRenderSensorsSettingsList:true",
    "realtime.renderLoggingStatus",
    "realtime.renderStatus",
    "history.renderHistoryTable",
    "history.reloadExpandedRunOnLanguageChange",
    "settings.syncSettingsInputs",
    "history.refreshHistory",
    "realtime.refreshLocationOptions",
    "realtime.refreshLoggingStatus",
    "settings.loadSpeedSourceFromServer",
    "settings.loadAnalysisSettingsFromServer",
    "settings.loadCarsFromServer",
    "settings.startGpsStatusPolling",
    "update.startPolling",
    "espFlash.startPolling",
  ]);
});

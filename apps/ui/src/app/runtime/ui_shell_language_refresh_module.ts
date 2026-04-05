import type { HistoryFeature } from "../features/history_feature";
import type { RealtimeFeature } from "../features/realtime_feature";
import type { SettingsFeature } from "../features/settings_feature";
import type { UiShellDom } from "../dom/shell_dom";
import type { AppState } from "../ui_app_state";

export interface UiShellLanguageRefreshFeaturePorts {
  realtime: Pick<RealtimeFeature, "buildLocationOptions" | "maybeRenderSensorsSettingsList" | "renderLoggingStatus" | "renderStatus">;
  history: Pick<HistoryFeature, "renderHistoryTable" | "reloadExpandedRunOnLanguageChange">;
  settings: Pick<SettingsFeature, "syncSettingsInputs">;
}

export interface UiShellLanguageRefreshModuleDeps {
  state: AppState;
  dom: UiShellDom;
  t: (key: string, vars?: Record<string, unknown>) => string;
  renderSpeedReadout: () => void;
  renderWsState: () => void;
  renderSpectrum: () => void;
  updateSpectrumOverlay: () => void;
}

export interface UiShellLanguageRefreshModule {
  applyLanguage(features: UiShellLanguageRefreshFeaturePorts, forceReloadInsights?: boolean): void;
}

export function createUiShellLanguageRefreshModule(
  deps: UiShellLanguageRefreshModuleDeps,
): UiShellLanguageRefreshModule {
  return {
    applyLanguage(features: UiShellLanguageRefreshFeaturePorts, forceReloadInsights = false): void {
      document.documentElement.lang = deps.state.shell.lang;
      document.querySelectorAll("[data-i18n]").forEach((element) => {
        const key = element.getAttribute("data-i18n");
        if (key) {
          element.textContent = deps.t(key);
        }
      });
      if (deps.dom.languageSelect) {
        deps.dom.languageSelect.value = deps.state.shell.lang;
      }
      if (deps.dom.speedUnitSelect) {
        deps.dom.speedUnitSelect.value = deps.state.shell.speedUnit;
      }
      deps.state.realtime.locationOptions = features.realtime.buildLocationOptions(deps.state.realtime.locationCodes);
      deps.state.realtime.sensorsSettingsSignature = "";
      features.settings.syncSettingsInputs();
      features.realtime.maybeRenderSensorsSettingsList(true);
      deps.renderSpeedReadout();
      features.realtime.renderLoggingStatus();
      features.realtime.renderStatus();
      features.history.renderHistoryTable();
      deps.renderWsState();
      if (deps.state.spectrum.spectrumPlot) {
        deps.state.spectrum.spectrumPlot.destroy();
        deps.state.spectrum.spectrumPlot = null;
        deps.renderSpectrum();
      }
      if (forceReloadInsights) {
        features.history.reloadExpandedRunOnLanguageChange();
      }
      deps.updateSpectrumOverlay();
    },
  };
}

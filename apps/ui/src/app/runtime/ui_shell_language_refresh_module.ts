import type { HistoryFeature } from "../features/history_feature";
import type { SettingsFeature } from "../features/settings_feature";
import type { AppState } from "../ui_app_state";

export interface UiShellLanguageRefreshFeaturePorts {
  history: Pick<
    HistoryFeature,
    "reloadExpandedRunOnLanguageChange" | "renderHistoryTable"
  >;
  settings: Pick<SettingsFeature, "syncSettingsInputs">;
}

type UiShellLanguageRefreshDeps = {
  renderSpeedReadout: () => void;
  renderSpectrum: () => void;
  renderWsState: () => void;
  state: AppState;
  updateSpectrumOverlay: () => void;
};

export interface UiShellLanguageRefreshModule {
  applyLanguage(
    features: UiShellLanguageRefreshFeaturePorts,
    forceReloadInsights?: boolean,
  ): void;
}

export function createUiShellLanguageRefreshModule(
  deps: UiShellLanguageRefreshDeps,
): UiShellLanguageRefreshModule {
  return {
    applyLanguage(features, forceReloadInsights = false) {
      document.documentElement.lang = deps.state.shell.lang;
      features.settings.syncSettingsInputs();
      deps.renderSpeedReadout();
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

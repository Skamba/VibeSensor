import type { UiDomElements } from "./dom/ui_dom_registry";
import { createCarsFeature, type CarsFeature } from "./features/cars_feature";
import { createEspFlashFeature, type EspFlashFeature } from "./features/esp_flash_feature";
import { createHistoryFeature, type HistoryFeature } from "./features/history_feature";
import { createRealtimeFeature, type RealtimeFeature } from "./features/realtime_feature";
import { createSettingsFeature, type SettingsFeature } from "./features/settings_feature";
import { createUpdateFeature, type UpdateFeature } from "./features/update_feature";
import type { AppState } from "./state/ui_app_state";

export interface AppFeatureBundle {
  history: HistoryFeature;
  realtime: RealtimeFeature;
  settings: SettingsFeature;
  cars: CarsFeature;
  update: UpdateFeature;
  espFlash: EspFlashFeature;
}

export interface AppFeatureBundleDeps {
  state: AppState;
  els: UiDomElements;
  t: (key: string, vars?: Record<string, unknown>) => string;
  escapeHtml: (value: unknown) => string;
  fmt: (n: number, digits?: number) => string;
  fmtTs: (iso: string) => string;
  formatInt: (value: number) => string;
  setPillState: (el: HTMLElement | null, variant: string, text: string) => void;
  setStatValue: (container: HTMLElement | null, value: string | number) => void;
  renderSpectrum: () => void;
  renderSpeedReadout: () => void;
  renderCarSelectionWarning: () => void;
  sendSelection: () => void;
}

export function createAppFeatureBundle(deps: AppFeatureBundleDeps): AppFeatureBundle {
  const { state, els, t, escapeHtml, fmt, fmtTs, formatInt } = deps;

  const history = createHistoryFeature({
    state,
    els,
    t,
    escapeHtml,
    fmt,
    fmtTs,
    formatInt,
  });

  const realtime = createRealtimeFeature({
    state,
    els,
    t,
    escapeHtml,
    formatInt,
    setPillState: deps.setPillState,
    setStatValue: deps.setStatValue,
    sendSelection: deps.sendSelection,
    refreshHistory: () => history.refreshHistory(),
  });

  const settings = createSettingsFeature({
    state,
    els,
    t,
    escapeHtml,
    fmt,
    renderSpectrum: deps.renderSpectrum,
    renderSpeedReadout: deps.renderSpeedReadout,
    onCarSelectionStateChange: deps.renderCarSelectionWarning,
  });

  const cars = createCarsFeature({
    els,
    t,
    escapeHtml,
    fmt,
    addCarFromWizard: settings.addCarFromWizard,
  });

  const update = createUpdateFeature({ els, t, escapeHtml });
  const espFlash = createEspFlashFeature({ els, t, escapeHtml });

  return {
    history,
    realtime,
    settings,
    cars,
    update,
    espFlash,
  };
}

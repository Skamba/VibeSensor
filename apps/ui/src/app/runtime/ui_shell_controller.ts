import * as I18N from "../../i18n";
import { formatIntLocale } from "../../format";
import type { AppFeatureBundle } from "../app_feature_bundle";
import type { UiDomElements } from "../ui_dom_registry";
import type { AppState } from "../ui_app_state";
import {
  createUiShellNavigationModule,
  type UiShellNavigationModule,
} from "./ui_shell_navigation_module";
import {
  createUiShellPreferencesModule,
  type UiShellPreferencesModule,
} from "./ui_shell_preferences_module";
import {
  createUiShellStatusModule,
  type UiShellStatusModule,
} from "./ui_shell_status_module";

type UiShellControllerDeps = {
  state: AppState;
  els: UiDomElements;
};

export class UiShellController {
  private readonly state: AppState;

  private readonly els: UiDomElements;

  private readonly navigation: UiShellNavigationModule;

  private readonly preferences: UiShellPreferencesModule;

  private readonly status: UiShellStatusModule;

  private features: AppFeatureBundle | null = null;

  private renderSpectrumChart: (() => void) | null = null;

  private updateSpectrumOverlayState: (() => void) | null = null;

  constructor(deps: UiShellControllerDeps) {
    this.state = deps.state;
    this.els = deps.els;
    this.navigation = createUiShellNavigationModule({
      state: this.state,
      els: this.els,
      onDashboardViewActivated: () => {
        this.state.spectrumPlot?.resize();
      },
    });
    this.status = createUiShellStatusModule({
      state: this.state,
      els: this.els,
      t: (key, vars) => this.t(key, vars),
      setPillState: (el, variant, text) => this.setPillState(el, variant, text),
    });
    this.preferences = createUiShellPreferencesModule({
      state: this.state,
      els: this.els,
      t: (key, vars) => this.t(key, vars),
      normalizeLanguage: (lang) => I18N.normalizeLang(lang),
      applyLanguage: (forceReloadInsights = false) => this.applyLanguage(forceReloadInsights),
      renderSpeedReadout: () => this.status.renderSpeedReadout(),
    });
  }

  attachFeatures(features: AppFeatureBundle): void {
    this.features = features;
  }

  attachSpectrumHooks(deps: {
    renderSpectrum: () => void;
    updateSpectrumOverlay: () => void;
  }): void {
    this.renderSpectrumChart = deps.renderSpectrum;
    this.updateSpectrumOverlayState = deps.updateSpectrumOverlay;
  }

  t(key: string, vars?: Record<string, unknown>): string {
    return I18N.get(this.state.lang, key, vars);
  }

  localFormatInt(value: number): string {
    return formatIntLocale(value, this.state.lang);
  }

  setStatValue(container: HTMLElement | null, value: string | number): void {
    const valueEl = container?.querySelector?.("[data-value]");
    if (valueEl) {
      valueEl.textContent = String(value);
      return;
    }
    if (container) {
      container.textContent = String(value);
    }
  }

  setPillState(el: HTMLElement | null, variant: string, text: string): void {
    if (!el) return;
    el.className = `pill pill--${variant}`;
    el.textContent = text;
  }

  renderSpeedReadout(): void {
    this.status.renderSpeedReadout();
  }

  renderWsState(): void {
    this.status.renderWsState();
  }

  renderCarSelectionWarning(): void {
    this.status.renderCarSelectionWarning();
  }

  setActiveView(viewId: string): void {
    this.navigation.setActiveView(viewId);
  }

  applyLanguage(forceReloadInsights = false): void {
    const features = this.requireFeatures();
    document.documentElement.lang = this.state.lang;
    document.querySelectorAll("[data-i18n]").forEach((element) => {
      const key = element.getAttribute("data-i18n");
      if (key) element.textContent = this.t(key);
    });
    if (this.els.languageSelect) this.els.languageSelect.value = this.state.lang;
    if (this.els.speedUnitSelect) this.els.speedUnitSelect.value = this.state.speedUnit;
    this.state.locationOptions = features.realtime.buildLocationOptions(this.state.locationCodes);
    this.state.sensorsSettingsSignature = "";
    features.realtime.maybeRenderSensorsSettingsList(true);
    this.renderSpeedReadout();
    features.realtime.renderLoggingStatus();
    features.history.renderHistoryTable();
    this.renderWsState();
    this.renderCarSelectionWarning();
    if (this.state.spectrumPlot) {
      this.state.spectrumPlot.destroy();
      this.state.spectrumPlot = null;
      this.renderSpectrumChart?.();
    }
    if (forceReloadInsights) {
      features.history.reloadExpandedRunOnLanguageChange();
    }
    this.updateSpectrumOverlayState?.();
  }

  bindUiEvents(): void {
    this.navigation.bindHandlers();
    this.bindFeatureEvents();
    this.preferences.bindHandlers();
  }

  async hydratePersistedPreferences(): Promise<void> {
    await this.preferences.hydratePersistedPreferences();
  }

  private bindFeatureEvents(): void {
    const features = this.requireFeatures();
    features.settings.bindHandlers();
    features.cars.bindWizardHandlers();
    features.realtime.bindHandlers();
    features.history.bindHandlers();
    features.update.bindUpdateHandlers();
    features.espFlash.bindHandlers();
  }

  private requireFeatures(): AppFeatureBundle {
    if (this.features === null) {
      throw new Error("UiShellController features used before initialization");
    }
    return this.features;
  }
}

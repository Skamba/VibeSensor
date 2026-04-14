import * as I18N from "../../i18n";
import { formatIntLocale } from "../../format";
import type { UiShellDom } from "../dom/shell_dom";
import type { AppState } from "../ui_app_state";
import {
  bindUiShellFeatureEvents,
  type UiShellFeaturePorts,
} from "./ui_shell_feature_ports";
import {
  createUiShellLanguageRefreshModule,
  type UiShellLanguageRefreshModule,
} from "./ui_shell_language_refresh_module";
import {
  createUiShellNavigationModule,
  type UiShellNavigationModule,
} from "./ui_shell_navigation_module";
import {
  createUiShellNotificationModule,
  type UiShellNotificationModule,
} from "./ui_shell_notification_module";
import {
  createUiShellPreferencesModule,
  type UiShellPreferencesModule,
} from "./ui_shell_preferences_module";
import {
  createUiShellStatusModule,
  type UiShellStatusModule,
} from "./ui_shell_status_module";
import type { UiShellChromeActionBridge } from "./ui_shell_chrome";
import { setVariantState } from "../style_state";

type UiShellControllerDeps = {
  state: AppState;
  dom: UiShellDom;
  chromeActions: UiShellChromeActionBridge;
};

export class UiShellController {
  private readonly state: AppState;

  private readonly els: UiShellDom;

  private readonly navigation: UiShellNavigationModule;

  private readonly notifications: UiShellNotificationModule;

  private readonly preferences: UiShellPreferencesModule;

  private readonly status: UiShellStatusModule;

  private readonly languageRefresh: UiShellLanguageRefreshModule;

  private ports: UiShellFeaturePorts | null = null;

  private renderSpectrumChart: (() => void) | null = null;

  private updateSpectrumOverlayState: (() => void) | null = null;

  constructor(deps: UiShellControllerDeps) {
    this.state = deps.state;
    this.els = deps.dom;
    this.navigation = createUiShellNavigationModule({
      shell: this.state.shell,
      dom: this.els,
      onDashboardViewActivated: () => {
        this.state.spectrum.spectrumPlot?.resize();
      },
    });
    this.notifications = createUiShellNotificationModule({
      dom: this.els,
    });
    this.status = createUiShellStatusModule({
      shell: this.state.shell,
      transport: this.state.transport,
      realtime: this.state.realtime,
      settings: this.state.settings,
      dom: this.els,
      t: (key, vars) => this.t(key, vars),
      setPillState: (el, variant, text) => this.setPillState(el, variant, text),
    });
    this.preferences = createUiShellPreferencesModule({
      shell: this.state.shell,
      dom: this.els,
      t: (key, vars) => this.t(key, vars),
      normalizeLanguage: (lang) => I18N.normalizeLang(lang),
      applyLanguage: (forceReloadInsights = false) => this.applyLanguage(forceReloadInsights),
      renderSpeedReadout: () => this.status.renderSpeedReadout(),
      showError: (message) => this.showError(message),
    });
    deps.chromeActions.attach({
      activateView: (viewId) => this.setActiveView(viewId),
      saveLanguage: (lang) => this.preferences.saveLanguage(lang),
      saveSpeedUnit: (unit) => this.preferences.saveSpeedUnit(unit),
    });
    this.languageRefresh = createUiShellLanguageRefreshModule({
      state: this.state,
      dom: this.els,
      t: (key, vars) => this.t(key, vars),
      renderSpeedReadout: () => this.renderSpeedReadout(),
      renderWsState: () => this.renderWsState(),
      renderSpectrum: () => this.renderSpectrumChart?.(),
      updateSpectrumOverlay: () => this.updateSpectrumOverlayState?.(),
    });
  }

  attachPorts(ports: UiShellFeaturePorts): void {
    this.ports = ports;
  }

  attachSpectrumHooks(deps: {
    renderSpectrum: () => void;
    updateSpectrumOverlay: () => void;
  }): void {
    this.renderSpectrumChart = deps.renderSpectrum;
    this.updateSpectrumOverlayState = deps.updateSpectrumOverlay;
  }

  t(key: string, vars?: Record<string, unknown>): string {
    return I18N.get(this.state.shell.lang, key, vars);
  }

  localFormatInt(value: number): string {
    return formatIntLocale(value, this.state.shell.lang);
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
    el.className = "pill";
    setVariantState(el, variant === "bad" || variant === "muted" || variant === "ok" || variant === "warn"
      ? variant
      : "muted");
    el.textContent = text;
  }

  showError(message: string): void {
    this.notifications.showError(message);
  }

  renderSpeedReadout(): void {
    this.status.renderSpeedReadout();
  }

  renderWsState(): void {
    this.status.renderWsState();
  }

  setActiveView(viewId: string): void {
    this.navigation.setActiveView(viewId);
  }

  applyLanguage(forceReloadInsights = false): void {
    this.languageRefresh.applyLanguage(this.requirePorts().languageRefresh, forceReloadInsights);
  }

  bindUiEvents(): void {
    this.bindFeatureEvents();
  }

  async hydratePersistedPreferences(): Promise<void> {
    await this.preferences.hydratePersistedPreferences();
  }

  private bindFeatureEvents(): void {
    bindUiShellFeatureEvents(this.requirePorts());
  }

  private requirePorts(): UiShellFeaturePorts {
    if (this.ports === null) {
      throw new Error("UiShellController ports used before initialization");
    }
    return this.ports;
  }
}

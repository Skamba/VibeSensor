import * as I18N from "../../i18n";
import { formatIntLocale } from "../../format";
import { queryOne, queryRequiredAll } from "../dom/dom_query";
import { setUiLanguage } from "../ui_i18n";
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
import { createUiShellViewVisibilityModule } from "./ui_shell_view_visibility_module";
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
import type {
  UiShellBadgeModel,
  UiShellChromeActionBridge,
  UiShellChromeRenderModel,
  UiShellChromeView,
} from "./ui_shell_chrome";
import {
  SHELL_NAV_ITEMS,
  SPEED_UNIT_OPTIONS,
} from "./ui_shell_chrome";
import type { RealtimeLiveOverviewBridge } from "../views/realtime_live_overview";
import type { VisualVariant } from "../style_state";

type UiShellControllerDeps = {
  chrome: UiShellChromeView;
  chromeActions: UiShellChromeActionBridge;
  liveOverview: RealtimeLiveOverviewBridge;
  state: AppState;
};

function normalizeBadgeVariant(variant: string): VisualVariant {
  return variant === "bad" || variant === "muted" || variant === "ok" || variant === "warn"
    ? variant
    : "muted";
}

export class UiShellController {
  private readonly state: AppState;

  private readonly chrome: UiShellChromeView;

  private readonly navigation: UiShellNavigationModule;

  private readonly notifications: UiShellNotificationModule;

  private readonly preferences: UiShellPreferencesModule;

  private readonly status: UiShellStatusModule;

  private readonly languageRefresh: UiShellLanguageRefreshModule;

  private readonly activeViewListeners = new Set<(viewId: string) => void>();

  private ports: UiShellFeaturePorts | null = null;

  private renderSpectrumChart: (() => void) | null = null;

  private updateSpectrumOverlayState: (() => void) | null = null;

  private liveStatusBadge: UiShellBadgeModel = {
    text: "No live signal",
    variant: "muted",
  };

  constructor(deps: UiShellControllerDeps) {
    this.state = deps.state;
    setUiLanguage(this.state.shell.lang);
    this.chrome = deps.chrome;
    const appShellWrap = queryOne<HTMLElement>(".wrap");
    const views = queryRequiredAll<HTMLElement>(".view", "UI shell views");
    this.navigation = createUiShellNavigationModule({
      shell: this.state.shell,
      viewIds: views.map((view) => view.id),
      onDashboardViewActivated: () => {
        this.state.spectrum.spectrumPlot?.resize();
      },
    });
    createUiShellViewVisibilityModule({
      activeViewId: this.navigation.activeViewId,
      views,
    });
    this.notifications = createUiShellNotificationModule({
      onChanged: () => this.renderChrome(),
      window,
    });
    this.status = createUiShellStatusModule({
      appShellWrap,
      realtime: this.state.realtime,
      renderLiveOverviewSpeed: (text) => deps.liveOverview.setSpeedText(text),
      settings: this.state.settings,
      shell: this.state.shell,
      t: (key, vars) => this.t(key, vars),
      transport: this.state.transport,
    });
    this.preferences = createUiShellPreferencesModule({
      shell: this.state.shell,
      t: (key, vars) => this.t(key, vars),
      normalizeLanguage: (lang) => I18N.normalizeLang(lang ?? ""),
      applyLanguage: (forceReloadInsights = false) => this.applyLanguage(forceReloadInsights),
      renderSpeedReadout: () => this.renderSpeedReadout(),
      onChanged: () => this.renderChrome(),
    });
    deps.chromeActions.attach({
      activateView: (viewId) => this.setActiveView(viewId),
      saveLanguage: (lang) => this.preferences.saveLanguage(lang),
      saveSpeedUnit: (unit) => this.preferences.saveSpeedUnit(unit),
    });
    this.languageRefresh = createUiShellLanguageRefreshModule({
      state: this.state,
      renderSpeedReadout: () => this.renderSpeedReadout(),
      renderWsState: () => this.renderWsState(),
      renderSpectrum: () => this.renderSpectrumChart?.(),
      updateSpectrumOverlay: () => this.updateSpectrumOverlayState?.(),
    });
    this.renderChrome();
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

  showError(message: string): void {
    this.notifications.showError(message);
  }

  renderSpeedReadout(): void {
    this.status.renderSpeedReadout();
    this.renderChrome();
  }

  renderWsState(): void {
    this.status.syncConnectionState();
    this.renderChrome();
  }

  setLiveStatus(variant: string, text: string): void {
    this.liveStatusBadge = {
      text,
      variant: normalizeBadgeVariant(variant),
    };
    this.renderChrome();
  }

  subscribeActiveViewChanges(listener: (viewId: string) => void): () => void {
    this.activeViewListeners.add(listener);
    return () => {
      this.activeViewListeners.delete(listener);
    };
  }

  setActiveView(viewId: string): void {
    const previousViewId = this.state.shell.activeViewId;
    this.navigation.setActiveView(viewId);
    this.renderChrome();
    if (this.state.shell.activeViewId !== previousViewId) {
      for (const listener of this.activeViewListeners) {
        listener(this.state.shell.activeViewId);
      }
    }
  }

  applyLanguage(forceReloadInsights = false): void {
    setUiLanguage(this.state.shell.lang);
    this.languageRefresh.applyLanguage(
      this.requirePorts().languageRefresh,
      forceReloadInsights,
    );
    this.renderChrome();
  }

  bindUiEvents(): void {
    this.bindFeatureEvents();
  }

  async hydratePersistedPreferences(): Promise<void> {
    await this.preferences.hydratePersistedPreferences();
    this.renderChrome();
  }

  private bindFeatureEvents(): void {
    bindUiShellFeatureEvents(this.requirePorts());
  }

  private buildRenderModel(): UiShellChromeRenderModel {
    return {
      activeViewId: this.state.shell.activeViewId,
      appErrorBanner: this.notifications.getBannerModel(),
      languageFeedback: this.preferences.getLanguageFeedback(),
      languageLabelText: this.t("settings.language"),
      navItems: SHELL_NAV_ITEMS.map((item) => ({
        labelText: this.t(item.labelKey) || item.fallbackLabel,
        tabId: item.tabId,
        viewId: item.viewId,
      })),
      selectedLanguage: this.preferences.getSelectedLanguage(),
      selectedSpeedUnit: this.preferences.getSelectedSpeedUnit(),
      shellLiveStatus: this.liveStatusBadge,
      speedUnitFeedback: this.preferences.getSpeedUnitFeedback(),
      speedUnitLabelText: this.t("speed.unit"),
      speedUnitOptionLabels: Object.fromEntries(
        SPEED_UNIT_OPTIONS.map((option) => [option.value, this.t(option.labelKey) || option.fallbackLabel]),
      ),
      wsLinkState: this.status.getWsLinkState(),
    };
  }

  private renderChrome(): void {
    this.status.syncConnectionState();
    this.chrome.render(this.buildRenderModel());
  }

  private requirePorts(): UiShellFeaturePorts {
    if (this.ports === null) {
      throw new Error("UiShellController ports used before initialization");
    }
    return this.ports;
  }
}

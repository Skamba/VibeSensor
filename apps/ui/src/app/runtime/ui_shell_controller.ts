import type { QueryClient } from "@tanstack/query-core";

import * as I18N from "../../i18n";
import { setUiLanguage, translateUiText } from "../ui_i18n";
import type { AppState } from "../ui_app_state";
import {
  computed,
  effect,
  effectOnChange,
  signal,
  untracked,
  type Signal,
  type ReadonlySignal,
} from "../ui_signals";
import { createReplaceableTimeout } from "../timer_cleanup";
import type { VisualVariant } from "../visual_variant";
import {
  createUiConfirmationModule,
  type UiConfirmationModule,
} from "./ui_confirmation_module";
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
  UiShellChromeActions,
  UiShellChromeDialogModel,
  UiShellChromeNavigationModel,
  UiShellChromePreferencesModel,
  UiShellChromeStatusModel,
  UiShellChromeView,
  UiShellErrorBannerModel,
} from "./ui_shell_chrome";
import { SHELL_NAV_ITEMS, SPEED_UNIT_OPTIONS } from "./ui_shell_chrome";
import type { RealtimeLiveOverviewBridge } from "../views/realtime_live_overview";

export const DEFAULT_SHELL_VIEW_ID = "dashboardView";

const SHELL_VIEW_IDS: readonly string[] = SHELL_NAV_ITEMS.map(
  (item) => item.viewId,
);

const ERROR_BANNER_HIDE_MS = 5000;

const HIDDEN_BANNER_MODEL: UiShellErrorBannerModel = {
  hidden: true,
  text: "",
  variant: null,
};

function normalizeActiveViewId(viewId: string): string {
  return SHELL_VIEW_IDS.includes(viewId) ? viewId : DEFAULT_SHELL_VIEW_ID;
}

type UiShellControllerDeps = {
  bindFeatureHandlers: () => void;
  chrome: UiShellChromeView;
  chromeActions: Signal<UiShellChromeActions>;
  liveOverview: RealtimeLiveOverviewBridge;
  onViewActivated?: (viewId: string) => Promise<void>;
  queryClient: QueryClient;
  state: AppState;
};

function normalizeBadgeVariant(variant: string): VisualVariant {
  return variant === "bad" ||
    variant === "muted" ||
    variant === "ok" ||
    variant === "warn"
    ? variant
    : "muted";
}

export class UiShellController {
  private readonly state: AppState;

  private readonly chrome: UiShellChromeView;

  private readonly activeView: Signal<string>;

  private pendingViewActivationToken = 0;

  private readonly onViewActivated?: (viewId: string) => Promise<void>;

  private readonly errorBanner =
    signal<UiShellErrorBannerModel>(HIDDEN_BANNER_MODEL);

  private readonly hideErrorBannerTimer = createReplaceableTimeout(window);

  private readonly preferences: UiShellPreferencesModule;

  private readonly status: UiShellStatusModule;

  private readonly confirmation: UiConfirmationModule;

  private readonly navigationRenderModel: ReadonlySignal<UiShellChromeNavigationModel>;

  private readonly preferencesRenderModel: ReadonlySignal<UiShellChromePreferencesModel>;

  private readonly statusRenderModel: ReadonlySignal<UiShellChromeStatusModel>;

  private readonly dialogRenderModel: ReadonlySignal<UiShellChromeDialogModel>;

  private readonly bindFeatureHandlers: () => void;

  private readonly disposeDocumentLanguageSync: () => void;

  private readonly disposeReactiveLanguageSync: () => void;

  private readonly liveStatusBadge = signal<UiShellBadgeModel>({
    text: "No live signal",
    variant: "muted",
  });

  constructor(deps: UiShellControllerDeps) {
    this.state = deps.state;
    this.chrome = deps.chrome;
    this.bindFeatureHandlers = deps.bindFeatureHandlers;
    this.onViewActivated = deps.onViewActivated;
    this.activeView = signal(
      normalizeActiveViewId(this.state.shell.activeViewId.value),
    );
    this.state.shell.activeViewId.value = this.activeView.value;
    this.status = createUiShellStatusModule({
      realtime: this.state.realtime,
      settings: this.state.settings,
      shell: this.state.shell,
      t: (key, vars) => this.t(key, vars),
      transport: this.state.transport,
    });
    this.confirmation = createUiConfirmationModule({
      t: (key, vars) => this.t(key, vars),
    });
    this.preferences = createUiShellPreferencesModule({
      queryClient: deps.queryClient,
      shell: this.state.shell,
      t: (key, vars) => this.t(key, vars),
      normalizeLanguage: (lang) => I18N.normalizeLang(lang ?? ""),
      prepareLanguage: (lang) => setUiLanguage(lang),
    });
    deps.chromeActions.value = {
      activateView: (viewId) => this.setActiveView(viewId),
      cancelConfirmation: () => this.confirmation.cancel(),
      confirmConfirmation: () => this.confirmation.confirm(),
      saveLanguage: (lang) => this.preferences.saveLanguage(lang),
      saveSpeedUnit: (unit) => this.preferences.saveSpeedUnit(unit),
    };
    this.navigationRenderModel = this.createNavigationRenderModel();
    this.preferencesRenderModel = this.createPreferencesRenderModel();
    this.statusRenderModel = this.createStatusRenderModel();
    this.dialogRenderModel = this.createDialogRenderModel();
    deps.liveOverview.speedText.value = this.status.speedReadoutText;
    this.bindChromeModelSignals();
    this.disposeDocumentLanguageSync = this.bindDocumentLanguageSync();
    this.disposeReactiveLanguageSync = this.bindReactiveLanguageSync();
  }

  t(key: string, vars?: Record<string, unknown>): string {
    return translateUiText(key, vars);
  }

  showError(message: string): void {
    this.hideErrorBannerTimer.clear();
    this.errorBanner.value = { hidden: false, text: message, variant: "bad" };
    this.hideErrorBannerTimer.replace(() => {
      this.errorBanner.value = HIDDEN_BANNER_MODEL;
    }, ERROR_BANNER_HIDE_MS);
  }

  requestConfirmation(message: string): Promise<boolean> {
    return this.confirmation.requestConfirmation(message);
  }

  setLiveStatus(variant: string, text: string): void {
    this.liveStatusBadge.value = {
      text,
      variant: normalizeBadgeVariant(variant),
    };
  }

  get activeViewId(): ReadonlySignal<string> {
    return this.activeView;
  }

  /**
   * Switches views; non-dashboard views first wait for `onViewActivated`
   * (lazy chunk + data), and only the latest request wins.
   */
  setActiveView(viewId: string): void {
    const nextViewId = normalizeActiveViewId(viewId);
    const activationToken = ++this.pendingViewActivationToken;
    const activation =
      nextViewId === DEFAULT_SHELL_VIEW_ID
        ? undefined
        : this.onViewActivated?.(nextViewId);
    if (activation === undefined) {
      this.applyActiveView(nextViewId);
      return;
    }
    void activation
      .then(() => {
        if (activationToken === this.pendingViewActivationToken) {
          this.applyActiveView(nextViewId);
        }
      })
      .catch((error) => {
        if (activationToken === this.pendingViewActivationToken) {
          this.showError(
            error instanceof Error
              ? error.message
              : this.t("status.view_load_failed"),
          );
        }
      });
  }

  private applyActiveView(viewId: string): void {
    this.activeView.value = viewId;
    this.state.shell.activeViewId.value = viewId;
    if (viewId === DEFAULT_SHELL_VIEW_ID) {
      this.state.spectrum.spectrumPlot.value?.resize();
    }
  }

  start(defaultViewId: string): void {
    this.bindFeatureHandlers();
    this.setActiveView(this.activeViewId.value || defaultViewId);
  }

  dispose(): void {
    this.disposeReactiveLanguageSync();
    this.disposeDocumentLanguageSync();
    this.hideErrorBannerTimer.clear();
  }

  async hydratePersistedPreferences(): Promise<void> {
    await this.preferences.hydratePersistedPreferences();
  }

  private bindReactiveLanguageSync(): () => void {
    return effectOnChange(this.state.shell.lang, (currentLanguage) => {
      untracked(() => {
        void setUiLanguage(currentLanguage);
      });
    });
  }

  private bindDocumentLanguageSync(): () => void {
    return effect(() => {
      const currentLanguage = this.state.shell.lang.value;
      untracked(() => {
        const documentElement = globalThis.document?.documentElement;
        if (documentElement) {
          documentElement.lang = currentLanguage;
        }
      });
    });
  }

  private bindChromeModelSignals(): void {
    this.chrome.bindNavigationModel(this.navigationRenderModel);
    this.chrome.bindPreferencesModel(this.preferencesRenderModel);
    this.chrome.bindStatusModel(this.statusRenderModel);
    this.chrome.bindDialogModel(this.dialogRenderModel);
  }

  private createNavigationRenderModel(): ReadonlySignal<UiShellChromeNavigationModel> {
    return computed(() => ({
      activeViewId: this.activeView.value,
      navItems: SHELL_NAV_ITEMS.map((item) => ({
        labelText: this.t(item.labelKey) || item.fallbackLabel,
        tabId: item.tabId,
        viewId: item.viewId,
      })),
    }));
  }

  private createPreferencesRenderModel(): ReadonlySignal<UiShellChromePreferencesModel> {
    return computed(() => ({
      languageFeedback: this.preferences.languageFeedback.value,
      languageLabelText: this.t("settings.language"),
      selectedLanguage: this.preferences.selectedLanguage.value,
      selectedSpeedUnit: this.preferences.selectedSpeedUnit.value,
      speedUnitFeedback: this.preferences.speedUnitFeedback.value,
      speedUnitLabelText: this.t("speed.unit"),
      speedUnitOptionLabels: Object.fromEntries(
        SPEED_UNIT_OPTIONS.map((option) => [
          option.value,
          this.t(option.labelKey) || option.fallbackLabel,
        ]),
      ),
    }));
  }

  private createStatusRenderModel(): ReadonlySignal<UiShellChromeStatusModel> {
    return computed(() => ({
      connectionState: this.status.connectionState.value,
      shellLiveStatus: this.liveStatusBadge.value,
      wsLinkState: this.status.wsLinkState.value,
    }));
  }

  private createDialogRenderModel(): ReadonlySignal<UiShellChromeDialogModel> {
    return computed(() => ({
      appErrorBanner: this.errorBanner.value,
      confirmationDialog: this.confirmation.dialogModel.value,
    }));
  }
}

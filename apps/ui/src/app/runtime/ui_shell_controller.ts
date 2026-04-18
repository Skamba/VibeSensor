import * as I18N from "../../i18n";
import { formatIntLocale } from "../../format";
import { setUiLanguage } from "../ui_i18n";
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
import type { VisualVariant } from "../visual_variant";
import {
  createUiConfirmationModule,
  type UiConfirmationModule,
} from "./ui_confirmation_module";
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
import type {
  UiShellBadgeModel,
  UiShellChromeActions,
  UiShellChromeDialogModel,
  UiShellChromeNavigationModel,
  UiShellChromePreferencesModel,
  UiShellChromeStatusModel,
  UiShellChromeView,
} from "./ui_shell_chrome";
import {
  SHELL_NAV_ITEMS,
  SPEED_UNIT_OPTIONS,
} from "./ui_shell_chrome";
import type { RealtimeLiveOverviewBridge } from "../views/realtime_live_overview";

type UiShellControllerDeps = {
  bindFeatureHandlers: () => void;
  chrome: UiShellChromeView;
  chromeActions: Signal<UiShellChromeActions>;
  liveOverview: RealtimeLiveOverviewBridge;
  onViewActivated?: (viewId: string) => Promise<void> | void;
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

  private readonly liveOverview: RealtimeLiveOverviewBridge;

  private readonly navigation: UiShellNavigationModule;

  private readonly notifications: UiShellNotificationModule;

  private readonly preferences: UiShellPreferencesModule;

  private readonly status: UiShellStatusModule;

  private readonly confirmation: UiConfirmationModule;

  private readonly navigationRenderModel: ReadonlySignal<UiShellChromeNavigationModel>;

  private readonly preferencesRenderModel: ReadonlySignal<UiShellChromePreferencesModel>;

  private readonly statusRenderModel: ReadonlySignal<UiShellChromeStatusModel>;

  private readonly dialogRenderModel: ReadonlySignal<UiShellChromeDialogModel>;

  private readonly bindFeatureHandlers: () => void;

  private readonly liveStatusBadge = signal<UiShellBadgeModel>({
    text: "No live signal",
    variant: "muted",
  });

  constructor(deps: UiShellControllerDeps) {
    this.state = deps.state;
    this.chrome = deps.chrome;
    this.liveOverview = deps.liveOverview;
    this.bindFeatureHandlers = deps.bindFeatureHandlers;
    this.notifications = createUiShellNotificationModule({
      window,
    });
    this.navigation = createUiShellNavigationModule({
      shell: this.state.shell,
      viewIds: SHELL_NAV_ITEMS.map((item) => item.viewId),
      onViewActivated: deps.onViewActivated,
      onViewActivationFailed: (viewId, error) => {
        console.error(`[VibeSensor] Failed to activate view "${viewId}".`, error);
        this.notifications.showError(this.t("status.view_load_failed"));
      },
      onDashboardViewActivated: () => {
        this.state.spectrum.spectrumPlot.value?.resize();
      },
    });
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
      shell: this.state.shell,
      t: (key, vars) => this.t(key, vars),
      normalizeLanguage: (lang) => I18N.normalizeLang(lang ?? ""),
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
    this.bindChromeModelSignals();
    this.bindDocumentLanguageSync();
    this.bindReactiveLanguageSync();
    this.bindReactiveSpeedReadoutSync();
  }

  t(key: string, vars?: Record<string, unknown>): string {
    return I18N.get(this.state.shell.lang.value, key, vars);
  }

  localFormatInt(value: number): string {
    return formatIntLocale(value, this.state.shell.lang.value);
  }

  showError(message: string): void {
    this.notifications.showError(message);
  }

  requestConfirmation(message: string): Promise<boolean> {
    return this.confirmation.requestConfirmation(message);
  }

  renderSpeedReadout(): void {
    untracked(() => {
      this.liveOverview.speedText.value = this.status.speedReadoutText.value;
    });
  }

  setLiveStatus(variant: string, text: string): void {
    this.liveStatusBadge.value = {
      text,
      variant: normalizeBadgeVariant(variant),
    };
  }

  get activeViewId(): ReadonlySignal<string> {
    return this.navigation.activeViewId;
  }

  setActiveView(viewId: string): void {
    this.navigation.setActiveView(viewId);
  }

  start(defaultViewId: string): void {
    this.bindFeatureHandlers();
    this.setActiveView(defaultViewId);
  }

  async hydratePersistedPreferences(): Promise<void> {
    await this.preferences.hydratePersistedPreferences();
  }

  private bindReactiveLanguageSync(): void {
    effectOnChange(this.state.shell.lang, (currentLanguage) => {
      untracked(() => {
        setUiLanguage(currentLanguage);
      });
    });
  }

  private bindDocumentLanguageSync(): void {
    effect(() => {
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

  private bindReactiveSpeedReadoutSync(): void {
    effect(() => {
      const speedText = this.status.speedReadoutText.value;
      untracked(() => {
        this.liveOverview.speedText.value = speedText;
      });
    });
  }

  private createNavigationRenderModel(): ReadonlySignal<UiShellChromeNavigationModel> {
    return computed(() => ({
      activeViewId: this.navigation.activeViewId.value,
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
      appErrorBanner: this.notifications.bannerModel.value,
      confirmationDialog: this.confirmation.dialogModel.value,
    }));
  }
}

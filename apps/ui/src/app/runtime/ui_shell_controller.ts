import * as I18N from "../../i18n";
import { formatIntLocale } from "../../format";
import { queryOne } from "../dom/dom_query";
import { setUiLanguage } from "../ui_i18n";
import { trackAppStateSlice, type AppState } from "../ui_app_state";
import {
  computed,
  effect,
  signal,
  untracked,
  type ReadonlySignal,
} from "../ui_signals";
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
  UiShellChromeActionBridge,
  UiShellChromeRenderModel,
  UiShellChromeView,
} from "./ui_shell_chrome";
import {
  SHELL_NAV_ITEMS,
  SPEED_UNIT_OPTIONS,
} from "./ui_shell_chrome";
import type { RealtimeLiveOverviewBridge } from "../views/realtime_live_overview";
import type { VisualVariant } from "../view_style_types";

type UiShellControllerDeps = {
  bindFeatureHandlers: () => void;
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

  private readonly appShellWrap: HTMLElement | null;

  private readonly liveOverview: RealtimeLiveOverviewBridge;

  private readonly navigation: UiShellNavigationModule;

  private readonly notifications: UiShellNotificationModule;

  private readonly preferences: UiShellPreferencesModule;

  private readonly status: UiShellStatusModule;

  private readonly confirmation: UiConfirmationModule;

  private readonly chromeRenderModel: ReadonlySignal<UiShellChromeRenderModel>;

  private readonly bindFeatureHandlers: () => void;

  private readonly liveStatusBadge = signal<UiShellBadgeModel>({
    text: "No live signal",
    variant: "muted",
  });

  constructor(deps: UiShellControllerDeps) {
    this.state = deps.state;
    this.chrome = deps.chrome;
    this.appShellWrap = queryOne<HTMLElement>(".wrap");
    this.liveOverview = deps.liveOverview;
    this.bindFeatureHandlers = deps.bindFeatureHandlers;
    this.navigation = createUiShellNavigationModule({
      shell: this.state.shell,
      viewIds: SHELL_NAV_ITEMS.map((item) => item.viewId),
      onDashboardViewActivated: () => {
        this.state.spectrum.spectrumPlot?.resize();
      },
    });
    this.notifications = createUiShellNotificationModule({
      window,
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
    deps.chromeActions.attach({
      activateView: (viewId) => this.setActiveView(viewId),
      cancelConfirmation: () => this.confirmation.cancel(),
      confirmConfirmation: () => this.confirmation.confirm(),
      saveLanguage: (lang) => this.preferences.saveLanguage(lang),
      saveSpeedUnit: (unit) => this.preferences.saveSpeedUnit(unit),
    });
    this.chromeRenderModel = this.createChromeRenderModel();
    this.bindReactiveLanguageSync();
    this.bindReactiveStatusSync();
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

  requestConfirmation(message: string): Promise<boolean> {
    return this.confirmation.requestConfirmation(message);
  }

  renderSpeedReadout(): void {
    untracked(() => {
      this.liveOverview.setSpeedText(this.status.speedReadoutText.value);
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
    let initialized = false;
    let previousLanguage = this.state.shell.lang;
    effect(() => {
      trackAppStateSlice(this.state.shell);
      const currentLanguage = this.state.shell.lang;
      if (!initialized) {
        initialized = true;
        previousLanguage = currentLanguage;
      } else if (currentLanguage === previousLanguage) {
        return;
      } else {
        previousLanguage = currentLanguage;
      }
      untracked(() => {
        setUiLanguage(currentLanguage);
        const documentElement = globalThis.document?.documentElement;
        if (documentElement) {
          documentElement.lang = currentLanguage;
        }
      });
    });
  }

  private bindReactiveStatusSync(): void {
    effect(() => {
      const model = this.chromeRenderModel.value;
      const connectionState = this.status.connectionState.value;
      untracked(() => {
        if (this.appShellWrap) {
          this.appShellWrap.dataset.connectionState = connectionState;
        }
        this.chrome.setModel(model);
      });
    });

    effect(() => {
      const speedText = this.status.speedReadoutText.value;
      untracked(() => {
        this.liveOverview.setSpeedText(speedText);
      });
    });
  }

  private createChromeRenderModel(): ReadonlySignal<UiShellChromeRenderModel> {
    return computed(() => {
      trackAppStateSlice(this.state.shell);
      return {
        activeViewId: this.state.shell.activeViewId,
        appErrorBanner: this.notifications.bannerModel.value,
        confirmationDialog: this.confirmation.dialogModel.value,
        languageFeedback: this.preferences.languageFeedback.value,
        languageLabelText: this.t("settings.language"),
        navItems: SHELL_NAV_ITEMS.map((item) => ({
          labelText: this.t(item.labelKey) || item.fallbackLabel,
          tabId: item.tabId,
          viewId: item.viewId,
        })),
        selectedLanguage: this.preferences.selectedLanguage.value,
        selectedSpeedUnit: this.preferences.selectedSpeedUnit.value,
        shellLiveStatus: this.liveStatusBadge.value,
        speedUnitFeedback: this.preferences.speedUnitFeedback.value,
        speedUnitLabelText: this.t("speed.unit"),
        speedUnitOptionLabels: Object.fromEntries(
          SPEED_UNIT_OPTIONS.map((option) => [
            option.value,
            this.t(option.labelKey) || option.fallbackLabel,
          ]),
        ),
        wsLinkState: this.status.wsLinkState.value,
      };
    });
  }
}

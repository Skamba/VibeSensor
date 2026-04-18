import type { ReadonlySignal } from "../../ui_signals";
import type { VisualVariant } from "../../visual_variant";
import type { SettingsFeedbackMessage } from "../../views/settings_feedback";
import type { UiConfirmationDialogModel } from "../ui_confirmation_module";

export const SHELL_OWNER = "UI shell";
export const SHELL_CHROME_HOST_ID = "appShellChromeRoot";

export const SHELL_NAV_ITEMS = [
  {
    fallbackLabel: "Live",
    labelKey: "nav.live",
    tabId: "tab-dashboard",
    viewId: "dashboardView",
  },
  {
    fallbackLabel: "History",
    labelKey: "nav.history",
    tabId: "tab-history",
    viewId: "historyView",
  },
  {
    fallbackLabel: "Settings",
    labelKey: "nav.settings",
    tabId: "tab-settings",
    viewId: "settingsView",
  },
] as const;

export const SPEED_UNIT_OPTIONS = [
  { fallbackLabel: "km/h", labelKey: "speed.unit.kmh", value: "kmh" },
  { fallbackLabel: "m/s", labelKey: "speed.unit.mps", value: "mps" },
] as const;

export const SHELL_NAVIGATION_MODEL_KEYS = ["activeViewId", "navItems"] as const;
export const SHELL_ACTIVE_VIEW_KEY = ["activeViewId"] as const;
export const SHELL_PREFERENCES_MODEL_KEYS = [
  "languageFeedback",
  "languageLabelText",
  "selectedLanguage",
  "selectedSpeedUnit",
  "speedUnitFeedback",
  "speedUnitLabelText",
  "speedUnitOptionLabels",
] as const;
export const SHELL_STATUS_MODEL_KEYS = ["shellLiveStatus", "wsLinkState"] as const;
export const SHELL_DIALOG_MODEL_KEYS = ["appErrorBanner"] as const;

export interface UiShellChromeActions {
  activateView(viewId: string): void;
  cancelConfirmation(): void;
  confirmConfirmation(): void;
  saveLanguage(lang: string): Promise<void> | void;
  saveSpeedUnit(unit: string): Promise<void> | void;
}

export const DEFAULT_UI_SHELL_CHROME_ACTIONS: UiShellChromeActions = {
  activateView: noop,
  cancelConfirmation: noop,
  confirmConfirmation: noop,
  saveLanguage: noop,
  saveSpeedUnit: noop,
};

export interface UiShellBadgeModel {
  text: string;
  variant: VisualVariant;
}

export interface UiShellErrorBannerModel {
  hidden: boolean;
  text: string;
  variant: "bad" | null;
}

export interface UiShellChromeNavItemModel {
  labelText: string;
  tabId: string;
  viewId: string;
}

export interface UiShellChromeNavigationModel {
  activeViewId: string;
  navItems: readonly UiShellChromeNavItemModel[];
}

export interface UiShellChromePreferencesModel {
  languageFeedback: SettingsFeedbackMessage | null;
  languageLabelText: string;
  selectedLanguage: string;
  selectedSpeedUnit: string;
  speedUnitFeedback: SettingsFeedbackMessage | null;
  speedUnitLabelText: string;
  speedUnitOptionLabels: Record<string, string>;
}

export interface UiShellChromeStatusModel {
  connectionState: "degraded" | "live";
  shellLiveStatus: UiShellBadgeModel;
  wsLinkState: UiShellBadgeModel;
}

export interface UiShellChromeDialogModel {
  appErrorBanner: UiShellErrorBannerModel;
  confirmationDialog: UiConfirmationDialogModel | null;
}

export interface UiShellChromeView {
  bindDialogModel(model: ReadonlySignal<UiShellChromeDialogModel>): void;
  bindNavigationModel(model: ReadonlySignal<UiShellChromeNavigationModel>): void;
  bindPreferencesModel(model: ReadonlySignal<UiShellChromePreferencesModel>): void;
  bindStatusModel(model: ReadonlySignal<UiShellChromeStatusModel>): void;
}

export type UiShellChromePendingPanelHosts = {
  dashboard: {
    spectrum: HTMLDivElement | null;
    liveOverview: HTMLDivElement | null;
    logging: HTMLDivElement | null;
  };
  history: HTMLDivElement | null;
  settingsShell: HTMLDivElement | null;
};

export const DEFAULT_NAVIGATION_MODEL: UiShellChromeNavigationModel = {
  activeViewId: "dashboardView",
  navItems: SHELL_NAV_ITEMS.map((item) => ({
    labelText: item.fallbackLabel,
    tabId: item.tabId,
    viewId: item.viewId,
  })),
};

export const DEFAULT_PREFERENCES_MODEL: UiShellChromePreferencesModel = {
  languageFeedback: null,
  languageLabelText: "Language",
  selectedLanguage: "en",
  selectedSpeedUnit: "kmh",
  speedUnitFeedback: null,
  speedUnitLabelText: "Unit",
  speedUnitOptionLabels: {
    kmh: "km/h",
    mps: "m/s",
  },
};

export const DEFAULT_STATUS_MODEL: UiShellChromeStatusModel = {
  connectionState: "live",
  shellLiveStatus: {
    text: "No live signal",
    variant: "muted",
  },
  wsLinkState: {
    text: "Connecting...",
    variant: "muted",
  },
};

export const DEFAULT_DIALOG_MODEL: UiShellChromeDialogModel = {
  appErrorBanner: {
    hidden: true,
    text: "",
    variant: null,
  },
  confirmationDialog: null,
};

export function createPendingUiPanelHosts(): UiShellChromePendingPanelHosts {
  return {
    dashboard: {
      spectrum: null,
      liveOverview: null,
      logging: null,
    },
    history: null,
    settingsShell: null,
  };
}

function noop(): void {
  return;
}

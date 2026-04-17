import { render, type ComponentChildren, type JSX } from "preact";
import { useRef } from "preact/hooks";

import {
  createUiPanelHostRefs,
  resolveUiPanelHosts,
  type UiPanelHostRefs,
  type UiPanelHostRegistry,
} from "../ui_panel_host_registry";
import {
  useComputed,
  signal,
  type ReadonlySignal,
  useSignalEffect,
} from "../ui_signals";
import type { UiConfirmationDialogModel } from "./ui_confirmation_module";
import {
  settingsFeedbackClassName,
  type SettingsFeedbackMessage,
} from "../views/settings_feedback";
import type { VisualVariant } from "../view_style_types";
const SHELL_OWNER = "UI shell";
const SHELL_CHROME_HOST_ID = "appShellChromeRoot";

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

const LANGUAGE_OPTIONS = [
  { label: "🇺🇸 English", value: "en" },
  { label: "🇳🇱 Nederlands", value: "nl" },
] as const;

export interface UiShellChromeActions {
  activateView(viewId: string): void;
  cancelConfirmation(): void;
  confirmConfirmation(): void;
  saveLanguage(lang: string): Promise<void> | void;
  saveSpeedUnit(unit: string): Promise<void> | void;
}

export interface UiShellChromeActionBridge {
  readonly current: UiShellChromeActions;
  attach(actions: UiShellChromeActions): void;
}

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

export type UiShellChromeRenderModel =
  & UiShellChromeNavigationModel
  & UiShellChromePreferencesModel
  & UiShellChromeStatusModel
  & UiShellChromeDialogModel;

export interface UiShellChromeView {
  setDialogModel(model: UiShellChromeDialogModel): void;
  setNavigationModel(model: UiShellChromeNavigationModel): void;
  setPreferencesModel(model: UiShellChromePreferencesModel): void;
  setStatusModel(model: UiShellChromeStatusModel): void;
}

type UiShellChromeProps = {
  bridge: UiShellChromeActionBridge;
  dialogModel: ReadonlySignal<UiShellChromeDialogModel>;
  navigationModel: ReadonlySignal<UiShellChromeNavigationModel>;
  panelHostRefs: UiPanelHostRefs;
  preferencesModel: ReadonlySignal<UiShellChromePreferencesModel>;
  statusModel: ReadonlySignal<UiShellChromeStatusModel>;
};

type ShellViewSectionProps = {
  activeViewId: string;
  ariaLabelledBy: string;
  children: ComponentChildren;
  viewId: string;
};

const DEFAULT_NAVIGATION_MODEL: UiShellChromeNavigationModel = {
  activeViewId: "dashboardView",
  navItems: SHELL_NAV_ITEMS.map((item) => ({
    labelText: item.fallbackLabel,
    tabId: item.tabId,
    viewId: item.viewId,
  })),
};

const DEFAULT_PREFERENCES_MODEL: UiShellChromePreferencesModel = {
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

const DEFAULT_STATUS_MODEL: UiShellChromeStatusModel = {
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

const DEFAULT_DIALOG_MODEL: UiShellChromeDialogModel = {
  appErrorBanner: {
    hidden: true,
    text: "",
    variant: null,
  },
  confirmationDialog: null,
};

function noop(): void {
  return;
}

function normalizeMenuIndex(index: number): number {
  return ((index % SHELL_NAV_ITEMS.length) + SHELL_NAV_ITEMS.length) % SHELL_NAV_ITEMS.length;
}

function SettingsFeedbackSlot(props: {
  id: string;
  message: SettingsFeedbackMessage | null;
}) {
  const { id, message } = props;
  return (
    <div
      id={id}
      class="settings-feedback-slot settings-feedback-slot--compact"
      hidden={!message}
      aria-live={message ? (message.tone === "error" ? "assertive" : "polite") : undefined}
    >
      {message ? (
        <div class={settingsFeedbackClassName(message)}>
          {message.title ? (
            <strong class="settings-feedback__title">{message.title}</strong>
          ) : null}
          <span class="settings-feedback__body">{message.body}</span>
          {message.detail ? (
            <span class="settings-feedback__detail">{message.detail}</span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function ConfirmationDialog(props: {
  bridge: UiShellChromeActionBridge;
  model: UiConfirmationDialogModel;
}) {
  const { bridge, model } = props;
  const confirmButtonRef = useRef<HTMLButtonElement | null>(null);

  useSignalEffect(() => {
    if (model.messageText) {
      confirmButtonRef.current?.focus();
    }
  });

  return (
    <div class="app-modal-layer">
      <div
        class="app-modal-backdrop"
        aria-hidden="true"
        onClick={() => bridge.current.cancelConfirmation()}
      />
      <div
        class="panel card confirmation-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirmationDialogTitle"
        aria-describedby="confirmationDialogMessage"
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            bridge.current.cancelConfirmation();
          }
        }}
      >
        <div class="confirmation-dialog__body">
          <strong id="confirmationDialogTitle" class="confirmation-dialog__title">
            {model.titleText}
          </strong>
          <p id="confirmationDialogMessage" class="confirmation-dialog__message">
            {model.messageText}
          </p>
        </div>
        <div class="confirmation-dialog__actions">
          <button
            type="button"
            class="btn"
            onClick={() => bridge.current.cancelConfirmation()}
          >
            {model.cancelButtonText}
          </button>
          <button
            type="button"
            class="btn btn--danger"
            onClick={() => bridge.current.confirmConfirmation()}
            ref={confirmButtonRef}
          >
            {model.confirmButtonText}
          </button>
        </div>
      </div>
    </div>
  );
}

function DashboardViewHosts(props: {
  panelHostRefs: UiPanelHostRefs["dashboard"];
}) {
  const { panelHostRefs } = props;
  return (
    <div class="dashboard-grid">
      <div
        id="liveOverviewRoot"
        ref={panelHostRefs.liveOverview}
        class="panel card dashboard-grid__overview"
      ></div>
      <div
        id="spectrumPanelRoot"
        ref={panelHostRefs.spectrum}
        class="panel card dashboard-grid__main"
      ></div>
      <div
        id="loggingPanelRoot"
        ref={panelHostRefs.logging}
        class="panel card dashboard-grid__controls"
      ></div>
    </div>
  );
}

function HistoryViewHosts(props: {
  hostRef: UiPanelHostRefs["history"];
}) {
  return <div id="historyPanelRoot" ref={props.hostRef} class="panel card"></div>;
}

function SettingsViewHosts(props: {
  hostRef: UiPanelHostRefs["settingsShell"];
}) {
  return <div id="settingsShellRoot" ref={props.hostRef}></div>;
}

function ShellViewSection(props: ShellViewSectionProps) {
  const { activeViewId, ariaLabelledBy, children, viewId } = props;
  return (
    <section
      id={viewId}
      class="view"
      role="tabpanel"
      aria-labelledby={ariaLabelledBy}
      hidden={activeViewId !== viewId}
    >
      {children}
    </section>
  );
}

function DocumentLanguageSync(props: {
  preferencesModel: ReadonlySignal<UiShellChromePreferencesModel>;
}) {
  const { preferencesModel } = props;

  useSignalEffect(() => {
    const lang = preferencesModel.value.selectedLanguage;
    const documentElement = globalThis.document?.documentElement;
    if (documentElement) documentElement.lang = lang;
  });

  return null;
}

function ShellChromeFrame(props: {
  children: ComponentChildren;
  statusModel: ReadonlySignal<UiShellChromeStatusModel>;
}) {
  const { children, statusModel } = props;
  const connectionState = useComputed(() => statusModel.value.connectionState);

  return (
    <div
      class="wrap"
      data-connection-state={connectionState}
    >
      {children}
    </div>
  );
}

function ShellNavigation(props: {
  bridge: UiShellChromeActionBridge;
  navigationModel: ReadonlySignal<UiShellChromeNavigationModel>;
}) {
  const { bridge, navigationModel } = props;
  const model = navigationModel.value;
  const menuButtonRefs = useRef<(HTMLButtonElement | null)[]>([]);

  function activateView(viewId: string): void {
    bridge.current.activateView(viewId);
  }

  function focusMenuButton(nextIndex: number): void {
    menuButtonRefs.current[normalizeMenuIndex(nextIndex)]?.focus();
  }

  function handleMenuKeyDown(
    index: number,
    event: JSX.TargetedKeyboardEvent<HTMLButtonElement>,
  ): void {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      activateView(model.navItems[index].viewId);
      return;
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      const nextIndex = normalizeMenuIndex(index + 1);
      activateView(model.navItems[nextIndex].viewId);
      focusMenuButton(nextIndex);
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      const nextIndex = normalizeMenuIndex(index - 1);
      activateView(model.navItems[nextIndex].viewId);
      focusMenuButton(nextIndex);
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      activateView(model.navItems[0].viewId);
      focusMenuButton(0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      const nextIndex = model.navItems.length - 1;
      activateView(model.navItems[nextIndex].viewId);
      focusMenuButton(nextIndex);
    }
  }

  return (
    <div class="site-header__nav">
      <h1 class="title" aria-label="VibeSensor">
        <picture class="brandmark">
          <source
            srcSet="/branding/vibesensor-logo-header-dark.svg"
            media="(prefers-color-scheme: dark)"
          />
          <img
            src="/branding/vibesensor-logo-header-light.svg"
            alt="VibeSensor"
            width="222"
            height="46"
          />
        </picture>
      </h1>
      <nav class="menu" aria-label="Primary" role="tablist">
        {model.navItems.map((item, index) => {
          const isActive = item.viewId === model.activeViewId;
          return (
            <button
              key={item.viewId}
              ref={(el) => { menuButtonRefs.current[index] = el; }}
              type="button"
              class={isActive ? "menu-btn active" : "menu-btn"}
              data-view={item.viewId}
              id={item.tabId}
              role="tab"
              aria-controls={item.viewId}
              aria-selected={isActive ? "true" : "false"}
              tabIndex={isActive ? 0 : -1}
              onClick={() => activateView(item.viewId)}
              onKeyDown={(event) => handleMenuKeyDown(index, event)}
            >
              <span>{item.labelText}</span>
            </button>
          );
        })}
      </nav>
    </div>
  );
}

function ShellPreferences(props: {
  bridge: UiShellChromeActionBridge;
  preferencesModel: ReadonlySignal<UiShellChromePreferencesModel>;
}) {
  const { bridge, preferencesModel } = props;
  const model = preferencesModel.value;

  return (
    <div class="site-header__preferences">
      <label class="header-select" htmlFor="speedUnitSelect">
        <span class="mini-label">{model.speedUnitLabelText}</span>
        <select
          id="speedUnitSelect"
          class="unit-picker"
          aria-label={model.speedUnitLabelText}
          aria-describedby={model.speedUnitFeedback ? "speedUnitFeedback" : undefined}
          aria-invalid={model.speedUnitFeedback?.tone === "error" ? "true" : undefined}
          value={model.selectedSpeedUnit}
          onChange={(event) => {
            void bridge.current.saveSpeedUnit(event.currentTarget.value);
          }}
        >
          {SPEED_UNIT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {model.speedUnitOptionLabels[option.value] ?? option.fallbackLabel}
            </option>
          ))}
        </select>
        <SettingsFeedbackSlot
          id="speedUnitFeedback"
          message={model.speedUnitFeedback}
        />
      </label>
      <label class="header-select" htmlFor="languageSelect">
        <span class="mini-label">{model.languageLabelText}</span>
        <select
          id="languageSelect"
          class="lang-picker"
          aria-label={model.languageLabelText}
          aria-describedby={model.languageFeedback ? "languageFeedback" : undefined}
          aria-invalid={model.languageFeedback?.tone === "error" ? "true" : undefined}
          value={model.selectedLanguage}
          onChange={(event) => {
            void bridge.current.saveLanguage(event.currentTarget.value);
          }}
        >
          {LANGUAGE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <SettingsFeedbackSlot
          id="languageFeedback"
          message={model.languageFeedback}
        />
      </label>
    </div>
  );
}

function ShellStatus(props: {
  navigationModel: ReadonlySignal<UiShellChromeNavigationModel>;
  statusModel: ReadonlySignal<UiShellChromeStatusModel>;
}) {
  const { navigationModel, statusModel } = props;
  const navigation = navigationModel.value;
  const status = statusModel.value;
  const statusHidden = navigation.activeViewId === "dashboardView";

  return (
    <div class="site-header__status" hidden={statusHidden}>
      <div class="site-header__status-pills">
        <div
          id="linkState"
          class="pill"
          data-variant={status.wsLinkState.variant}
          aria-live="polite"
        >
          {status.wsLinkState.text}
        </div>
        <div
          id="shellLiveStatus"
          class="pill"
          data-variant={status.shellLiveStatus.variant}
          aria-live="polite"
        >
          {status.shellLiveStatus.text}
        </div>
      </div>
    </div>
  );
}

function AppErrorBanner(props: {
  dialogModel: ReadonlySignal<UiShellChromeDialogModel>;
}) {
  const banner = props.dialogModel.value.appErrorBanner;
  const appErrorVariant = banner.variant ?? undefined;

  return (
    <div
      id="appErrorBanner"
      class="connection-banner app-error-banner"
      hidden={banner.hidden}
      data-variant={appErrorVariant}
      aria-live="assertive"
      role="alert"
    >
      {banner.text}
    </div>
  );
}

function ShellViewHostsContainer(props: {
  navigationModel: ReadonlySignal<UiShellChromeNavigationModel>;
  panelHostRefs: UiPanelHostRefs;
}) {
  const { navigationModel, panelHostRefs } = props;
  const activeViewId = navigationModel.value.activeViewId;

  return (
    <>
      <ShellViewSection
        activeViewId={activeViewId}
        ariaLabelledBy="tab-dashboard"
        viewId="dashboardView"
      >
        <DashboardViewHosts panelHostRefs={panelHostRefs.dashboard} />
      </ShellViewSection>

      <ShellViewSection
        activeViewId={activeViewId}
        ariaLabelledBy="tab-history"
        viewId="historyView"
      >
        <HistoryViewHosts hostRef={panelHostRefs.history} />
      </ShellViewSection>

      <ShellViewSection
        activeViewId={activeViewId}
        ariaLabelledBy="tab-settings"
        viewId="settingsView"
      >
        <SettingsViewHosts hostRef={panelHostRefs.settingsShell} />
      </ShellViewSection>
    </>
  );
}

function ConfirmationDialogLayer(props: {
  bridge: UiShellChromeActionBridge;
  dialogModel: ReadonlySignal<UiShellChromeDialogModel>;
}) {
  const { bridge, dialogModel } = props;
  const confirmationDialog = dialogModel.value.confirmationDialog;
  return confirmationDialog
    ? <ConfirmationDialog bridge={bridge} model={confirmationDialog} />
    : null;
}

function UiShellChrome(props: UiShellChromeProps) {
  const {
    bridge,
    dialogModel,
    navigationModel,
    panelHostRefs,
    preferencesModel,
    statusModel,
  } = props;

  return (
    <ShellChromeFrame statusModel={statusModel}>
      <DocumentLanguageSync preferencesModel={preferencesModel} />
      <header class="site-header">
        <div class="site-header__main">
          <ShellNavigation bridge={bridge} navigationModel={navigationModel} />
          <ShellPreferences bridge={bridge} preferencesModel={preferencesModel} />
        </div>
        <ShellStatus navigationModel={navigationModel} statusModel={statusModel} />
      </header>

      <AppErrorBanner dialogModel={dialogModel} />
      <ShellViewHostsContainer navigationModel={navigationModel} panelHostRefs={panelHostRefs} />
      <ConfirmationDialogLayer bridge={bridge} dialogModel={dialogModel} />
    </ShellChromeFrame>
  );
}

export function createUiShellChromeActionBridge(): UiShellChromeActionBridge {
  const current: UiShellChromeActions = {
    activateView: noop,
    cancelConfirmation: noop,
    confirmConfirmation: noop,
    saveLanguage: noop,
    saveSpeedUnit: noop,
  };
  return {
    current,
    attach(actions: UiShellChromeActions): void {
      current.activateView = actions.activateView;
      current.cancelConfirmation = actions.cancelConfirmation;
      current.confirmConfirmation = actions.confirmConfirmation;
      current.saveLanguage = actions.saveLanguage;
      current.saveSpeedUnit = actions.saveSpeedUnit;
    },
  };
}

export function getUiShellChromeHost(): HTMLElement {
  const host = globalThis.document?.getElementById(SHELL_CHROME_HOST_ID);
  if (host) {
    return host as HTMLElement;
  }
  throw new Error(`${SHELL_OWNER} requires #${SHELL_CHROME_HOST_ID}`);
}

export function mountUiShellChrome(
  host: HTMLElement,
  bridge: UiShellChromeActionBridge,
): UiShellChromeView & { panelHosts: UiPanelHostRegistry } {
  const dialogModel = signal<UiShellChromeDialogModel>(DEFAULT_DIALOG_MODEL);
  const navigationModel = signal<UiShellChromeNavigationModel>(DEFAULT_NAVIGATION_MODEL);
  const panelHostRefs = createUiPanelHostRefs();
  const preferencesModel = signal<UiShellChromePreferencesModel>(DEFAULT_PREFERENCES_MODEL);
  const statusModel = signal<UiShellChromeStatusModel>(DEFAULT_STATUS_MODEL);
  render(
    <UiShellChrome
      bridge={bridge}
      dialogModel={dialogModel}
      navigationModel={navigationModel}
      panelHostRefs={panelHostRefs}
      preferencesModel={preferencesModel}
      statusModel={statusModel}
    />,
    host,
  );
  const panelHosts = resolveUiPanelHosts(panelHostRefs);

  return {
    panelHosts,
    setDialogModel(nextModel) {
      dialogModel.value = nextModel;
    },
    setNavigationModel(nextModel) {
      navigationModel.value = nextModel;
    },
    setPreferencesModel(nextModel) {
      preferencesModel.value = nextModel;
    },
    setStatusModel(nextModel) {
      statusModel.value = nextModel;
    },
  };
}

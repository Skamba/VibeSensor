import { render, type ComponentChildren, type JSX } from "preact";
import { useRef } from "preact/hooks";

import {
  createUiPanelHostRefs,
  resolveUiPanelHosts,
  type UiPanelHostRefs,
  type UiPanelHostRegistry,
} from "../ui_panel_host_registry";
import {
  handleTabListKeyboardNavigation,
  normalizeTabListIndex,
} from "../dom/tab_list_keyboard_navigation";
import {
  useComputed,
  useSignalProperties,
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

const SHELL_NAVIGATION_MODEL_KEYS = ["activeViewId", "navItems"] as const;
const SHELL_ACTIVE_VIEW_KEY = ["activeViewId"] as const;
const SHELL_PREFERENCES_MODEL_KEYS = [
  "languageFeedback",
  "languageLabelText",
  "selectedLanguage",
  "selectedSpeedUnit",
  "speedUnitFeedback",
  "speedUnitLabelText",
  "speedUnitOptionLabels",
] as const;
const SHELL_STATUS_MODEL_KEYS = ["shellLiveStatus", "wsLinkState"] as const;
const SHELL_DIALOG_MODEL_KEYS = ["appErrorBanner"] as const;

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
  activeViewId: ReadonlySignal<string>;
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

function SettingsFeedbackSlot(props: {
  id: string;
  message: ReadonlySignal<SettingsFeedbackMessage | null>;
}) {
  const { id, message } = props;
  const ariaLive = useComputed(() => {
    const nextMessage = message.value;
    return nextMessage ? (nextMessage.tone === "error" ? "assertive" : "polite") : undefined;
  });
  const hidden = useComputed(() => !message.value);
  return (
    <div
      id={id}
      class="settings-feedback-slot settings-feedback-slot--compact"
      hidden={hidden}
      aria-live={ariaLive}
    >
      {message.value ? (
        <div class={settingsFeedbackClassName(message.value)}>
          {message.value.title ? (
            <strong class="settings-feedback__title">{message.value.title}</strong>
          ) : null}
          <span class="settings-feedback__body">{message.value.body}</span>
          {message.value.detail ? (
            <span class="settings-feedback__detail">{message.value.detail}</span>
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
  const hidden = useComputed(() => activeViewId.value !== viewId);
  return (
    <section
      id={viewId}
      class="view"
      role="tabpanel"
      aria-labelledby={ariaLabelledBy}
      hidden={hidden}
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
  const { activeViewId, navItems } = useSignalProperties(
    navigationModel,
    SHELL_NAVIGATION_MODEL_KEYS,
  );
  const menuButtonRefs = useRef<(HTMLButtonElement | null)[]>([]);

  function activateView(viewId: string): void {
    bridge.current.activateView(viewId);
  }

  function focusMenuButton(nextIndex: number): void {
    menuButtonRefs.current[normalizeTabListIndex(nextIndex, navItems.value.length)]?.focus();
  }

  function handleMenuKeyDown(
    index: number,
    event: JSX.TargetedKeyboardEvent<HTMLButtonElement>,
  ): void {
    handleTabListKeyboardNavigation({
      count: navItems.value.length,
      event,
      focusTabAt: focusMenuButton,
      getTabIdAt: (nextIndex) => navItems.value[nextIndex].viewId,
      index,
      onActivateTab: activateView,
    });
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
        {navItems.value.map((item, index) => (
          <ShellNavigationTabButton
            key={item.viewId}
            activeViewId={activeViewId}
            index={index}
            item={item}
            onActivateView={activateView}
            onKeyDown={handleMenuKeyDown}
            onRef={(el) => { menuButtonRefs.current[index] = el; }}
          />
        ))}
      </nav>
    </div>
  );
}

function ShellNavigationTabButton(props: {
  activeViewId: ReadonlySignal<string>;
  index: number;
  item: UiShellChromeNavItemModel;
  onActivateView(viewId: string): void;
  onKeyDown(index: number, event: JSX.TargetedKeyboardEvent<HTMLButtonElement>): void;
  onRef(el: HTMLButtonElement | null): void;
}) {
  const { index, item, onActivateView } = props;
  const isActive = useComputed(() => item.viewId === props.activeViewId.value);
  const buttonClass = useComputed(() => isActive.value ? "menu-btn active" : "menu-btn");
  const ariaSelected = useComputed(() => isActive.value ? "true" : "false");
  const tabIndex = useComputed(() => isActive.value ? 0 : -1);

  return (
    <button
      ref={props.onRef}
      type="button"
      class={buttonClass}
      data-view={item.viewId}
      id={item.tabId}
      role="tab"
      aria-controls={item.viewId}
      aria-selected={ariaSelected}
      tabIndex={tabIndex}
      onClick={() => onActivateView(item.viewId)}
      onKeyDown={(event) => props.onKeyDown(index, event)}
    >
      <span>{item.labelText}</span>
    </button>
  );
}

function ShellPreferences(props: {
  bridge: UiShellChromeActionBridge;
  preferencesModel: ReadonlySignal<UiShellChromePreferencesModel>;
}) {
  const { bridge, preferencesModel } = props;
  const {
    languageFeedback,
    languageLabelText,
    selectedLanguage,
    selectedSpeedUnit,
    speedUnitFeedback,
    speedUnitLabelText,
    speedUnitOptionLabels,
  } = useSignalProperties(preferencesModel, SHELL_PREFERENCES_MODEL_KEYS);
  const speedUnitAriaDescribedBy = useComputed(() =>
    speedUnitFeedback.value ? "speedUnitFeedback" : undefined
  );
  const speedUnitAriaInvalid = useComputed(() =>
    speedUnitFeedback.value?.tone === "error" ? "true" : undefined
  );
  const languageAriaDescribedBy = useComputed(() =>
    languageFeedback.value ? "languageFeedback" : undefined
  );
  const languageAriaInvalid = useComputed(() =>
    languageFeedback.value?.tone === "error" ? "true" : undefined
  );

  return (
    <div class="site-header__preferences">
      <label class="header-select" htmlFor="speedUnitSelect">
        <span class="mini-label">{speedUnitLabelText}</span>
        <select
          id="speedUnitSelect"
          class="unit-picker"
          aria-label={speedUnitLabelText}
          aria-describedby={speedUnitAriaDescribedBy}
          aria-invalid={speedUnitAriaInvalid}
          value={selectedSpeedUnit}
          onChange={(event) => {
            void bridge.current.saveSpeedUnit(event.currentTarget.value);
          }}
        >
          {SPEED_UNIT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {speedUnitOptionLabels.value[option.value] ?? option.fallbackLabel}
            </option>
          ))}
        </select>
        <SettingsFeedbackSlot
          id="speedUnitFeedback"
          message={speedUnitFeedback}
        />
      </label>
      <label class="header-select" htmlFor="languageSelect">
        <span class="mini-label">{languageLabelText}</span>
        <select
          id="languageSelect"
          class="lang-picker"
          aria-label={languageLabelText}
          aria-describedby={languageAriaDescribedBy}
          aria-invalid={languageAriaInvalid}
          value={selectedLanguage}
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
          message={languageFeedback}
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
  const { activeViewId } = useSignalProperties(navigationModel, SHELL_ACTIVE_VIEW_KEY);
  const { shellLiveStatus, wsLinkState } = useSignalProperties(statusModel, SHELL_STATUS_MODEL_KEYS);
  const statusHidden = useComputed(() => activeViewId.value === "dashboardView");

  return (
    <div class="site-header__status" hidden={statusHidden}>
      <div class="site-header__status-pills">
        <ShellStatusPill id="linkState" model={wsLinkState} />
        <ShellStatusPill id="shellLiveStatus" model={shellLiveStatus} />
      </div>
    </div>
  );
}

function ShellStatusPill(props: {
  id: string;
  model: ReadonlySignal<UiShellBadgeModel>;
}) {
  const variant = useComputed(() => props.model.value.variant);
  const text = useComputed(() => props.model.value.text);

  return (
    <div
      id={props.id}
      class="pill"
      data-variant={variant}
      aria-live="polite"
    >
      {text}
    </div>
  );
}

function AppErrorBanner(props: {
  dialogModel: ReadonlySignal<UiShellChromeDialogModel>;
}) {
  const { appErrorBanner } = useSignalProperties(props.dialogModel, SHELL_DIALOG_MODEL_KEYS);
  const appErrorHidden = useComputed(() => appErrorBanner.value.hidden);
  const appErrorVariant = useComputed(() => appErrorBanner.value.variant ?? undefined);
  const appErrorText = useComputed(() => appErrorBanner.value.text);

  return (
    <div
      id="appErrorBanner"
      class="connection-banner app-error-banner"
      hidden={appErrorHidden}
      data-variant={appErrorVariant}
      aria-live="assertive"
      role="alert"
    >
      {appErrorText}
    </div>
  );
}

function ShellViewHostsContainer(props: {
  navigationModel: ReadonlySignal<UiShellChromeNavigationModel>;
  panelHostRefs: UiPanelHostRefs;
}) {
  const { navigationModel, panelHostRefs } = props;
  const { activeViewId } = useSignalProperties(navigationModel, SHELL_ACTIVE_VIEW_KEY);

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

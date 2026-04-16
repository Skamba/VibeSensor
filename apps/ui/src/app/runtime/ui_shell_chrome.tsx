import { render, type ComponentChildren, type JSX } from "preact";
import { useEffect, useRef } from "preact/hooks";

import { requiredById } from "../dom/dom_query";
import {
  signal,
  useComputed,
  type ReadonlySignal,
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

export interface UiShellChromeRenderModel {
  activeViewId: string;
  appErrorBanner: UiShellErrorBannerModel;
  confirmationDialog: UiConfirmationDialogModel | null;
  languageFeedback: SettingsFeedbackMessage | null;
  languageLabelText: string;
  navItems: readonly UiShellChromeNavItemModel[];
  selectedLanguage: string;
  selectedSpeedUnit: string;
  shellLiveStatus: UiShellBadgeModel;
  speedUnitFeedback: SettingsFeedbackMessage | null;
  speedUnitLabelText: string;
  speedUnitOptionLabels: Record<string, string>;
  wsLinkState: UiShellBadgeModel;
}

export interface UiShellChromeView {
  setModel(model: UiShellChromeRenderModel): void;
}

type UiShellChromeProps = {
  bridge: UiShellChromeActionBridge;
  model: ReadonlySignal<UiShellChromeRenderModel>;
};

type ShellViewSectionProps = {
  activeViewId: string;
  ariaLabelledBy: string;
  children: ComponentChildren;
  viewId: string;
};

const DEFAULT_SHELL_CHROME_MODEL: UiShellChromeRenderModel = {
  activeViewId: "dashboardView",
  appErrorBanner: {
    hidden: true,
    text: "",
    variant: null,
  },
  confirmationDialog: null,
  languageFeedback: null,
  languageLabelText: "Language",
  navItems: SHELL_NAV_ITEMS.map((item) => ({
    labelText: item.fallbackLabel,
    tabId: item.tabId,
    viewId: item.viewId,
  })),
  selectedLanguage: "en",
  selectedSpeedUnit: "kmh",
  shellLiveStatus: {
    text: "No live signal",
    variant: "muted",
  },
  speedUnitFeedback: null,
  speedUnitLabelText: "Unit",
  speedUnitOptionLabels: {
    kmh: "km/h",
    mps: "m/s",
  },
  wsLinkState: {
    text: "Connecting...",
    variant: "muted",
  },
};

function noop(): void {
  return;
}

function normalizeMenuIndex(index: number): number {
  return ((index % SHELL_NAV_ITEMS.length) + SHELL_NAV_ITEMS.length) % SHELL_NAV_ITEMS.length;
}

function focusMenuButton(
  event: JSX.TargetedKeyboardEvent<HTMLButtonElement>,
  nextIndex: number,
): void {
  const menu = event.currentTarget.closest(".menu");
  if (!(menu instanceof HTMLElement)) {
    return;
  }
  const buttons = Array.from(menu.querySelectorAll<HTMLButtonElement>(".menu-btn"));
  buttons[normalizeMenuIndex(nextIndex)]?.focus();
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

  useEffect(() => {
    confirmButtonRef.current?.focus();
  }, [model.messageText]);

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

function DashboardViewHosts() {
  return (
    <div class="dashboard-grid">
      <div id="liveOverviewRoot" class="panel card dashboard-grid__overview"></div>
      <div id="spectrumPanelRoot" class="panel card dashboard-grid__main"></div>
      <div id="loggingPanelRoot" class="panel card dashboard-grid__controls"></div>
    </div>
  );
}

function HistoryViewHosts() {
  return <div id="historyPanelRoot" class="panel card"></div>;
}

function SettingsViewHosts() {
  return <div id="settingsShellRoot"></div>;
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

function UiShellChrome(props: UiShellChromeProps) {
  const { bridge } = props;
  const activeViewId = useComputed(() => props.model.value.activeViewId);
  const appErrorBanner = useComputed(() => props.model.value.appErrorBanner);
  const confirmationDialog = useComputed(() => props.model.value.confirmationDialog);
  const languageFeedback = useComputed(() => props.model.value.languageFeedback);
  const languageLabelText = useComputed(() => props.model.value.languageLabelText);
  const navItems = useComputed(() => props.model.value.navItems);
  const selectedLanguage = useComputed(() => props.model.value.selectedLanguage);
  const selectedSpeedUnit = useComputed(() => props.model.value.selectedSpeedUnit);
  const shellLiveStatus = useComputed(() => props.model.value.shellLiveStatus);
  const speedUnitFeedback = useComputed(() => props.model.value.speedUnitFeedback);
  const speedUnitLabelText = useComputed(() => props.model.value.speedUnitLabelText);
  const speedUnitOptionLabels = useComputed(() => props.model.value.speedUnitOptionLabels);
  const wsLinkState = useComputed(() => props.model.value.wsLinkState);
  const statusHidden = useComputed(() => activeViewId.value === "dashboardView");
  const appErrorHidden = useComputed(() => appErrorBanner.value.hidden);
  const appErrorVariant = useComputed(() => appErrorBanner.value.variant ?? undefined);
  const appErrorText = useComputed(() => appErrorBanner.value.text);
  const wsLinkVariant = useComputed(() => wsLinkState.value.variant);
  const wsLinkText = useComputed(() => wsLinkState.value.text);
  const shellLiveVariant = useComputed(() => shellLiveStatus.value.variant);
  const shellLiveText = useComputed(() => shellLiveStatus.value.text);

  function activateView(viewId: string): void {
    bridge.current.activateView(viewId);
  }

  function handleMenuKeyDown(
    index: number,
    event: JSX.TargetedKeyboardEvent<HTMLButtonElement>,
  ): void {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      activateView(navItems.value[index].viewId);
      return;
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      const nextIndex = normalizeMenuIndex(index + 1);
      activateView(navItems.value[nextIndex].viewId);
      focusMenuButton(event, nextIndex);
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      const nextIndex = normalizeMenuIndex(index - 1);
      activateView(navItems.value[nextIndex].viewId);
      focusMenuButton(event, nextIndex);
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      activateView(navItems.value[0].viewId);
      focusMenuButton(event, 0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      const nextIndex = navItems.value.length - 1;
      activateView(navItems.value[nextIndex].viewId);
      focusMenuButton(event, nextIndex);
    }
  }

  return (
    <div class="wrap">
      <header class="site-header">
        <div class="site-header__main">
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
              {navItems.value.map((item, index) => {
                const isActive = item.viewId === activeViewId.value;
                return (
                  <button
                    key={item.viewId}
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
          <div class="site-header__preferences">
            <label class="header-select" htmlFor="speedUnitSelect">
              <span class="mini-label">{speedUnitLabelText}</span>
              <select
                id="speedUnitSelect"
                class="unit-picker"
                aria-label={speedUnitLabelText}
                aria-describedby={speedUnitFeedback.value ? "speedUnitFeedback" : undefined}
                aria-invalid={speedUnitFeedback.value?.tone === "error" ? "true" : undefined}
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
                message={speedUnitFeedback.value}
              />
            </label>
            <label class="header-select" htmlFor="languageSelect">
              <span class="mini-label">{languageLabelText}</span>
              <select
                id="languageSelect"
                class="lang-picker"
                aria-label={languageLabelText}
                aria-describedby={languageFeedback.value ? "languageFeedback" : undefined}
                aria-invalid={languageFeedback.value?.tone === "error" ? "true" : undefined}
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
                message={languageFeedback.value}
              />
            </label>
          </div>
        </div>
        <div class="site-header__status" hidden={statusHidden}>
          <div class="site-header__status-pills">
            <div
              id="linkState"
              class="pill"
              data-variant={wsLinkVariant}
              aria-live="polite"
            >
              {wsLinkText}
            </div>
            <div
              id="shellLiveStatus"
              class="pill"
              data-variant={shellLiveVariant}
              aria-live="polite"
            >
              {shellLiveText}
            </div>
          </div>
        </div>
      </header>

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

      <ShellViewSection
        activeViewId={activeViewId.value}
        ariaLabelledBy="tab-dashboard"
        viewId="dashboardView"
      >
        <DashboardViewHosts />
      </ShellViewSection>

      <ShellViewSection
        activeViewId={activeViewId.value}
        ariaLabelledBy="tab-history"
        viewId="historyView"
      >
        <HistoryViewHosts />
      </ShellViewSection>

      <ShellViewSection
        activeViewId={activeViewId.value}
        ariaLabelledBy="tab-settings"
        viewId="settingsView"
      >
        <SettingsViewHosts />
      </ShellViewSection>

      {confirmationDialog.value
        ? <ConfirmationDialog bridge={bridge} model={confirmationDialog.value} />
        : null}
    </div>
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
  return requiredById<HTMLElement>(SHELL_CHROME_HOST_ID, SHELL_OWNER);
}

export function mountUiShellChrome(
  host: HTMLElement,
  bridge: UiShellChromeActionBridge,
): UiShellChromeView {
  const model = signal<UiShellChromeRenderModel>(DEFAULT_SHELL_CHROME_MODEL);
  render(<UiShellChrome bridge={bridge} model={model} />, host);

  return {
    setModel(nextModel) {
      model.value = nextModel;
    },
  };
}

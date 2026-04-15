import { h, type JSX } from "preact";

import { requiredById } from "../dom/dom_query";
import { signal, type ReadonlySignal } from "../ui_signals";
import {
  settingsFeedbackClassName,
  type SettingsFeedbackMessage,
} from "../views/settings_feedback";
import type { VisualVariant } from "../style_state";
import { createUiPreactMount } from "./ui_preact_mount";

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

export const LANGUAGE_OPTIONS = [
  { label: "🇺🇸 English", value: "en" },
  { label: "🇳🇱 Nederlands", value: "nl" },
] as const;

export interface UiShellChromeActions {
  activateView(viewId: string): void;
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

export interface UiShellChromeDom {
  menuButtons: HTMLButtonElement[];
}

export interface UiShellChromeView {
  readonly dom: UiShellChromeDom;
  render(model: UiShellChromeRenderModel): void;
}

type UiShellChromeProps = {
  bridge: UiShellChromeActionBridge;
  model: ReadonlySignal<UiShellChromeRenderModel>;
};

const DEFAULT_SHELL_CHROME_MODEL: UiShellChromeRenderModel = {
  activeViewId: "dashboardView",
  appErrorBanner: {
    hidden: true,
    text: "",
    variant: null,
  },
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

function UiShellChrome(props: UiShellChromeProps) {
  const { bridge } = props;
  const model = props.model.value;

  function activateView(viewId: string): void {
    bridge.current.activateView(viewId);
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
      focusMenuButton(event, nextIndex);
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      const nextIndex = normalizeMenuIndex(index - 1);
      activateView(model.navItems[nextIndex].viewId);
      focusMenuButton(event, nextIndex);
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      activateView(model.navItems[0].viewId);
      focusMenuButton(event, 0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      const nextIndex = model.navItems.length - 1;
      activateView(model.navItems[nextIndex].viewId);
      focusMenuButton(event, nextIndex);
    }
  }

  return (
    <>
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
              {model.navItems.map((item, index) => {
                const isActive = item.viewId === model.activeViewId;
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
        </div>
        <div class="site-header__status" hidden={model.activeViewId === "dashboardView"}>
          <div class="site-header__status-pills">
            <div
              id="linkState"
              class="pill"
              data-variant={model.wsLinkState.variant}
              aria-live="polite"
            >
              {model.wsLinkState.text}
            </div>
            <div
              id="shellLiveStatus"
              class="pill"
              data-variant={model.shellLiveStatus.variant}
              aria-live="polite"
            >
              {model.shellLiveStatus.text}
            </div>
          </div>
        </div>
      </header>

      <div
        id="appErrorBanner"
        class="connection-banner app-error-banner"
        hidden={model.appErrorBanner.hidden}
        data-variant={model.appErrorBanner.variant ?? undefined}
        aria-live="assertive"
        role="alert"
      >
        {model.appErrorBanner.text}
      </div>
    </>
  );
}

export function createUiShellChromeActionBridge(): UiShellChromeActionBridge {
  const current: UiShellChromeActions = {
    activateView: noop,
    saveLanguage: noop,
    saveSpeedUnit: noop,
  };
  return {
    current,
    attach(actions: UiShellChromeActions): void {
      current.activateView = actions.activateView;
      current.saveLanguage = actions.saveLanguage;
      current.saveSpeedUnit = actions.saveSpeedUnit;
    },
  };
}

export function getUiShellChromeHost(): HTMLElement {
  return requiredById<HTMLElement>(SHELL_CHROME_HOST_ID, SHELL_OWNER);
}

function createUiShellChromeDom(host: HTMLElement): UiShellChromeDom {
  return {
    menuButtons: Array.from(host.querySelectorAll<HTMLButtonElement>(".menu-btn")),
  };
}

export function mountUiShellChrome(
  host: HTMLElement,
  bridge: UiShellChromeActionBridge,
): UiShellChromeView {
  const model = signal<UiShellChromeRenderModel>(DEFAULT_SHELL_CHROME_MODEL);
  const mount = createUiPreactMount(host);
  mount.render(<UiShellChrome bridge={bridge} model={model} />);

  return {
    dom: createUiShellChromeDom(host),
    render(nextModel) {
      model.value = nextModel;
    },
  };
}

import type { JSX } from "preact";

import type { ShellState } from "../ui_app_state";
import { createUiPreactMount } from "./ui_preact_mount";

const SHELL_NAV_ITEMS = [
  {
    viewId: "dashboardView",
    tabId: "tab-dashboard",
    labelKey: "nav.live",
    fallbackLabel: "Live",
  },
  {
    viewId: "historyView",
    tabId: "tab-history",
    labelKey: "nav.history",
    fallbackLabel: "History",
  },
  {
    viewId: "settingsView",
    tabId: "tab-settings",
    labelKey: "nav.settings",
    fallbackLabel: "Settings",
  },
] as const;

const SPEED_UNIT_OPTIONS = [
  { value: "kmh", labelKey: "speed.unit.kmh", fallbackLabel: "km/h" },
  { value: "mps", labelKey: "speed.unit.mps", fallbackLabel: "m/s" },
] as const;

const LANGUAGE_OPTIONS = [
  { value: "en", label: "🇺🇸 English" },
  { value: "nl", label: "🇳🇱 Nederlands" },
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

type UiShellChromeProps = {
  bridge: UiShellChromeActionBridge;
  initialShellState: Pick<ShellState, "activeViewId" | "lang" | "speedUnit">;
};

function noop(): void {
  return;
}

function normalizeMenuIndex(index: number): number {
  return ((index % SHELL_NAV_ITEMS.length) + SHELL_NAV_ITEMS.length) % SHELL_NAV_ITEMS.length;
}

function focusMenuButton(event: JSX.TargetedKeyboardEvent<HTMLButtonElement>, nextIndex: number): void {
  const menu = event.currentTarget.closest(".menu");
  if (!(menu instanceof HTMLElement)) {
    return;
  }
  const buttons = Array.from(menu.querySelectorAll<HTMLButtonElement>(".menu-btn"));
  buttons[normalizeMenuIndex(nextIndex)]?.focus();
}

function UiShellChrome(props: UiShellChromeProps) {
  const { bridge, initialShellState } = props;

  function activateView(viewId: string): void {
    bridge.current.activateView(viewId);
  }

  function handleMenuKeyDown(
    index: number,
    event: JSX.TargetedKeyboardEvent<HTMLButtonElement>,
  ): void {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      activateView(SHELL_NAV_ITEMS[index].viewId);
      return;
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      const nextIndex = normalizeMenuIndex(index + 1);
      activateView(SHELL_NAV_ITEMS[nextIndex].viewId);
      focusMenuButton(event, nextIndex);
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      const nextIndex = normalizeMenuIndex(index - 1);
      activateView(SHELL_NAV_ITEMS[nextIndex].viewId);
      focusMenuButton(event, nextIndex);
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      activateView(SHELL_NAV_ITEMS[0].viewId);
      focusMenuButton(event, 0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      const nextIndex = SHELL_NAV_ITEMS.length - 1;
      activateView(SHELL_NAV_ITEMS[nextIndex].viewId);
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
              {SHELL_NAV_ITEMS.map((item, index) => {
                const isActive = item.viewId === initialShellState.activeViewId;
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
                    <span data-i18n={item.labelKey}>{item.fallbackLabel}</span>
                  </button>
                );
              })}
            </nav>
          </div>
          <div class="site-header__preferences">
            <label class="header-select" htmlFor="speedUnitSelect">
              <span class="mini-label" data-i18n="speed.unit">
                Unit
              </span>
              <select
                id="speedUnitSelect"
                class="unit-picker"
                aria-label="Speed unit"
                defaultValue={initialShellState.speedUnit}
                onChange={(event) => {
                  void bridge.current.saveSpeedUnit(event.currentTarget.value);
                }}
              >
                {SPEED_UNIT_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value} data-i18n={option.labelKey}>
                    {option.fallbackLabel}
                  </option>
                ))}
              </select>
              <div
                id="speedUnitFeedback"
                class="settings-feedback-slot settings-feedback-slot--compact"
                hidden
              />
            </label>
            <label class="header-select" htmlFor="languageSelect">
              <span class="mini-label" data-i18n="settings.language">
                Language
              </span>
              <select
                id="languageSelect"
                class="lang-picker"
                aria-label="Language"
                defaultValue={initialShellState.lang}
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
              <div
                id="languageFeedback"
                class="settings-feedback-slot settings-feedback-slot--compact"
                hidden
              />
            </label>
          </div>
        </div>
        <div class="site-header__status">
          <div class="site-header__status-pills">
            <div id="linkState" class="pill pill--muted" aria-live="polite">
              Connecting...
            </div>
            <div id="shellLiveStatus" class="pill pill--muted" aria-live="polite">
              No live signal
            </div>
          </div>
        </div>
      </header>

      <div
        id="appErrorBanner"
        class="connection-banner app-error-banner"
        hidden
        aria-live="assertive"
        role="alert"
      />
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

export function mountUiShellChrome(
  host: HTMLElement,
  bridge: UiShellChromeActionBridge,
  initialShellState: Pick<ShellState, "activeViewId" | "lang" | "speedUnit">,
): void {
  const mount = createUiPreactMount(host);
  mount.render(<UiShellChrome bridge={bridge} initialShellState={initialShellState} />);
}

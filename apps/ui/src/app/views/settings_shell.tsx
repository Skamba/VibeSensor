import type { JSX } from "preact";

import { createUiPreactMount } from "../runtime/ui_preact_mount";
import { useUiTranslation } from "../ui_i18n";
import type { ViewDisposer } from "./dom_event_bindings";

const SETTINGS_TABS = [
  {
    id: "carTab",
    labelKey: "settings.tab.car",
    fallbackLabel: "Car",
    hostId: "carsPanelRoot",
  },
  {
    id: "analysisTab",
    labelKey: "settings.tab.analysis",
    fallbackLabel: "Analysis",
    hostId: "analysisPanelRoot",
  },
  {
    id: "speedSourceTab",
    labelKey: "settings.tab.speed_source",
    fallbackLabel: "Speed Source",
    hostId: "speedSourcePanelRoot",
  },
  {
    id: "sensorsTab",
    labelKey: "settings.tab.sensors",
    fallbackLabel: "Sensors",
    hostId: "sensorsPanelRoot",
  },
  {
    id: "internetTab",
    labelKey: "settings.tab.internet",
    fallbackLabel: "Internet",
    hostId: "internetPanelRoot",
  },
  {
    id: "updateTab",
    labelKey: "settings.tab.update",
    fallbackLabel: "Update",
    hostId: "updatePanelRoot",
  },
  {
    id: "espFlashTab",
    labelKey: "settings.tab.esp_flash",
    fallbackLabel: "ESP Flash",
    hostId: "espFlashPanelRoot",
  },
] as const;

type SettingsShellTabId = (typeof SETTINGS_TABS)[number]["id"];

export interface SettingsShellDom {
  settingsTabs: HTMLButtonElement[];
}

export interface SettingsShellView {
  readonly dom: SettingsShellDom;
  activateTab(tabId: string): void;
  subscribeActiveTabChanges(listener: (tabId: string) => void): ViewDisposer;
}

type SettingsShellProps = {
  activeTabId: SettingsShellTabId;
  onActivateTab(tabId: SettingsShellTabId): void;
};

function isSettingsShellTabId(value: string): value is SettingsShellTabId {
  return SETTINGS_TABS.some((tab) => tab.id === value);
}

function normalizeSettingsTabIndex(index: number): number {
  return ((index % SETTINGS_TABS.length) + SETTINGS_TABS.length) % SETTINGS_TABS.length;
}

function focusSettingsTab(
  event: JSX.TargetedKeyboardEvent<HTMLButtonElement>,
  nextIndex: number,
): void {
  const nav = event.currentTarget.closest(".settings-tabs");
  if (!(nav instanceof HTMLElement)) {
    return;
  }
  const buttons = Array.from(nav.querySelectorAll<HTMLButtonElement>(".settings-tab"));
  buttons[normalizeSettingsTabIndex(nextIndex)]?.focus();
}

function SettingsShell(props: SettingsShellProps) {
  const { activeTabId, onActivateTab } = props;
  const t = useUiTranslation();

  function handleTabKeyDown(
    index: number,
    event: JSX.TargetedKeyboardEvent<HTMLButtonElement>,
  ): void {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onActivateTab(SETTINGS_TABS[index].id);
      return;
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      const nextIndex = normalizeSettingsTabIndex(index + 1);
      onActivateTab(SETTINGS_TABS[nextIndex].id);
      focusSettingsTab(event, nextIndex);
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      const nextIndex = normalizeSettingsTabIndex(index - 1);
      onActivateTab(SETTINGS_TABS[nextIndex].id);
      focusSettingsTab(event, nextIndex);
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      onActivateTab(SETTINGS_TABS[0].id);
      focusSettingsTab(event, 0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      const nextIndex = SETTINGS_TABS.length - 1;
      onActivateTab(SETTINGS_TABS[nextIndex].id);
      focusSettingsTab(event, nextIndex);
    }
  }

  return (
    <>
      <nav class="settings-tabs" role="tablist">
        {SETTINGS_TABS.map((tab, index) => {
          const isActive = tab.id === activeTabId;
          return (
            <button
              key={tab.id}
              type="button"
              class={isActive ? "settings-tab active" : "settings-tab"}
              data-settings-tab={tab.id}
              role="tab"
              aria-controls={tab.id}
              aria-selected={isActive ? "true" : "false"}
              tabIndex={isActive ? 0 : -1}
              onClick={() => onActivateTab(tab.id)}
              onKeyDown={(event) => handleTabKeyDown(index, event)}
            >
              <span data-i18n={tab.labelKey}>
                {t(tab.labelKey, tab.fallbackLabel)}
              </span>
            </button>
          );
        })}
      </nav>
      {SETTINGS_TABS.map((tab) => {
        const isActive = tab.id === activeTabId;
        return (
          <div
            key={tab.id}
            id={tab.id}
            class={isActive ? "settings-tab-panel active" : "settings-tab-panel"}
            role="tabpanel"
            hidden={!isActive}
          >
            <div id={tab.hostId} />
          </div>
        );
      })}
    </>
  );
}

function requireInHostAll<T extends HTMLElement>(
  host: HTMLElement,
  selector: string,
): T[] {
  const elements = Array.from(host.querySelectorAll<T>(selector));
  if (elements.length === 0) {
    throw new Error(`Settings shell requires ${selector}`);
  }
  return elements;
}

function createSettingsShellDom(host: HTMLElement): SettingsShellDom {
  return {
    settingsTabs: requireInHostAll<HTMLButtonElement>(host, ".settings-tab"),
  };
}

export function mountSettingsShell(host: HTMLElement): SettingsShellView {
  const mount = createUiPreactMount(host);
  let activeTabId: SettingsShellTabId = "carTab";
  const activeTabListeners = new Set<(tabId: string) => void>();

  function notifyActiveTabListeners(): void {
    for (const listener of activeTabListeners) {
      listener(activeTabId);
    }
  }

  function setActiveTab(tabId: SettingsShellTabId): void {
    if (tabId === activeTabId) {
      return;
    }
    activeTabId = tabId;
    render();
    notifyActiveTabListeners();
  }

  function render(): void {
    mount.render(
      <SettingsShell
        activeTabId={activeTabId}
        onActivateTab={(tabId) => {
          setActiveTab(tabId);
        }}
      />,
    );
  }

  render();
  const dom = createSettingsShellDom(host);

  return {
    dom,
    activateTab(tabId: string): void {
      if (!isSettingsShellTabId(tabId)) {
        return;
      }
      setActiveTab(tabId);
    },
    subscribeActiveTabChanges(listener: (tabId: string) => void): ViewDisposer {
      activeTabListeners.add(listener);
      return () => {
        activeTabListeners.delete(listener);
      };
    },
  };
}

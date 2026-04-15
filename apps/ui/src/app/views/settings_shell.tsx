import { render, type JSX } from "preact";

import { useUiTranslation } from "../ui_i18n";
import { effect, type ReadonlySignal, signal } from "../ui_signals";

type ViewDisposer = () => void;

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

export interface SettingsShellView {
  activateTab(tabId: string): void;
  subscribeActiveTabChanges(listener: (tabId: string) => void): ViewDisposer;
}

type SettingsShellProps = {
  activeTabId: ReadonlySignal<SettingsShellTabId>;
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
  const activeTabId = props.activeTabId.value;
  const { onActivateTab } = props;
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
              <span>
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

export function mountSettingsShell(host: HTMLElement): SettingsShellView {
  const activeTabId = signal<SettingsShellTabId>("carTab");

  function setActiveTab(tabId: SettingsShellTabId): void {
    if (tabId === activeTabId.value) {
      return;
    }
    activeTabId.value = tabId;
  }

  render(
    <SettingsShell
      activeTabId={activeTabId}
      onActivateTab={(tabId) => {
        setActiveTab(tabId);
      }}
    />,
    host,
  );

  return {
    activateTab(tabId: string): void {
      if (!isSettingsShellTabId(tabId)) {
        return;
      }
      setActiveTab(tabId);
    },
    subscribeActiveTabChanges(listener: (tabId: string) => void): ViewDisposer {
      let initialized = false;
      return effect(() => {
        const nextTabId = activeTabId.value;
        if (!initialized) {
          initialized = true;
          return;
        }
        listener(nextTabId);
      });
    },
  };
}

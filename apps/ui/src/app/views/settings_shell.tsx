import { render, type JSX } from "preact";

import { useUiText } from "../ui_i18n";
import {
  effect,
  useComputed,
  type ReadonlySignal,
  signal,
} from "../ui_signals";

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
  getActiveTabId(): string;
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

function SettingsShellTabButton(props: {
  activeTabId: ReadonlySignal<SettingsShellTabId>;
  index: number;
  onActivateTab(tabId: SettingsShellTabId): void;
  tab: (typeof SETTINGS_TABS)[number];
}) {
  const { index, onActivateTab, tab } = props;
  const isActive = useComputed(() => tab.id === props.activeTabId.value);
  const labelText = useUiText(tab.labelKey, tab.fallbackLabel);
  const tabClass = useComputed(() => isActive.value ? "settings-tab active" : "settings-tab");
  const ariaSelected = useComputed(() => isActive.value ? "true" : "false");
  const tabIndex = useComputed(() => isActive.value ? 0 : -1);

  function handleTabKeyDown(
    event: JSX.TargetedKeyboardEvent<HTMLButtonElement>,
  ): void {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onActivateTab(tab.id);
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
    <button
      type="button"
      class={tabClass}
      data-settings-tab={tab.id}
      role="tab"
      aria-controls={tab.id}
      aria-selected={ariaSelected}
      tabIndex={tabIndex}
      onClick={() => onActivateTab(tab.id)}
      onKeyDown={handleTabKeyDown}
    >
      <span>{labelText}</span>
    </button>
  );
}

function SettingsShellTabPanel(props: {
  activeTabId: ReadonlySignal<SettingsShellTabId>;
  tab: (typeof SETTINGS_TABS)[number];
}) {
  const isActive = useComputed(() => props.tab.id === props.activeTabId.value);
  const panelClass = useComputed(() => isActive.value ? "settings-tab-panel active" : "settings-tab-panel");
  const hidden = useComputed(() => !isActive.value);

  return (
    <div
      id={props.tab.id}
      class={panelClass}
      role="tabpanel"
      hidden={hidden}
    >
      <div id={props.tab.hostId} />
    </div>
  );
}

function SettingsShell(props: SettingsShellProps) {
  const { onActivateTab } = props;

  return (
    <>
      <nav class="settings-tabs" role="tablist">
        {SETTINGS_TABS.map((tab, index) => {
          return (
            <SettingsShellTabButton
              key={tab.id}
              activeTabId={props.activeTabId}
              index={index}
              onActivateTab={onActivateTab}
              tab={tab}
            />
          );
        })}
      </nav>
      {SETTINGS_TABS.map((tab) => (
        <SettingsShellTabPanel key={tab.id} activeTabId={props.activeTabId} tab={tab} />
      ))}
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
    getActiveTabId(): string {
      return activeTabId.value;
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

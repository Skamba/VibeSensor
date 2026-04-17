import { render, type JSX } from "preact";
import { useRef } from "preact/hooks";

import {
  handleTabListKeyboardNavigation,
  normalizeTabListIndex,
} from "../dom/tab_list_keyboard_navigation";
import {
  createUiSettingsPanelHostRefs,
  resolveUiSettingsPanelHosts,
  type UiSettingsPanelHostRefs,
  type UiSettingsPanelHostRegistry,
} from "../ui_panel_host_registry";
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
  panelHostRefs: UiSettingsPanelHostRefs;
};

function isSettingsShellTabId(value: string): value is SettingsShellTabId {
  return SETTINGS_TABS.some((tab) => tab.id === value);
}

function SettingsShellTabButton(props: {
  activeTabId: ReadonlySignal<SettingsShellTabId>;
  index: number;
  onActivateTab(tabId: SettingsShellTabId): void;
  onFocusTab(index: number): void;
  onRef(el: HTMLButtonElement | null): void;
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
    handleTabListKeyboardNavigation({
      count: SETTINGS_TABS.length,
      event,
      focusTabAt: props.onFocusTab,
      getTabIdAt: (nextIndex) => SETTINGS_TABS[nextIndex].id,
      index,
      onActivateTab,
    });
  }

  return (
    <button
      ref={props.onRef}
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
  hostRef: UiSettingsPanelHostRefs[keyof UiSettingsPanelHostRefs];
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
      <div id={props.tab.hostId} ref={props.hostRef} />
    </div>
  );
}

function SettingsShell(props: SettingsShellProps) {
  const { onActivateTab, panelHostRefs } = props;
  const tabButtonRefs = useRef<(HTMLButtonElement | null)[]>([]);

  function focusTabAtIndex(index: number): void {
    tabButtonRefs.current[normalizeTabListIndex(index, SETTINGS_TABS.length)]?.focus();
  }

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
              onFocusTab={focusTabAtIndex}
              onRef={(el) => { tabButtonRefs.current[index] = el; }}
              tab={tab}
            />
          );
        })}
      </nav>
      {SETTINGS_TABS.map((tab) => (
        <SettingsShellTabPanel
          key={tab.id}
          activeTabId={props.activeTabId}
          hostRef={getSettingsPanelHostRef(panelHostRefs, tab.id)}
          tab={tab}
        />
      ))}
    </>
  );
}

function getSettingsPanelHostRef(
  panelHostRefs: UiSettingsPanelHostRefs,
  tabId: SettingsShellTabId,
): UiSettingsPanelHostRefs[keyof UiSettingsPanelHostRefs] {
  switch (tabId) {
    case "carTab":
      return panelHostRefs.cars;
    case "analysisTab":
      return panelHostRefs.analysis;
    case "speedSourceTab":
      return panelHostRefs.speedSource;
    case "sensorsTab":
      return panelHostRefs.sensors;
    case "internetTab":
      return panelHostRefs.internet;
    case "updateTab":
      return panelHostRefs.update;
    case "espFlashTab":
      return panelHostRefs.espFlash;
  }
}

export function mountSettingsShell(
  host: HTMLElement,
): { panelHosts: UiSettingsPanelHostRegistry; view: SettingsShellView } {
  const activeTabId = signal<SettingsShellTabId>("carTab");
  const panelHostRefs = createUiSettingsPanelHostRefs();

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
      panelHostRefs={panelHostRefs}
    />,
    host,
  );
  const panelHosts = resolveUiSettingsPanelHosts(panelHostRefs);

  return {
    panelHosts,
    view: {
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
    },
  };
}

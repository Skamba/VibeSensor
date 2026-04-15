import {
  computed,
  effect,
  signal,
  type ReadonlySignal,
} from "../ui_signals";
import type { FeatureServices } from "../feature_deps_base";
import { createEspFlashFeatureWorkflow } from "./esp_flash_feature_workflow";
import { createEspFlashFeaturePresenter } from "../views/esp_flash_feature_presenter";
import type { EspFlashPanelView } from "../views/esp_flash_panel";

interface EspFlashFeaturePorts {
  getActiveSettingsTabId: () => string;
  activeViewId: ReadonlySignal<string>;
  subscribeSettingsTabChanges(listener: (tabId: string) => void): () => void;
}

export interface EspFlashFeatureDeps {
  panel: EspFlashPanelView;
  ports: EspFlashFeaturePorts;
  services: FeatureServices;
}

export interface EspFlashFeature {
  bindHandlers(): void;
  startPolling(): void;
  stopPolling(): void;
}

function isEspFlashPollingContext(viewId: string, tabId: string): boolean {
  return viewId === "settingsView" && tabId === "espFlashTab";
}

export function createEspFlashFeature(
  ctx: EspFlashFeatureDeps,
): EspFlashFeature {
  const { panel, ports, services } = ctx;
  const handlersBound = signal(false);
  const activeSettingsTabId = signal(ports.getActiveSettingsTabId());
  const pollingEnabled = computed(() =>
    handlersBound.value
    && isEspFlashPollingContext(ports.activeViewId.value, activeSettingsTabId.value)
  );
  const presenter = createEspFlashFeaturePresenter({
    panel,
    t: services.t,
  });
  const workflow = createEspFlashFeatureWorkflow({
    t: services.t,
    showError: services.showError,
    view: presenter,
    pollingEnabled,
  });

  ports.subscribeSettingsTabChanges((tabId) => {
    activeSettingsTabId.value = tabId;
  });

  let wasPollingEnabled = false;
  effect(() => {
    const enabled = pollingEnabled.value;
    if (enabled && !wasPollingEnabled) {
      void workflow.refreshPorts();
    }
    wasPollingEnabled = enabled;
  });

  function bindHandlers(): void {
    if (handlersBound.value) {
      return;
    }
    handlersBound.value = true;
    panel.bindActions({
      onStart: () => {
        void workflow.startFlash();
      },
      onCancel: () => {
        void workflow.cancelFlash();
      },
      onRefreshPorts: () => {
        void workflow.refreshPorts();
      },
      onSelectPort: (value) => {
        workflow.setSelectedPortValue(value);
      },
    });
    workflow.renderCurrentState();
  }

  return {
    bindHandlers,
    startPolling: () => workflow.startPolling(),
    stopPolling: () => workflow.stopPolling(),
  };
}

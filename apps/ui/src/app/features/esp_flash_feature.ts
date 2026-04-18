import {
  computed,
  effectOnChange,
  signal,
  type ReadonlySignal,
} from "../ui_signals";
import type { FeatureServices } from "../feature_deps_base";
import { createEspFlashFeatureWorkflow } from "./esp_flash_feature_workflow";
import { createEspFlashFeaturePresenter } from "../views/esp_flash_feature_presenter";
import type { EspFlashPanelView } from "../views/esp_flash_panel";

interface EspFlashFeaturePorts {
  activeViewId: ReadonlySignal<string>;
  activeSettingsTabId: ReadonlySignal<string>;
}

export interface EspFlashFeatureDeps {
  panel: EspFlashPanelView;
  ports: EspFlashFeaturePorts;
  services: FeatureServices;
}

export interface EspFlashFeature {
  bindHandlers(): void;
  dispose(): void;
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
  const pollingEnabled = computed(() =>
    handlersBound.value
    && isEspFlashPollingContext(ports.activeViewId.value, ports.activeSettingsTabId.value)
  );
  const workflow = createEspFlashFeatureWorkflow({
    t: services.t,
    showError: services.showError,
    pollingEnabled,
  });
  const presenter = createEspFlashFeaturePresenter({
    renderState: workflow.renderState,
    t: services.t,
  });
  panel.model.value = presenter.model;

  const disposePollingContextSync = effectOnChange(pollingEnabled, (enabled) => {
    if (enabled) {
      void workflow.refreshPorts();
    }
  });

  function bindHandlers(): void {
    if (handlersBound.value) {
      return;
    }
    handlersBound.value = true;
    panel.actions.value = {
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
    };
  }

  return {
    bindHandlers,
    dispose(): void {
      disposePollingContextSync();
      workflow.dispose();
    },
    startPolling: () => workflow.startPolling(),
    stopPolling: () => workflow.stopPolling(),
  };
}

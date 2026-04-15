import type { FeatureServices } from "../feature_deps_base";
import { createEspFlashFeatureWorkflow } from "./esp_flash_feature_workflow";
import { createEspFlashFeaturePresenter } from "../views/esp_flash_feature_presenter";
import type { EspFlashPanelView } from "../views/esp_flash_panel";

export interface EspFlashFeatureDeps {
  panel: EspFlashPanelView;
  services: FeatureServices;
}

export interface EspFlashFeature {
  bindHandlers(): void;
  startPolling(): void;
  stopPolling(): void;
}

export function createEspFlashFeature(
  ctx: EspFlashFeatureDeps,
): EspFlashFeature {
  const { panel, services } = ctx;
  const presenter = createEspFlashFeaturePresenter({
    panel,
    t: services.t,
  });
  const workflow = createEspFlashFeatureWorkflow({
    t: services.t,
    showError: services.showError,
    view: presenter,
  });
  let handlersBound = false;

  function bindHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
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

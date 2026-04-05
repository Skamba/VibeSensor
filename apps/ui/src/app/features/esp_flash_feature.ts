import type { UiEspFlashDom } from "../dom/esp_flash_dom";
import type { FeatureDepsBase } from "../feature_deps_base";
import { createEspFlashFeatureWorkflow } from "./esp_flash_feature_workflow";
import { bindEspFlashFeatureInteractions } from "../views/esp_flash_feature_bindings";
import { createEspFlashFeaturePresenter } from "../views/esp_flash_feature_presenter";

export interface EspFlashFeatureDeps extends FeatureDepsBase {
  dom: UiEspFlashDom;
}

export interface EspFlashFeature {
  bindHandlers(): void;
  startPolling(): void;
  stopPolling(): void;
}

export function createEspFlashFeature(ctx: EspFlashFeatureDeps): EspFlashFeature {
  const presenter = createEspFlashFeaturePresenter({
    dom: ctx.dom,
    t: ctx.t,
    escapeHtml: ctx.escapeHtml,
  });
  const workflow = createEspFlashFeatureWorkflow({
    t: ctx.t,
    showError: ctx.showError,
    view: presenter,
  });
  let handlersBound = false;

  function bindHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    bindEspFlashFeatureInteractions(ctx.dom, {
      onAction(action) {
        switch (action.type) {
          case "start":
            void workflow.startFlash();
            return;
          case "cancel":
            void workflow.cancelFlash();
            return;
          case "refresh-ports":
            void workflow.refreshPorts();
            return;
          case "select-port":
            workflow.setSelectedPortValue(action.value);
        }
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

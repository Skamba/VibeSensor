import type { FeatureDepsBase } from "../feature_deps_base";
import { createUpdateFeatureWorkflow } from "./update_feature_workflow";
import { createUpdateFeaturePresenter } from "../views/update_feature_presenter";
import type { InternetPanelView } from "../views/internet_panel";
import type { UpdatePanelView } from "../views/update_panel";

export interface UpdateFeatureDeps extends FeatureDepsBase {
  panel: UpdatePanelView;
  internetPanel: InternetPanelView;
}

export interface UpdateFeature {
  bindUpdateHandlers(): void;
  startPolling(): void;
  stopPolling(): void;
}

export function createUpdateFeature(ctx: UpdateFeatureDeps): UpdateFeature {
  const presenter = createUpdateFeaturePresenter({
    dom: ctx.panel.dom,
    internetDom: ctx.internetPanel.dom,
    t: ctx.t,
    escapeHtml: ctx.escapeHtml,
  });
  const workflow = createUpdateFeatureWorkflow({
    t: ctx.t,
    showError: ctx.showError,
    view: presenter,
  });
  let handlersBound = false;

  function bindUpdateHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    ctx.panel.dom.updateStartBtn.addEventListener("click", () => {
      workflow.renderCurrentState();
      void workflow.startUpdate(
        presenter.readStartIntent(workflow.getRenderState()),
      );
    });
    ctx.panel.dom.updateCancelBtn.addEventListener("click", () => {
      void workflow.cancelUpdate();
    });
    ctx.internetPanel.dom.updateTogglePasswordBtn?.addEventListener(
      "click",
      () => {
        presenter.togglePassword();
      },
    );
    ctx.internetPanel.dom.updateTransportWifiRadio?.addEventListener(
      "change",
      () => {
        workflow.renderCurrentState();
      },
    );
    ctx.internetPanel.dom.updateTransportUsbRadio?.addEventListener(
      "change",
      () => {
        workflow.renderCurrentState();
      },
    );
    ctx.internetPanel.dom.updateSsidInput?.addEventListener("input", () => {
      workflow.renderCurrentState();
    });
    workflow.renderCurrentState();
  }

  return {
    bindUpdateHandlers,
    startPolling: () => workflow.startPolling(),
    stopPolling: () => workflow.stopPolling(),
  };
}

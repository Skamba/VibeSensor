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
    panel: ctx.panel,
    internetPanel: ctx.internetPanel,
    t: ctx.t,
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
    ctx.panel.bindActions({
      onStart: () => {
        workflow.renderCurrentState();
        void workflow.startUpdate(
          presenter.readStartIntent(workflow.getRenderState()),
        );
      },
      onCancel: () => {
        void workflow.cancelUpdate();
      },
    });
    ctx.internetPanel.bindActions({
      onTogglePassword: () => {
        presenter.togglePassword();
      },
      onTransportChange: () => {
        workflow.renderCurrentState();
      },
      onSsidInput: () => {
        workflow.renderCurrentState();
      },
    });
    workflow.renderCurrentState();
  }

  return {
    bindUpdateHandlers,
    startPolling: () => workflow.startPolling(),
    stopPolling: () => workflow.stopPolling(),
  };
}

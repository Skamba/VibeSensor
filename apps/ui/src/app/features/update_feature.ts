import type { FeatureServices } from "../feature_deps_base";
import { createUpdateFeatureWorkflow } from "./update_feature_workflow";
import { createUpdateFeaturePresenter } from "../views/update_feature_presenter";
import type { InternetPanelView } from "../views/internet_panel";
import type { UpdatePanelView } from "../views/update_panel";

interface UpdateFeaturePanels {
  update: UpdatePanelView;
  internet: InternetPanelView;
}

export interface UpdateFeatureDeps {
  panels: UpdateFeaturePanels;
  services: FeatureServices;
}

export interface UpdateFeature {
  bindUpdateHandlers(): void;
  startPolling(): void;
  stopPolling(): void;
}

export function createUpdateFeature(ctx: UpdateFeatureDeps): UpdateFeature {
  const { panels, services } = ctx;
  const presenter = createUpdateFeaturePresenter({
    panel: panels.update,
    internetPanel: panels.internet,
    t: services.t,
  });
  const workflow = createUpdateFeatureWorkflow({
    t: services.t,
    showError: services.showError,
    view: presenter,
  });
  let handlersBound = false;

  function bindUpdateHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    panels.update.bindActions({
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
    panels.internet.bindActions({
      onPasswordInput: (value) => {
        presenter.setPasswordInput(value);
      },
      onTogglePassword: () => {
        presenter.togglePassword();
      },
      onTransportChange: (transport) => {
        presenter.setSelectedTransport(transport);
        workflow.renderCurrentState();
      },
      onSsidInput: (value) => {
        presenter.setSsidInput(value);
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

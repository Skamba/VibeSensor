import { computed, signal } from "../ui_signals";
import type { FeatureServices } from "../feature_deps_base";
import { createUpdateFeatureWorkflow } from "./update_feature_workflow";
import { createUpdateFeaturePresenter } from "../views/update_feature_presenter";
import type { InternetPanelView } from "../views/internet_panel";
import type { UpdatePanelView } from "../views/update_panel";

interface UpdateFeaturePanels {
  update: UpdatePanelView;
  internet: InternetPanelView;
}

interface UpdateFeaturePorts {
  getActiveSettingsTabId: () => string;
  getActiveViewId: () => string;
  subscribePrimaryViewChanges(listener: (viewId: string) => void): () => void;
  subscribeSettingsTabChanges(listener: (tabId: string) => void): () => void;
}

export interface UpdateFeatureDeps {
  panels: UpdateFeaturePanels;
  ports: UpdateFeaturePorts;
  services: FeatureServices;
}

export interface UpdateFeature {
  bindUpdateHandlers(): void;
  startPolling(): void;
  stopPolling(): void;
}

function isUpdatePollingContext(viewId: string, tabId: string): boolean {
  return viewId === "settingsView" && (tabId === "internetTab" || tabId === "updateTab");
}

export function createUpdateFeature(ctx: UpdateFeatureDeps): UpdateFeature {
  const { panels, ports, services } = ctx;
  const handlersBound = signal(false);
  const activeViewId = signal(ports.getActiveViewId());
  const activeSettingsTabId = signal(ports.getActiveSettingsTabId());
  const pollingEnabled = computed(() =>
    handlersBound.value
    && isUpdatePollingContext(activeViewId.value, activeSettingsTabId.value)
  );
  const presenter = createUpdateFeaturePresenter({
    panel: panels.update,
    internetPanel: panels.internet,
    t: services.t,
  });
  const workflow = createUpdateFeatureWorkflow({
    t: services.t,
    showError: services.showError,
    view: presenter,
    pollingEnabled,
  });

  ports.subscribePrimaryViewChanges((viewId) => {
    activeViewId.value = viewId;
  });
  ports.subscribeSettingsTabChanges((tabId) => {
    activeSettingsTabId.value = tabId;
  });

  function bindUpdateHandlers(): void {
    if (handlersBound.value) {
      return;
    }
    handlersBound.value = true;
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

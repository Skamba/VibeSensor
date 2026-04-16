import {
  computed,
  signal,
  type ReadonlySignal,
} from "../ui_signals";
import type { FeatureServices } from "../feature_deps_base";
import { createUpdateFeatureWorkflow } from "./update_feature_workflow";
import {
  createUpdateFeaturePresenter,
  type UpdateFeaturePresenter,
} from "../views/update_feature_presenter";
import type { InternetPanelView } from "../views/internet_panel";
import type { UpdatePanelView } from "../views/update_panel";

interface UpdateFeaturePanels {
  update: UpdatePanelView;
  internet: InternetPanelView;
}

interface UpdateFeaturePorts {
  getActiveSettingsTabId: () => string;
  activeViewId: ReadonlySignal<string>;
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
  const activeSettingsTabId = signal(ports.getActiveSettingsTabId());
  const pollingEnabled = computed(() =>
    handlersBound.value
    && isUpdatePollingContext(ports.activeViewId.value, activeSettingsTabId.value)
  );
  let presenter!: UpdateFeaturePresenter;
  const workflow = createUpdateFeatureWorkflow({
    t: services.t,
    showError: services.showError,
    view: {
      clearPassword() {
        presenter.clearPassword();
      },
      focusSsidInput() {
        panels.internet.focusSsidInput();
      },
    },
    pollingEnabled,
  });
  presenter = createUpdateFeaturePresenter({
    renderState: workflow.renderState,
    t: services.t,
  });
  panels.internet.bindModel(presenter.internetPanelModel);
  panels.update.bindModel(presenter.updatePanelModel);

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
        void workflow.startUpdate(presenter.readStartIntent());
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
      },
      onSsidInput: (value) => {
        presenter.setSsidInput(value);
      },
    });
  }

  return {
    bindUpdateHandlers,
    startPolling: () => workflow.startPolling(),
    stopPolling: () => workflow.stopPolling(),
  };
}

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
  activeViewId: ReadonlySignal<string>;
  activeSettingsTabId: ReadonlySignal<string>;
}

export interface UpdateFeatureDeps {
  panels: UpdateFeaturePanels;
  ports: UpdateFeaturePorts;
  services: FeatureServices;
}

export interface UpdateFeature {
  bindUpdateHandlers(): void;
  dispose(): void;
  startPolling(): void;
  stopPolling(): void;
}

function isUpdatePollingContext(viewId: string, tabId: string): boolean {
  return viewId === "settingsView" && (tabId === "internetTab" || tabId === "updateTab");
}

export function createUpdateFeature(ctx: UpdateFeatureDeps): UpdateFeature {
  const { panels, ports, services } = ctx;
  const handlersBound = signal(false);
  const pollingEnabled = computed(() =>
    handlersBound.value
    && isUpdatePollingContext(ports.activeViewId.value, ports.activeSettingsTabId.value)
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
  panels.internet.model.value = presenter.internetPanelModel;
  panels.update.model.value = presenter.updatePanelModel;

  function bindUpdateHandlers(): void {
    if (handlersBound.value) {
      return;
    }
    handlersBound.value = true;
    panels.update.actions.value = {
      onStart: () => {
        void workflow.startUpdate(presenter.readStartIntent());
      },
      onCancel: () => {
        void workflow.cancelUpdate();
      },
    };
    panels.internet.actions.value = {
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
    };
  }

  return {
    bindUpdateHandlers,
    dispose(): void {
      workflow.dispose();
    },
    startPolling: () => workflow.startPolling(),
    stopPolling: () => workflow.stopPolling(),
  };
}

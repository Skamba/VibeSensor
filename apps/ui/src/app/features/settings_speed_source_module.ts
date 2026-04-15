import type { FeatureDepsBase } from "../feature_deps_base";
import {
  buildSettingsSpeedSourcePanelModel,
  type SettingsSpeedSourcePresenterDeps,
} from "../views/settings_speed_source_presenter";
import type { SpeedSourcePanelView } from "../views/speed_source_panel";
import type { SettingsState } from "../ui_app_state";
import { createSettingsSpeedSourceWorkflow } from "./settings_speed_source_workflow";

export interface SettingsSpeedSourceModuleDeps extends FeatureDepsBase {
  panel: SpeedSourcePanelView;
  settings: SettingsState;
  getSpeedUnit: () => string;
  fmt: (n: number, digits?: number) => string;
  renderSpeedReadout: () => void;
  subscribePrimaryViewChanges(listener: (viewId: string) => void): () => void;
  subscribeSettingsTabChanges(listener: (tabId: string) => void): () => void;
}

export interface SettingsSpeedSourceModule {
  bindHandlers(): void;
  syncSpeedSourceSelectionUi(): void;
  syncSpeedSourceInputs(): void;
  loadSpeedSourceFromServer(): Promise<void>;
  saveSpeedSourceFromInputs(): void;
}

export function createSettingsSpeedSourceModule(
  ctx: SettingsSpeedSourceModuleDeps,
): SettingsSpeedSourceModule {
  const { settings, t } = ctx;
  const presenterDeps: SettingsSpeedSourcePresenterDeps = {
    fmt: ctx.fmt,
    getSpeedUnit: ctx.getSpeedUnit,
    t,
  };
  const workflow = createSettingsSpeedSourceWorkflow({
    renderSpeedReadout: ctx.renderSpeedReadout,
    settings,
    showError: ctx.showError,
    t,
    view: {
      focusManualSpeedInput: ctx.panel.focusManualSpeedInput,
      focusScanObdDevices: ctx.panel.focusScanObdDevices,
      focusStaleTimeoutInput: ctx.panel.focusStaleTimeoutInput,
      isObdConfigVisible: ctx.panel.isObdConfigVisible,
      render(state): void {
        ctx.panel.setModel(buildSettingsSpeedSourcePanelModel(state, presenterDeps));
      },
    },
  });
  let handlersBound = false;

  function bindHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    ctx.subscribeSettingsTabChanges(() => {
      workflow.handleNavigateContext();
    });
    ctx.subscribePrimaryViewChanges(() => {
      workflow.handleNavigateContext();
    });
    ctx.panel.bindActions({
      onManualSpeedInput(value): void {
        workflow.handleManualSpeedInput(value);
      },
      onPairObdDevice(macAddress): void {
        void workflow.pairObdDevice(macAddress);
      },
      onSave(): void {
        void workflow.saveSpeedSource();
      },
      onScanObdDevices(): void {
        void workflow.scanObdDevices();
      },
      onSpeedSourceChanged(mode): void {
        workflow.handleSpeedSourceChanged(mode);
      },
      onStaleTimeoutInput(value): void {
        workflow.handleStaleTimeoutInput(value);
      },
    });
    workflow.handleNavigateContext();
  }

  return {
    bindHandlers,
    loadSpeedSourceFromServer: workflow.loadSpeedSourceFromServer,
    saveSpeedSourceFromInputs(): void {
      void workflow.saveSpeedSource();
    },
    syncSpeedSourceInputs: workflow.syncInputsFromSettings,
    syncSpeedSourceSelectionUi: workflow.syncFromSettings,
  };
}

import type { FeatureFormatting, FeatureServices } from "../feature_deps_base";
import {
  buildSettingsSpeedSourcePanelModel,
  type SettingsSpeedSourcePresenterDeps,
} from "../views/settings_speed_source_presenter";
import type { SpeedSourcePanelView } from "../views/speed_source_panel";
import type { SettingsState } from "../ui_app_state";
import {
  computed,
  effect,
  untracked,
  type ReadonlySignal,
} from "../ui_signals";
import { createSettingsSpeedSourceWorkflow } from "./settings_speed_source_workflow";

interface SettingsSpeedSourceModulePorts {
  activeViewId: ReadonlySignal<string>;
  activeSettingsTabId: ReadonlySignal<string>;
  renderSpeedReadout: () => void;
}

export interface SettingsSpeedSourceModuleDeps {
  panel: SpeedSourcePanelView;
  settings: SettingsState;
  services: FeatureServices;
  formatting: Pick<FeatureFormatting, "fmt">;
  getSpeedUnit: () => string;
  ports: SettingsSpeedSourceModulePorts;
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
  const { settings, services } = ctx;
  const presenterDeps: SettingsSpeedSourcePresenterDeps = {
    fmt: ctx.formatting.fmt,
    getSpeedUnit: ctx.getSpeedUnit,
    t: services.t,
  };
  const workflow = createSettingsSpeedSourceWorkflow({
    renderSpeedReadout: ctx.ports.renderSpeedReadout,
    settings,
    showError: services.showError,
    t: services.t,
    view: {
      focusManualSpeedInput: ctx.panel.focusManualSpeedInput,
      focusScanObdDevices: ctx.panel.focusScanObdDevices,
      focusStaleTimeoutInput: ctx.panel.focusStaleTimeoutInput,
      isObdConfigVisible: ctx.panel.isObdConfigVisible,
    },
  });
  const panelModel = computed(() =>
    buildSettingsSpeedSourcePanelModel(workflow.renderState.value, presenterDeps)
  );
  ctx.panel.bindModel(panelModel);
  let handlersBound = false;

  function bindHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    let hasSeenInitialContext = false;
    effect(() => {
      ctx.ports.activeViewId.value;
      ctx.ports.activeSettingsTabId.value;
      if (!hasSeenInitialContext) {
        hasSeenInitialContext = true;
        return;
      }
      untracked(() => {
        workflow.handleNavigateContext();
      });
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

import type { UiShellDom } from "../dom/shell_dom";
import type { FeatureDepsBase } from "../feature_deps_base";
import {
  bindSettingsSpeedSourceInteractions,
  type SettingsSpeedSourceInteraction,
} from "../views/settings_speed_source_bindings";
import {
  buildSettingsSpeedSourcePanelModel,
  type SettingsSpeedSourcePresenterDeps,
} from "../views/settings_speed_source_presenter";
import type { SettingsShellDom } from "../views/settings_shell";
import type {
  SettingsSpeedSourcePanelDom,
  SpeedSourcePanelView,
} from "../views/speed_source_panel";
import type { SettingsState } from "../ui_app_state";
import { createSettingsSpeedSourceWorkflow } from "./settings_speed_source_workflow";

export interface SettingsSpeedSourceModuleDeps extends FeatureDepsBase {
  dom: Pick<SettingsShellDom, "settingsTabs"> & SettingsSpeedSourcePanelDom;
  panel: SpeedSourcePanelView;
  shellDom: Pick<UiShellDom, "menuButtons">;
  settings: SettingsState;
  getSpeedUnit: () => string;
  fmt: (n: number, digits?: number) => string;
  renderSpeedReadout: () => void;
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
  const { settings, dom: els, shellDom, t } = ctx;
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
        ctx.panel.render(buildSettingsSpeedSourcePanelModel(state, presenterDeps));
      },
    },
  });
  let handlersBound = false;

  function bindHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    bindSettingsSpeedSourceInteractions(els, shellDom, {
      onAction: (action: SettingsSpeedSourceInteraction) => {
        if (action.type === "speed-source-changed") {
          workflow.handleSpeedSourceChanged(action.mode);
          return;
        }
        if (action.type === "manual-speed-input") {
          workflow.handleManualSpeedInput(action.value);
          return;
        }
        if (action.type === "stale-timeout-input") {
          workflow.handleStaleTimeoutInput(action.value);
          return;
        }
        if (action.type === "save") {
          void workflow.saveSpeedSource();
          return;
        }
        if (action.type === "scan-obd-devices") {
          void workflow.scanObdDevices();
          return;
        }
        if (action.type === "navigate-context") {
          workflow.handleNavigateContext();
          return;
        }
        void workflow.pairObdDevice(action.macAddress);
      },
    });
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

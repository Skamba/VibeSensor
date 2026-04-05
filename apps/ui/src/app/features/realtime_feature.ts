import type { UiCarsDom } from "../dom/cars_dom";
import type { UiRealtimeDom } from "../dom/realtime_dom";
import type { UiSettingsDom } from "../dom/settings_dom";
import type { UiShellDom } from "../dom/shell_dom";
import type { FeatureDepsBase } from "../feature_deps_base";
import type { RealtimeState, SettingsState, SpectrumState } from "../ui_app_state";
import type { LocationOption } from "../../transport/http_models";
import type { AdaptedClient } from "../../transport/live_models";
import {
  bindRealtimeFeatureInteractions,
} from "../views/realtime_feature_bindings";
import { createRealtimeFeatureWorkflow } from "./realtime_feature_workflow";
import { createRealtimeFeaturePresenter } from "../views/realtime_feature_presenter";

export interface RealtimeFeatureDeps extends FeatureDepsBase {
  dom: UiRealtimeDom;
  shellDom: Pick<UiShellDom, "menuButtons">;
  settingsDom: Pick<UiSettingsDom, "settingsTabs">;
  carsDom: Pick<UiCarsDom, "addCarBtn">;
  realtime: RealtimeState;
  spectrum: SpectrumState;
  settings: SettingsState;
  getLanguage: () => string;
  formatInt: (value: number) => string;
  chrome: RealtimeFeatureChromePorts;
  selection: RealtimeFeatureSelectionPorts;
  recording: RealtimeFeatureRecordingPorts;
}

export interface RealtimeFeatureChromePorts {
  setPillState: (el: HTMLElement | null, variant: string, text: string) => void;
  setStatValue: (container: HTMLElement | null, value: string | number) => void;
}

export interface RealtimeFeatureSelectionPorts {
  sendSelection: () => void;
}

export interface RealtimeFeatureRecordingPorts {
  onRecordingStatusChanged: () => Promise<void>;
}

export interface RealtimeFeature {
  bindHandlers(): void;
  buildLocationOptions(codes: readonly string[]): LocationOption[];
  maybeRenderSensorsSettingsList(force?: boolean): void;
  updateClientSelection(): void;
  renderStatus(clientRow?: AdaptedClient): void;
  renderLoggingStatus(): void;
  refreshLoggingStatus(): Promise<void>;
  refreshLocationOptions(): Promise<void>;
}

export function createRealtimeFeature(ctx: RealtimeFeatureDeps): RealtimeFeature {
  const isDemoMode = new URLSearchParams(window.location.search).has("demo");
  const presenter = createRealtimeFeaturePresenter({
    realtime: ctx.realtime,
    settings: ctx.settings,
    spectrum: ctx.spectrum,
    getLanguage: ctx.getLanguage,
    dom: ctx.dom,
    shellDom: ctx.shellDom,
    settingsDom: ctx.settingsDom,
    carsDom: ctx.carsDom,
    t: ctx.t,
    escapeHtml: ctx.escapeHtml,
    formatInt: ctx.formatInt,
    chrome: ctx.chrome,
  });
  const workflow = createRealtimeFeatureWorkflow({
    realtime: ctx.realtime,
    t: ctx.t,
    showError: ctx.showError,
    isDemoMode,
    view: presenter,
    selection: ctx.selection,
    recording: ctx.recording,
    confirmRemoveClient: (message) => window.confirm(message),
  });
  let handlersBound = false;

  function bindHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    workflow.bindHandlers();
    bindRealtimeFeatureInteractions(ctx.dom, {
      onStartLogging: () => {
        void workflow.startLogging();
      },
      onStopLogging: () => {
        void workflow.stopLogging();
      },
      onLoggingSummaryAction: (action) => {
        if (action === "open-history") {
          presenter.openHistory();
          return;
        }
        if (action === "open-add-car") {
          presenter.openCars({ openWizard: true });
          return;
        }
        if (action === "open-cars") {
          presenter.openCars();
          return;
        }
        if (action === "open-sensors") {
          presenter.openSensorsSettings();
          return;
        }
        presenter.openSpeedSourceSettings();
      },
      onSensorLocationChange: (change) => {
        void workflow.setClientLocation(change.clientId, change.locationCode);
      },
      onSensorTableAction: (action) => {
        if (action.type === "identify") {
          void workflow.identifyClient(action.clientId);
          return;
        }
        void workflow.removeClient(action.clientId);
      },
    });
  }

  return {
    bindHandlers,
    buildLocationOptions: (codes) => presenter.buildLocationOptions(codes),
    maybeRenderSensorsSettingsList: (force) => presenter.maybeRenderSensorsSettingsList(force),
    updateClientSelection: () => workflow.updateClientSelection(),
    renderStatus: (clientRow) => presenter.renderStatus(clientRow),
    renderLoggingStatus: () => workflow.renderLoggingStatus(),
    refreshLoggingStatus: () => workflow.refreshLoggingStatus(),
    refreshLocationOptions: () => workflow.refreshLocationOptions(),
  };
}

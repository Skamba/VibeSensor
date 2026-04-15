import type { FeatureDepsBase } from "../feature_deps_base";
import type {
  RealtimeState,
  SettingsState,
  ShellState,
  SpectrumState,
} from "../ui_app_state";
import { trackAppStateSlice } from "../ui_app_state";
import type { AdaptedClient } from "../../transport/live_models";
import type { RealtimeLoggingPanelBridge } from "../views/realtime_logging_panel";
import type { RealtimeLiveOverviewBridge } from "../views/realtime_live_overview";
import type { SensorsPanelView } from "../views/sensors_panel";
import { effect, untracked } from "../ui_signals";
import { createRealtimeFeatureWorkflow } from "./realtime_feature_workflow";
import { createRealtimeFeaturePresenter } from "../views/realtime_feature_presenter";

export interface RealtimeFeatureDeps extends FeatureDepsBase {
  realtime: RealtimeState;
  spectrum: SpectrumState;
  settings: SettingsState;
  shell: Pick<ShellState, "lang">;
  formatInt: (value: number) => string;
  chrome: RealtimeFeatureChromePorts;
  sensorsPanel: SensorsPanelView;
  navigation: RealtimeFeatureNavigationPorts;
  selection: RealtimeFeatureSelectionPorts;
  recording: RealtimeFeatureRecordingPorts;
}

export interface RealtimeFeatureChromePorts {
  setShellLiveStatus: (variant: string, text: string) => void;
  liveOverview: RealtimeLiveOverviewBridge;
  loggingPanel: RealtimeLoggingPanelBridge;
}

export interface RealtimeFeatureNavigationPorts {
  activatePrimaryView(viewId: string): void;
  activateSettingsTab(tabId: string): void;
  openCarWizard(): void;
}

export interface RealtimeFeatureSelectionPorts {
  sendSelection: () => void;
}

export interface RealtimeFeatureRecordingPorts {
  onRecordingStatusChanged: () => Promise<void>;
}

export interface RealtimeFeature {
  bindHandlers(): void;
  maybeRenderSensorsSettingsList(force?: boolean): void;
  renderStatus(clientRow?: AdaptedClient): void;
  renderLoggingStatus(): void;
  refreshLoggingStatus(): Promise<void>;
  refreshLocationOptions(): Promise<void>;
}

export function createRealtimeFeature(
  ctx: RealtimeFeatureDeps,
): RealtimeFeature {
  const isDemoMode = new URLSearchParams(window.location.search).has("demo");
  const presenter = createRealtimeFeaturePresenter({
    realtime: ctx.realtime,
    settings: ctx.settings,
    shell: ctx.shell,
    spectrum: ctx.spectrum,
    sensorsPanel: ctx.sensorsPanel,
    t: ctx.t,
    formatInt: ctx.formatInt,
    chrome: ctx.chrome,
    navigation: ctx.navigation,
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

  effect(() => {
    trackAppStateSlice(ctx.realtime);
    trackAppStateSlice(ctx.settings);
    trackAppStateSlice(ctx.spectrum);
    untracked(() => {
      presenter.maybeRenderSensorsSettingsList();
      workflow.renderLoggingStatus();
    });
  });

  function bindHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    ctx.chrome.loggingPanel.bindActions({
      onStartLogging: () => {
        void workflow.startLogging();
      },
      onStopLogging: () => {
        void workflow.stopLogging();
      },
      onSummaryAction: (action) => {
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
    });
    workflow.bindHandlers();
    ctx.sensorsPanel.bindActions({
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
    maybeRenderSensorsSettingsList: (force) =>
      presenter.maybeRenderSensorsSettingsList(force),
    renderStatus: (clientRow) => presenter.renderStatus(clientRow),
    renderLoggingStatus: () => workflow.renderLoggingStatus(),
    refreshLoggingStatus: () => workflow.refreshLoggingStatus(),
    refreshLocationOptions: () => workflow.refreshLocationOptions(),
  };
}

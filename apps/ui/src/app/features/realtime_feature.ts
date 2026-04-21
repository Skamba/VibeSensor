import type { QueryClient } from "@tanstack/query-core";

import type { FeatureFormatting, FeatureServices } from "../feature_deps_base";
import type {
  RealtimeState,
  SettingsState,
  ShellState,
  SpectrumState,
} from "../ui_app_state";
import type { RealtimeLoggingPanelBridge } from "../views/realtime_logging_panel";
import type { RealtimeLiveOverviewBridge } from "../views/realtime_live_overview";
import type { SensorsPanelView } from "../views/sensors_panel";
import { effect, untracked } from "../ui_signals";
import {
  createRealtimeFeatureWorkflow,
  createRealtimeFeatureWorkflowState,
} from "./realtime_feature_workflow";
import { createRealtimeFeatureViewState } from "./realtime_feature_view_state";

interface RealtimeFeatureStateDeps {
  realtime: RealtimeState;
  spectrum: SpectrumState;
  settings: SettingsState;
  shell: Pick<ShellState, "lang">;
}

interface RealtimeFeaturePanelDeps {
  sensorsPanel: SensorsPanelView;
}

interface RealtimeFeaturePortDeps {
  chrome: RealtimeFeatureChromePorts;
  navigation: RealtimeFeatureNavigationPorts;
  selection: RealtimeFeatureSelectionPorts;
  recording: RealtimeFeatureRecordingPorts;
}

export interface RealtimeFeatureDeps {
  state: RealtimeFeatureStateDeps;
  panels: RealtimeFeaturePanelDeps;
  ports: RealtimeFeaturePortDeps;
  queryClient: QueryClient;
  services: FeatureServices;
  formatting: Pick<FeatureFormatting, "formatInt">;
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
  dispose(): void;
  refreshLoggingStatus(): Promise<void>;
  refreshLocationOptions(): Promise<void>;
}

export function createRealtimeFeature(
  ctx: RealtimeFeatureDeps,
): RealtimeFeature {
  const { state, panels, ports, services, formatting } = ctx;
  const isDemoMode = new URLSearchParams(window.location.search).has("demo");
  let handlersBound = false;
  const workflowState = createRealtimeFeatureWorkflowState();
  const viewState = createRealtimeFeatureViewState({
    state: {
      realtime: state.realtime,
      settings: state.settings,
      shell: state.shell,
      spectrum: state.spectrum,
    },
    services: {
      t: services.t,
    },
    formatting: {
      formatInt: formatting.formatInt,
    },
    workflow: workflowState,
  });
  ports.chrome.liveOverview.model.value = viewState.liveOverviewModel;
  ports.chrome.loggingPanel.model.value = viewState.loggingPanelModel;
  panels.sensorsPanel.model.value = viewState.sensorsPanelModel;
  const workflow = createRealtimeFeatureWorkflow({
    realtime: state.realtime,
    t: services.t,
    showError: services.showError,
    queryClient: ctx.queryClient,
    isDemoMode,
    idleCaptureReadinessSignature: viewState.idleCaptureReadinessSignature,
    selection: ports.selection,
    recording: ports.recording,
    confirmRemoveClient: (message) => services.requestConfirmation(message),
    state: workflowState,
  });

  function activatePrimaryView(viewId: string): void {
    ports.navigation.activatePrimaryView(viewId);
  }

  function activateSettingsTab(tabId: string): void {
    ports.navigation.activateSettingsTab(tabId);
  }

  function openSettingsView(tabId: string): void {
    activatePrimaryView("settingsView");
    activateSettingsTab(tabId);
  }

  const disposeLiveStatusSync = effect(() => {
    const model = viewState.liveOverviewModel.value;
    untracked(() => {
      ports.chrome.setShellLiveStatus(model.runHealth.variant, model.runHealth.text);
    });
  });

  function bindHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    ports.chrome.loggingPanel.actions.value = {
      onStartLogging: () => {
        void workflow.startLogging();
      },
      onStopLogging: () => {
        void workflow.stopLogging();
      },
      onSummaryAction: (action) => {
        if (action === "open-history") {
          activatePrimaryView("historyView");
          return;
        }
        if (action === "open-add-car") {
          openSettingsView("carTab");
          ports.navigation.openCarWizard();
          return;
        }
        if (action === "open-cars") {
          openSettingsView("carTab");
          return;
        }
        if (action === "open-sensors") {
          openSettingsView("sensorsTab");
          return;
        }
        openSettingsView("speedSourceTab");
      },
    };
    workflow.bindHandlers();
    panels.sensorsPanel.actions.value = {
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
    };
  }

  return {
    bindHandlers,
    dispose(): void {
      disposeLiveStatusSync();
      workflow.dispose();
      viewState.dispose();
    },
    refreshLoggingStatus: () => workflow.refreshLoggingStatus(),
    refreshLocationOptions: () => workflow.refreshLocationOptions(),
  };
}

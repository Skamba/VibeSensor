import type { UiStartupFeaturePorts } from "./runtime/ui_startup_feature_ports";
import type { HistoryFeature } from "./features/history_feature";
import type { RealtimeFeature, RealtimeFeatureRecordingPorts } from "./features/realtime_feature";

export interface AppShellFeatureBindings {
  bindHandlers(): void;
}

export interface AppFeatureBundle {
  dispose(): void;
  ensureViewReady(viewId: string): Promise<void>;
  shell: AppShellFeatureBindings;
  startup: UiStartupFeaturePorts;
}

interface AppFeatureBundlePortSources {
  dashboard?: {
    hydrateStartupState(): Promise<void>;
  };
  realtime: Pick<
    RealtimeFeature,
    | "bindHandlers"
    | "dispose"
    | "refreshLocationOptions"
    | "refreshLoggingStatus"
  >;
  secondary?: {
    dispose(): void;
  };
  ensureViewReady?: (viewId: string) => Promise<void>;
}

export function createRealtimeFeatureRecordingPorts(
  history: Pick<HistoryFeature, "refreshHistory"> | (() => Promise<void>),
): RealtimeFeatureRecordingPorts {
  const refreshHistory = typeof history === "function"
    ? history
    : () => history.refreshHistory();
  return {
    onRecordingStatusChanged: () => refreshHistory(),
  };
}

export function createAppFeatureBundlePorts(
  features: AppFeatureBundlePortSources,
): AppFeatureBundle {
  return {
    dispose: () => {
      features.secondary?.dispose();
      features.realtime.dispose();
    },
    ensureViewReady: (viewId) => features.ensureViewReady?.(viewId) ?? Promise.resolve(),
    shell: {
      bindHandlers: () => {
        features.realtime.bindHandlers();
      },
    },
    startup: {
      dashboard: {
        hydrateStartupState: () => features.dashboard?.hydrateStartupState() ?? Promise.resolve(),
      },
      realtime: {
        refreshLocationOptions: () => features.realtime.refreshLocationOptions(),
        refreshLoggingStatus: () => features.realtime.refreshLoggingStatus(),
      },
    },
  };
}

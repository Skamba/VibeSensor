import type { QueryClient } from "@tanstack/query-core";

import {
  createAppFeatureBundlePorts,
  createRealtimeFeatureRecordingPorts,
} from "./app_feature_bundle_ports";
import {
  createRealtimeFeature,
  type RealtimeFeatureChromePorts,
  type RealtimeFeatureSelectionPorts,
} from "./features/realtime_feature";
import { createDashboardSpeedSourceStatusModule } from "./features/dashboard_speed_source_status_module";
import { loadDashboardStartupState } from "./features/dashboard_startup_state";
import type { SettingsFeatureViewPorts } from "./features/settings_feature";
import type { FeatureFormatting, FeatureServices } from "./feature_deps_base";
import type { AppState } from "./ui_app_state";
import type { UiMountedPanels } from "./ui_lazy_panels";
import type { ReadonlySignal } from "./ui_signals";
import type { AppFeatureBundle } from "./app_feature_bundle_ports";
import type { AppFeatureSecondaryBundle } from "./app_feature_secondary_bundle";
import { preloadHistoryLazyView } from "./views/history_lazy_view";
import { preloadSettingsLazyView } from "./views/settings_lazy_view";
export type { AppFeatureBundle } from "./app_feature_bundle_ports";

export interface AppFeatureBundleSharedDeps {
  services: FeatureServices;
  formatting: FeatureFormatting;
  serverState: {
    queryClient: QueryClient;
  };
}

export interface AppFeatureBundleRuntimePorts {
  panels: UiMountedPanels;
  navigation: {
    activatePrimaryView(viewId: string): void;
    activeViewId: ReadonlySignal<string>;
  };
  realtimeChrome: Pick<RealtimeFeatureChromePorts, "setShellLiveStatus">;
  transport: RealtimeFeatureSelectionPorts;
  view: SettingsFeatureViewPorts;
}

export interface AppFeatureBundleDeps {
  state: AppState;
  shared: AppFeatureBundleSharedDeps;
  runtime: AppFeatureBundleRuntimePorts;
}

interface LazySecondaryFeatureBundle {
  dispose(): void;
  ensureHistoryDataLoaded(): Promise<void>;
  ensureSettingsDataLoaded(): Promise<void>;
  openCarWizard(): Promise<void>;
  refreshHistory(): Promise<void>;
}

function createLazySecondaryFeatureBundle(
  deps: AppFeatureBundleDeps,
): LazySecondaryFeatureBundle {
  let bundle: AppFeatureSecondaryBundle | null = null;
  let bundlePromise: Promise<AppFeatureSecondaryBundle> | null = null;
  let historyLoadPromise: Promise<void> | null = null;
  let settingsLoadPromise: Promise<void> | null = null;
  let historyLoaded = false;
  let settingsLoaded = false;
  let disposed = false;

  function ensureLoaded(): Promise<AppFeatureSecondaryBundle> {
    if (bundle !== null) {
      return Promise.resolve(bundle);
    }
    if (bundlePromise !== null) {
      return bundlePromise;
    }
    bundlePromise = import("./app_feature_secondary_bundle")
      .then(({ createAppFeatureSecondaryBundle }) => {
        const nextBundle = createAppFeatureSecondaryBundle(deps);
        if (disposed) {
          nextBundle.dispose();
          return nextBundle;
        }
        bundle = nextBundle;
        return nextBundle;
      })
      .catch((error) => {
        bundlePromise = null;
        throw error;
      });
    return bundlePromise;
  }

  function ensureSettingsDataLoaded(): Promise<void> {
    if (settingsLoaded || disposed) {
      return Promise.resolve();
    }
    if (settingsLoadPromise !== null) {
      return settingsLoadPromise;
    }
    settingsLoadPromise = (async () => {
      const loadedBundle = await ensureLoaded();
      if (disposed) {
        return;
      }
      await Promise.all([
        loadedBundle.settings.loadSpeedSourceFromServer(),
        loadedBundle.settings.loadAnalysisSettingsFromServer(),
      ]);
      settingsLoaded = true;
    })().catch((error) => {
      settingsLoadPromise = null;
      throw error;
    });
    return settingsLoadPromise;
  }

  function ensureHistoryDataLoaded(): Promise<void> {
    if (historyLoaded || disposed) {
      return Promise.resolve();
    }
    if (historyLoadPromise !== null) {
      return historyLoadPromise;
    }
    historyLoadPromise = (async () => {
      const loadedBundle = await ensureLoaded();
      if (disposed) {
        return;
      }
      await loadedBundle.history.refreshHistory();
      historyLoaded = true;
    })().catch((error) => {
      historyLoadPromise = null;
      throw error;
    });
    return historyLoadPromise;
  }

  return {
    dispose(): void {
      disposed = true;
      bundle?.dispose();
      bundle = null;
    },
    ensureHistoryDataLoaded,
    ensureSettingsDataLoaded,
    openCarWizard(): Promise<void> {
      return ensureLoaded().then((loadedBundle) => {
        if (!disposed) {
          loadedBundle.openCarWizard();
        }
      });
    },
    refreshHistory(): Promise<void> {
      return ensureLoaded().then((loadedBundle) => loadedBundle.history.refreshHistory());
    },
  };
}

export function createAppFeatureBundle(
  deps: AppFeatureBundleDeps,
): AppFeatureBundle {
  const {
    state,
    shared: { services, formatting, serverState },
    runtime,
  } = deps;
  const { panels } = runtime;
  const secondary = createLazySecondaryFeatureBundle(deps);
  const dashboardSpeedSourceStatus = createDashboardSpeedSourceStatusModule({
    activeViewId: runtime.navigation.activeViewId,
    queryClient: serverState.queryClient,
    settings: state.settings,
  });
  const reportFeatureLoadError = (error: unknown): void => {
    services.showError(
      error instanceof Error ? error.message : services.t("status.view_load_failed"),
    );
  };
  const ensureSecondaryViewReady = (viewId: string): Promise<void> => {
    if (viewId === "historyView") {
      return Promise.all([
        preloadHistoryLazyView(),
        secondary.ensureHistoryDataLoaded(),
      ]).then(() => undefined);
    }
    if (viewId === "settingsView") {
      return Promise.all([
        preloadSettingsLazyView(),
        secondary.ensureSettingsDataLoaded(),
      ]).then(() => undefined);
    }
    return Promise.resolve();
  };

  const realtime = createRealtimeFeature({
    state: {
      realtime: state.realtime,
      settings: state.settings,
      spectrum: state.spectrum,
      shell: state.shell,
    },
    panels: {
      sensorsPanel: panels.settings.sensors,
    },
    ports: {
      chrome: {
        ...runtime.realtimeChrome,
        liveOverview: panels.dashboard.liveOverview,
        loggingPanel: panels.dashboard.logging,
      },
      navigation: {
        activatePrimaryView: runtime.navigation.activatePrimaryView,
        activateSettingsTab: (tabId) => panels.settingsShell.activateTab(tabId),
        openCarWizard: () => {
          void secondary.openCarWizard().catch(reportFeatureLoadError);
        },
      },
      selection: runtime.transport,
      recording: createRealtimeFeatureRecordingPorts(() => secondary.refreshHistory()),
    },
    services,
    formatting: {
      formatInt: formatting.formatInt,
    },
    queryClient: serverState.queryClient,
  });

  const bundle = createAppFeatureBundlePorts({
    dashboard: {
      hydrateStartupState: () => Promise.all([
        loadDashboardStartupState(serverState.queryClient, state.settings),
        dashboardSpeedSourceStatus.markStartupReady(),
      ]).then(() => undefined),
    },
    realtime,
    ensureViewReady: (viewId) => ensureSecondaryViewReady(viewId).catch((error) => {
      reportFeatureLoadError(error);
      throw error;
    }),
    secondary: {
      dispose: () => secondary.dispose(),
    },
  });

  return {
    ...bundle,
    dispose(): void {
      dashboardSpeedSourceStatus.dispose();
      bundle.dispose();
    },
    shell: {
      bindHandlers(): void {
        dashboardSpeedSourceStatus.bindHandlers();
        bundle.shell.bindHandlers();
      },
    },
    startup: {
      ...bundle.startup,
      dashboard: {
        hydrateStartupState: () => bundle.startup.dashboard.hydrateStartupState().catch((error) => {
          reportFeatureLoadError(error);
          throw error;
        }),
      },
    },
  };
}

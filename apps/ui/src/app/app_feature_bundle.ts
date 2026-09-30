import type { QueryClient } from "@tanstack/query-core";

import { createDashboardSpeedSourceStatusModule } from "./features/dashboard_speed_source_status_module";
import { loadDashboardStartupState } from "./features/dashboard_startup_state";
import { createRealtimeFeature } from "./features/realtime_feature";
import type { FeatureFormatting, FeatureServices } from "./feature_deps_base";
import type { AppFeatureSecondaryBundle } from "./app_feature_secondary_bundle";
import type { UiStartupFeatures } from "./runtime/ui_startup_coordinator";
import type { AppState } from "./ui_app_state";
import type { UiMountedPanels } from "./ui_lazy_panels";
import type { ReadonlySignal } from "./ui_signals";
import { preloadHistoryLazyView } from "./views/history_lazy_view";
import { preloadSettingsLazyView } from "./views/settings_lazy_view";

/** Everything the feature controllers need from state and the runtime. */
export interface AppFeatureContext {
  state: AppState;
  services: FeatureServices;
  formatting: FeatureFormatting;
  queryClient: QueryClient;
  panels: UiMountedPanels;
  activeViewId: ReadonlySignal<string>;
  activatePrimaryView(viewId: string): void;
  setShellLiveStatus(variant: string, text: string): void;
  sendSelection(): void;
  refreshSpectrumDecorations(): void;
}

export interface AppFeatureBundle {
  bindHandlers(): void;
  dispose(): void;
  ensureViewReady(viewId: string): Promise<void>;
  startup: UiStartupFeatures;
}

interface LazySecondaryFeatureBundle {
  dispose(): void;
  ensureHistoryDataLoaded(): Promise<void>;
  ensureSettingsDataLoaded(): Promise<void>;
  openCarWizard(): Promise<void>;
  refreshHistory(): Promise<void>;
}

function createLazySecondaryFeatureBundle(
  ctx: AppFeatureContext,
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
        const nextBundle = createAppFeatureSecondaryBundle(ctx);
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
      return ensureLoaded().then((loadedBundle) =>
        loadedBundle.history.refreshHistory(),
      );
    },
  };
}

export function createAppFeatureBundle(
  ctx: AppFeatureContext,
): AppFeatureBundle {
  const { state, services, panels } = ctx;
  const secondary = createLazySecondaryFeatureBundle(ctx);
  const dashboardSpeedSourceStatus = createDashboardSpeedSourceStatusModule({
    activeViewId: ctx.activeViewId,
    queryClient: ctx.queryClient,
    settings: state.settings,
  });
  const reportFeatureLoadError = (error: unknown): void => {
    services.showError(
      error instanceof Error
        ? error.message
        : services.t("status.view_load_failed"),
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
    realtime: state.realtime,
    settings: state.settings,
    spectrum: state.spectrum,
    shell: state.shell,
    sensorsPanel: panels.settings.sensors,
    liveOverview: panels.dashboard.liveOverview,
    loggingPanel: panels.dashboard.logging,
    setShellLiveStatus: ctx.setShellLiveStatus,
    navigation: {
      activatePrimaryView: ctx.activatePrimaryView,
      activateSettingsTab: (tabId) => panels.settingsShell.activateTab(tabId),
      openCarWizard: () => {
        void secondary.openCarWizard().catch(reportFeatureLoadError);
      },
    },
    sendSelection: ctx.sendSelection,
    onRecordingStatusChanged: () => secondary.refreshHistory(),
    services,
    formatting: {
      formatInt: ctx.formatting.formatInt,
    },
    queryClient: ctx.queryClient,
  });

  return {
    bindHandlers(): void {
      dashboardSpeedSourceStatus.bindHandlers();
      realtime.bindHandlers();
    },
    dispose(): void {
      dashboardSpeedSourceStatus.dispose();
      secondary.dispose();
      realtime.dispose();
    },
    ensureViewReady: (viewId) =>
      ensureSecondaryViewReady(viewId).catch((error) => {
        reportFeatureLoadError(error);
        throw error;
      }),
    startup: {
      dashboard: {
        hydrateStartupState: () =>
          Promise.all([
            loadDashboardStartupState(ctx.queryClient, state.settings),
            dashboardSpeedSourceStatus.markStartupReady(),
          ])
            .then(() => undefined)
            .catch((error) => {
              reportFeatureLoadError(error);
              throw error;
            }),
      },
      realtime: {
        refreshLocationOptions: () => realtime.refreshLocationOptions(),
        refreshLoggingStatus: () => realtime.refreshLoggingStatus(),
      },
    },
  };
}

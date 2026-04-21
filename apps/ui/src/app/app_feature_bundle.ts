import type { QueryClient } from "@tanstack/query-core";

import {
  createAppFeatureBundlePorts,
  createRealtimeFeatureRecordingPorts,
} from "./app_feature_bundle_ports";
import { createCarsFeature, type CarsFeature } from "./features/cars_feature";
import { createEspFlashFeature } from "./features/esp_flash_feature";
import { createHistoryFeature } from "./features/history_feature";
import {
  createRealtimeFeature,
  type RealtimeFeatureChromePorts,
  type RealtimeFeatureSelectionPorts,
} from "./features/realtime_feature";
import {
  createSettingsFeature,
  type SettingsFeature,
  type SettingsFeatureViewPorts,
} from "./features/settings_feature";
import { createUpdateFeature } from "./features/update_feature";
import type { FeatureFormatting, FeatureServices } from "./feature_deps_base";
import type { AppState } from "./ui_app_state";
import type { UiMountedPanels } from "./ui_lazy_panels";
import type { ReadonlySignal } from "./ui_signals";
import type { AppFeatureBundle } from "./app_feature_bundle_ports";
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

export function createAppFeatureBundle(
  deps: AppFeatureBundleDeps,
): AppFeatureBundle {
  const {
    state,
    shared: { services, formatting, serverState },
    runtime,
  } = deps;
  const { panels } = runtime;

  const history = createHistoryFeature({
    history: state.history,
    shell: state.shell,
    panel: panels.history,
    navigation: runtime.navigation,
    services,
    formatting,
    queryClient: serverState.queryClient,
  });

  let carsFeature: CarsFeature | null = null;
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
          carsFeature?.openWizard();
        },
      },
      selection: runtime.transport,
      recording: createRealtimeFeatureRecordingPorts(history),
    },
    services,
    formatting: {
      formatInt: formatting.formatInt,
    },
    queryClient: serverState.queryClient,
  });

  const settings: SettingsFeature = createSettingsFeature({
    state: {
      settings: state.settings,
      shell: state.shell,
    },
    panels: {
      settingsShell: panels.settingsShell,
      analysisPanel: panels.settings.analysis,
      carsPanel: panels.settings.cars.list,
      speedSourcePanel: panels.settings.speedSource,
    },
    ports: {
      openCarWizard: () => {
        carsFeature?.openWizard();
      },
      activeViewId: runtime.navigation.activeViewId,
      view: runtime.view,
    },
    services,
    formatting: {
      fmt: formatting.fmt,
    },
    queryClient: serverState.queryClient,
  });

  const cars: CarsFeature = createCarsFeature({
    panel: panels.settings.cars.wizard,
    services: {
      t: services.t,
    },
    formatting: {
      fmt: formatting.fmt,
    },
    queryClient: serverState.queryClient,
    addCarFromWizard: (name, carType, aspects, variant) =>
      settings.addCarFromWizard(name, carType, aspects, variant),
  });
  carsFeature = cars;

  const update = createUpdateFeature({
    panels: {
      update: panels.settings.update,
      internet: panels.settings.internet,
    },
    ports: {
      activeViewId: runtime.navigation.activeViewId,
      activeSettingsTabId: panels.settingsShell.activeTabId,
    },
    services,
    queryClient: serverState.queryClient,
  });
  const espFlash = createEspFlashFeature({
    panel: panels.settings.espFlash,
    ports: {
      activeViewId: runtime.navigation.activeViewId,
      activeSettingsTabId: panels.settingsShell.activeTabId,
    },
    services,
    queryClient: serverState.queryClient,
  });

  return createAppFeatureBundlePorts({
    history,
    realtime,
    settings,
    cars,
    update,
    espFlash,
  });
}

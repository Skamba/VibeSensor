import type { UiPanelHostRegistry } from "./ui_panel_host_registry";
import {
  mountDashboardPanels,
  mountHistoryPanelLazy,
  mountSettingsPanelsLazy,
  type UiMountedDashboardPanels,
  type UiMountedLazyPanels,
  type UiMountedPanels,
} from "./ui_panel_bootstrap";
import { effect, signal } from "./ui_signals";
import type { AnalysisPanelView } from "./views/analysis_panel";
import type { CarsPanelView } from "./views/cars_panel";
import type { EspFlashPanelView } from "./views/esp_flash_panel";
import type { HistoryPanelView } from "./views/history_table_view";
import type { InternetPanelView } from "./views/internet_panel";
import type { SensorsPanelView } from "./views/sensors_panel";
import type { SettingsShellView } from "./views/settings_shell";
import type { SpeedSourcePanelView } from "./views/speed_source_panel";
import type { UpdatePanelView } from "./views/update_panel";

const HISTORY_VIEW_ID = "historyView";
const SETTINGS_VIEW_ID = "settingsView";
const DEFAULT_SETTINGS_TAB_ID = "carTab";

type DeferredWorkScheduler = (task: () => void) => void;

export interface UiLazyPanels {
  panels: UiMountedPanels;
  ensureViewPanels(viewId: string): Promise<void>;
  prefetchHiddenPanels(): void;
}

export interface CreateUiLazyPanelsDeps {
  hosts: UiPanelHostRegistry;
  mountDashboardPanels?: (hosts: UiPanelHostRegistry) => UiMountedDashboardPanels;
  loadHistoryPanel?: (hosts: UiPanelHostRegistry) => Promise<HistoryPanelView>;
  loadSettingsPanels?: (hosts: UiPanelHostRegistry) => Promise<UiMountedLazyPanels>;
  scheduleDeferredWork?: DeferredWorkScheduler;
}

function scheduleDeferredWork(task: () => void): void {
  setTimeout(task, 0);
}

function createDeferredHistoryPanelView(): {
  attach(realView: HistoryPanelView): void;
  view: HistoryPanelView;
} {
  type HistoryModel = Parameters<HistoryPanelView["bindModel"]>[0];
  type HistoryActions = Parameters<HistoryPanelView["bindActions"]>[0];

  let actions: HistoryActions | null = null;
  let model: HistoryModel | null = null;
  let realView: HistoryPanelView | null = null;

  return {
    view: {
      bindModel(nextModel) {
        model = nextModel;
        realView?.bindModel(nextModel);
      },
      bindActions(nextActions) {
        actions = nextActions;
        realView?.bindActions(nextActions);
      },
    },
    attach(nextRealView) {
      realView = nextRealView;
      if (model !== null) {
        realView.bindModel(model);
      }
      if (actions !== null) {
        realView.bindActions(actions);
      }
    },
  };
}

function createDeferredSettingsShellView(): {
  attach(realView: SettingsShellView): void;
  view: SettingsShellView;
} {
  let disposeRealViewSubscription: (() => void) | null = null;
  let realView: SettingsShellView | null = null;
  const activeTabId = signal(DEFAULT_SETTINGS_TAB_ID);

  return {
    view: {
      activateTab(tabId) {
        activeTabId.value = tabId;
        realView?.activateTab(tabId);
      },
      getActiveTabId() {
        return activeTabId.value;
      },
      subscribeActiveTabChanges(listener) {
        let initialized = false;
        return effect(() => {
          const nextTabId = activeTabId.value;
          if (!initialized) {
            initialized = true;
            return;
          }
          listener(nextTabId);
        });
      },
    },
    attach(nextRealView) {
      disposeRealViewSubscription?.();
      realView = nextRealView;
      realView.activateTab(activeTabId.value);
      activeTabId.value = realView.getActiveTabId();
      disposeRealViewSubscription = realView.subscribeActiveTabChanges((nextTabId) => {
        activeTabId.value = nextTabId;
      });
    },
  };
}

function createDeferredCarsPanelView(): {
  attach(realView: CarsPanelView): void;
  view: CarsPanelView;
} {
  type CarsListActions = Parameters<CarsPanelView["list"]["bindActions"]>[0];
  type CarsListModel = Parameters<CarsPanelView["list"]["bindModel"]>[0];
  type CarsWizardActions = Parameters<CarsPanelView["wizard"]["bindActions"]>[0];
  type CarsWizardFocusTarget = Parameters<CarsPanelView["wizard"]["focus"]>[0];
  type CarsWizardModel = Parameters<CarsPanelView["wizard"]["bindModel"]>[0];

  let listActions: CarsListActions | null = null;
  let listModel: CarsListModel | null = null;
  let realView: CarsPanelView | null = null;
  let wizardActions: CarsWizardActions | null = null;
  let wizardFocusTarget: CarsWizardFocusTarget | null = null;
  let wizardModel: CarsWizardModel | null = null;

  return {
    view: {
      list: {
        bindModel(nextModel) {
          listModel = nextModel;
          realView?.list.bindModel(nextModel);
        },
        bindActions(nextActions) {
          listActions = nextActions;
          realView?.list.bindActions(nextActions);
        },
      },
      wizard: {
        bindModel(nextModel) {
          wizardModel = nextModel;
          realView?.wizard.bindModel(nextModel);
        },
        bindActions(nextActions) {
          wizardActions = nextActions;
          realView?.wizard.bindActions(nextActions);
        },
        focus(target) {
          wizardFocusTarget = target;
          realView?.wizard.focus(target);
          if (realView !== null) {
            wizardFocusTarget = null;
          }
        },
      },
    },
    attach(nextRealView) {
      realView = nextRealView;
      if (listModel !== null) {
        realView.list.bindModel(listModel);
      }
      if (listActions !== null) {
        realView.list.bindActions(listActions);
      }
      if (wizardModel !== null) {
        realView.wizard.bindModel(wizardModel);
      }
      if (wizardActions !== null) {
        realView.wizard.bindActions(wizardActions);
      }
      if (wizardFocusTarget !== null) {
        realView.wizard.focus(wizardFocusTarget);
        wizardFocusTarget = null;
      }
    },
  };
}

function createDeferredAnalysisPanelView(): {
  attach(realView: AnalysisPanelView): void;
  view: AnalysisPanelView;
} {
  type AnalysisActions = Parameters<AnalysisPanelView["bindActions"]>[0];
  type AnalysisCarAvailability = Parameters<AnalysisPanelView["bindCarAvailability"]>[0];
  type AnalysisFocusField = Parameters<AnalysisPanelView["focusField"]>[0];
  type AnalysisModel = Parameters<AnalysisPanelView["bindModel"]>[0];

  let actions: AnalysisActions | null = null;
  let carAvailability: AnalysisCarAvailability | null = null;
  let focusField: AnalysisFocusField | null = null;
  let guidanceOpenRequested = false;
  let model: AnalysisModel | null = null;
  let realView: AnalysisPanelView | null = null;

  return {
    view: {
      bindModel(nextModel) {
        model = nextModel;
        realView?.bindModel(nextModel);
      },
      bindActions(nextActions) {
        actions = nextActions;
        realView?.bindActions(nextActions);
      },
      bindCarAvailability(nextCarAvailability) {
        carAvailability = nextCarAvailability;
        realView?.bindCarAvailability(nextCarAvailability);
      },
      openGuidance() {
        guidanceOpenRequested = true;
        realView?.openGuidance();
        if (realView !== null) {
          guidanceOpenRequested = false;
        }
      },
      focusField(nextFocusField) {
        focusField = nextFocusField;
        realView?.focusField(nextFocusField);
        if (realView !== null) {
          focusField = null;
        }
      },
    },
    attach(nextRealView) {
      realView = nextRealView;
      if (model !== null) {
        realView.bindModel(model);
      }
      if (actions !== null) {
        realView.bindActions(actions);
      }
      if (carAvailability !== null) {
        realView.bindCarAvailability(carAvailability);
      }
      if (guidanceOpenRequested) {
        realView.openGuidance();
        guidanceOpenRequested = false;
      }
      if (focusField !== null) {
        realView.focusField(focusField);
        focusField = null;
      }
    },
  };
}

function createDeferredSensorsPanelView(): {
  attach(realView: SensorsPanelView): void;
  view: SensorsPanelView;
} {
  type SensorsActions = Parameters<SensorsPanelView["bindActions"]>[0];
  type SensorsModel = Parameters<SensorsPanelView["bindModel"]>[0];

  let actions: SensorsActions | null = null;
  let model: SensorsModel | null = null;
  let realView: SensorsPanelView | null = null;

  return {
    view: {
      bindModel(nextModel) {
        model = nextModel;
        realView?.bindModel(nextModel);
      },
      bindActions(nextActions) {
        actions = nextActions;
        realView?.bindActions(nextActions);
      },
    },
    attach(nextRealView) {
      realView = nextRealView;
      if (model !== null) {
        realView.bindModel(model);
      }
      if (actions !== null) {
        realView.bindActions(actions);
      }
    },
  };
}

function createDeferredSpeedSourcePanelView(): {
  attach(realView: SpeedSourcePanelView): void;
  view: SpeedSourcePanelView;
} {
  type SpeedSourceActions = Parameters<SpeedSourcePanelView["bindActions"]>[0];
  type SpeedSourceDiagnostics = Parameters<SpeedSourcePanelView["bindDiagnostics"]>[0];
  type SpeedSourceModel = Parameters<SpeedSourcePanelView["bindModel"]>[0];
  type PendingFocusTarget = "manual" | "scan" | "stale";

  let actions: SpeedSourceActions | null = null;
  let diagnostics: SpeedSourceDiagnostics | null = null;
  let model: SpeedSourceModel | null = null;
  let pendingFocusTarget: PendingFocusTarget | null = null;
  let realView: SpeedSourcePanelView | null = null;

  const flushPendingFocusTarget = (): void => {
    if (realView === null || pendingFocusTarget === null) {
      return;
    }
    if (pendingFocusTarget === "manual") {
      realView.focusManualSpeedInput();
    } else if (pendingFocusTarget === "scan") {
      realView.focusScanObdDevices();
    } else {
      realView.focusStaleTimeoutInput();
    }
    pendingFocusTarget = null;
  };

  return {
    view: {
      bindModel(nextModel) {
        model = nextModel;
        realView?.bindModel(nextModel);
      },
      bindActions(nextActions) {
        actions = nextActions;
        realView?.bindActions(nextActions);
      },
      bindDiagnostics(nextDiagnostics) {
        diagnostics = nextDiagnostics;
        realView?.bindDiagnostics(nextDiagnostics);
      },
      focusManualSpeedInput() {
        pendingFocusTarget = "manual";
        flushPendingFocusTarget();
      },
      focusScanObdDevices() {
        pendingFocusTarget = "scan";
        flushPendingFocusTarget();
      },
      focusStaleTimeoutInput() {
        pendingFocusTarget = "stale";
        flushPendingFocusTarget();
      },
      isObdConfigVisible() {
        if (realView !== null) {
          return realView.isObdConfigVisible();
        }
        return model?.value.obdConfigVisible ?? false;
      },
    },
    attach(nextRealView) {
      realView = nextRealView;
      if (model !== null) {
        realView.bindModel(model);
      }
      if (actions !== null) {
        realView.bindActions(actions);
      }
      if (diagnostics !== null) {
        realView.bindDiagnostics(diagnostics);
      }
      flushPendingFocusTarget();
    },
  };
}

function createDeferredUpdatePanelView(): {
  attach(realView: UpdatePanelView): void;
  view: UpdatePanelView;
} {
  type UpdateActions = Parameters<UpdatePanelView["bindActions"]>[0];
  type UpdateModel = Parameters<UpdatePanelView["bindModel"]>[0];

  let actions: UpdateActions | null = null;
  let model: UpdateModel | null = null;
  let realView: UpdatePanelView | null = null;

  return {
    view: {
      bindModel(nextModel) {
        model = nextModel;
        realView?.bindModel(nextModel);
      },
      bindActions(nextActions) {
        actions = nextActions;
        realView?.bindActions(nextActions);
      },
    },
    attach(nextRealView) {
      realView = nextRealView;
      if (model !== null) {
        realView.bindModel(model);
      }
      if (actions !== null) {
        realView.bindActions(actions);
      }
    },
  };
}

function createDeferredInternetPanelView(): {
  attach(realView: InternetPanelView): void;
  view: InternetPanelView;
} {
  type InternetActions = Parameters<InternetPanelView["bindActions"]>[0];
  type InternetModel = Parameters<InternetPanelView["bindModel"]>[0];

  let actions: InternetActions | null = null;
  let focusSsidRequested = false;
  let model: InternetModel | null = null;
  let realView: InternetPanelView | null = null;

  return {
    view: {
      bindModel(nextModel) {
        model = nextModel;
        realView?.bindModel(nextModel);
      },
      bindActions(nextActions) {
        actions = nextActions;
        realView?.bindActions(nextActions);
      },
      focusSsidInput() {
        focusSsidRequested = true;
        realView?.focusSsidInput();
        if (realView !== null) {
          focusSsidRequested = false;
        }
      },
    },
    attach(nextRealView) {
      realView = nextRealView;
      if (model !== null) {
        realView.bindModel(model);
      }
      if (actions !== null) {
        realView.bindActions(actions);
      }
      if (focusSsidRequested) {
        realView.focusSsidInput();
        focusSsidRequested = false;
      }
    },
  };
}

function createDeferredEspFlashPanelView(): {
  attach(realView: EspFlashPanelView): void;
  view: EspFlashPanelView;
} {
  type EspFlashActions = Parameters<EspFlashPanelView["bindActions"]>[0];
  type EspFlashModel = Parameters<EspFlashPanelView["bindModel"]>[0];

  let actions: EspFlashActions | null = null;
  let model: EspFlashModel | null = null;
  let realView: EspFlashPanelView | null = null;

  return {
    view: {
      bindModel(nextModel) {
        model = nextModel;
        realView?.bindModel(nextModel);
      },
      bindActions(nextActions) {
        actions = nextActions;
        realView?.bindActions(nextActions);
      },
    },
    attach(nextRealView) {
      realView = nextRealView;
      if (model !== null) {
        realView.bindModel(model);
      }
      if (actions !== null) {
        realView.bindActions(actions);
      }
    },
  };
}

export function createLazyUiPanels(deps: CreateUiLazyPanelsDeps): UiLazyPanels {
  const { hosts } = deps;
  const dashboard = (deps.mountDashboardPanels ?? mountDashboardPanels)(hosts);
  const history = createDeferredHistoryPanelView();
  const settingsShell = createDeferredSettingsShellView();
  const settings = {
    analysis: createDeferredAnalysisPanelView(),
    cars: createDeferredCarsPanelView(),
    espFlash: createDeferredEspFlashPanelView(),
    internet: createDeferredInternetPanelView(),
    sensors: createDeferredSensorsPanelView(),
    speedSource: createDeferredSpeedSourcePanelView(),
    update: createDeferredUpdatePanelView(),
  };
  let historyMountPromise: Promise<void> | null = null;
  let settingsMountPromise: Promise<void> | null = null;

  const attachSettingsPanels = (mountedPanels: UiMountedLazyPanels): void => {
    settingsShell.attach(mountedPanels.settingsShell);
    settings.cars.attach(mountedPanels.settings.cars);
    settings.analysis.attach(mountedPanels.settings.analysis);
    settings.internet.attach(mountedPanels.settings.internet);
    settings.update.attach(mountedPanels.settings.update);
    settings.sensors.attach(mountedPanels.settings.sensors);
    settings.speedSource.attach(mountedPanels.settings.speedSource);
    settings.espFlash.attach(mountedPanels.settings.espFlash);
  };

  const ensureHistoryMounted = (): Promise<void> => {
    if (historyMountPromise === null) {
      historyMountPromise = (deps.loadHistoryPanel ?? mountHistoryPanelLazy)(hosts).then(
        (realView) => {
          history.attach(realView);
        },
      );
    }
    return historyMountPromise;
  };

  const ensureSettingsMounted = (): Promise<void> => {
    if (settingsMountPromise === null) {
      settingsMountPromise = (deps.loadSettingsPanels ?? mountSettingsPanelsLazy)(hosts).then(
        (mountedPanels) => {
          attachSettingsPanels(mountedPanels);
        },
      );
    }
    return settingsMountPromise;
  };

  return {
    panels: {
      dashboard,
      history: history.view,
      settingsShell: settingsShell.view,
      settings: {
        analysis: settings.analysis.view,
        cars: settings.cars.view,
        espFlash: settings.espFlash.view,
        internet: settings.internet.view,
        sensors: settings.sensors.view,
        speedSource: settings.speedSource.view,
        update: settings.update.view,
      },
    },
    ensureViewPanels(viewId) {
      if (viewId === HISTORY_VIEW_ID) {
        return ensureHistoryMounted();
      }
      if (viewId === SETTINGS_VIEW_ID) {
        return ensureSettingsMounted();
      }
      return Promise.resolve();
    },
    prefetchHiddenPanels() {
      (deps.scheduleDeferredWork ?? scheduleDeferredWork)(() => {
        void ensureHistoryMounted();
        void ensureSettingsMounted();
      });
    },
  };
}

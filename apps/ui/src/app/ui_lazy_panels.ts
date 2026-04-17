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

function createDeferredBindSlot<TView extends object, TArg>(
  realView: { value: TView | null },
  apply: (view: TView, arg: TArg) => void,
): {
  bind(nextArg: TArg): void;
  current: { value: TArg | null };
} {
  const current = signal<TArg | null>(null);
  effect(() => {
    const view = realView.value;
    const nextArg = current.value;
    if (view !== null && nextArg !== null) {
      apply(view, nextArg);
    }
  });
  return {
    bind(nextArg) {
      current.value = nextArg;
    },
    current,
  };
}

function createDeferredModelActionView<
  TModel,
  TActions,
  TView extends {
    bindActions(actions: TActions): void;
    bindModel(model: TModel): void;
  },
>(): {
  attach(realView: TView): void;
  view: TView;
} {
  const realView = signal<TView | null>(null);
  const actions = createDeferredBindSlot(realView, (view, nextActions: TActions) => {
    view.bindActions(nextActions);
  });
  const model = createDeferredBindSlot(realView, (view, nextModel: TModel) => {
    view.bindModel(nextModel);
  });

  return {
    view: {
      bindActions(nextActions) {
        actions.bind(nextActions);
      },
      bindModel(nextModel) {
        model.bind(nextModel);
      },
    } as TView,
    attach(nextRealView) {
      realView.value = nextRealView;
    },
  };
}

function createDeferredHistoryPanelView(): {
  attach(realView: HistoryPanelView): void;
  view: HistoryPanelView;
} {
  return createDeferredModelActionView<
    Parameters<HistoryPanelView["bindModel"]>[0],
    Parameters<HistoryPanelView["bindActions"]>[0],
    HistoryPanelView
  >();
}

function createDeferredSettingsShellView(): {
  attach(realView: SettingsShellView): void;
  view: SettingsShellView;
} {
  let disposeRealViewSync: (() => void) | null = null;
  let realView: SettingsShellView | null = null;
  const activeTabId = signal(DEFAULT_SETTINGS_TAB_ID);

  return {
    view: {
      activeTabId,
      activateTab(tabId) {
        activeTabId.value = tabId;
        realView?.activateTab(tabId);
      },
    },
    attach(nextRealView) {
      disposeRealViewSync?.();
      realView = nextRealView;
      realView.activateTab(activeTabId.value);
      activeTabId.value = realView.activeTabId.value;
      disposeRealViewSync = effect(() => {
        activeTabId.value = nextRealView.activeTabId.value;
      });
    },
  };
}

function createDeferredCarsPanelView(): {
  attach(realView: CarsPanelView): void;
  view: CarsPanelView;
} {
  type CarsWizardFocusTarget = Parameters<CarsPanelView["wizard"]["focus"]>[0];
  const list = createDeferredModelActionView<
    Parameters<CarsPanelView["list"]["bindModel"]>[0],
    Parameters<CarsPanelView["list"]["bindActions"]>[0],
    CarsPanelView["list"]
  >();
  const realWizard = signal<CarsPanelView["wizard"] | null>(null);
  const wizardActions = createDeferredBindSlot(realWizard, (view, nextActions: Parameters<CarsPanelView["wizard"]["bindActions"]>[0]) => {
    view.bindActions(nextActions);
  });
  const wizardModel = createDeferredBindSlot(realWizard, (view, nextModel: Parameters<CarsPanelView["wizard"]["bindModel"]>[0]) => {
    view.bindModel(nextModel);
  });
  const wizardFocusTarget = signal<CarsWizardFocusTarget | null>(null);
  effect(() => {
    const view = realWizard.value;
    const target = wizardFocusTarget.value;
    if (view !== null && target !== null) {
      view.focus(target);
      wizardFocusTarget.value = null;
    }
  });

  return {
    view: {
      list: list.view,
      wizard: {
        bindActions(nextActions) {
          wizardActions.bind(nextActions);
        },
        bindModel(nextModel) {
          wizardModel.bind(nextModel);
        },
        focus(target) {
          wizardFocusTarget.value = target;
        },
      },
    },
    attach(nextRealView) {
      list.attach(nextRealView.list);
      realWizard.value = nextRealView.wizard;
    },
  };
}

function createDeferredAnalysisPanelView(): {
  attach(realView: AnalysisPanelView): void;
  view: AnalysisPanelView;
} {
  type AnalysisFocusField = Parameters<AnalysisPanelView["focusField"]>[0];
  const realView = signal<AnalysisPanelView | null>(null);
  const actions = createDeferredBindSlot(realView, (view, nextActions: Parameters<AnalysisPanelView["bindActions"]>[0]) => {
    view.bindActions(nextActions);
  });
  const carAvailability = createDeferredBindSlot(realView, (view, nextCarAvailability: Parameters<AnalysisPanelView["bindCarAvailability"]>[0]) => {
    view.bindCarAvailability(nextCarAvailability);
  });
  const model = createDeferredBindSlot(realView, (view, nextModel: Parameters<AnalysisPanelView["bindModel"]>[0]) => {
    view.bindModel(nextModel);
  });
  const focusField = signal<AnalysisFocusField | null>(null);
  const guidanceOpenRequested = signal(false);
  effect(() => {
    const view = realView.value;
    if (view !== null && guidanceOpenRequested.value) {
      view.openGuidance();
      guidanceOpenRequested.value = false;
    }
  });
  effect(() => {
    const view = realView.value;
    const nextFocusField = focusField.value;
    if (view !== null && nextFocusField !== null) {
      view.focusField(nextFocusField);
      focusField.value = null;
    }
  });

  return {
    view: {
      bindActions(nextActions) {
        actions.bind(nextActions);
      },
      bindCarAvailability(nextCarAvailability) {
        carAvailability.bind(nextCarAvailability);
      },
      bindModel(nextModel) {
        model.bind(nextModel);
      },
      openGuidance() {
        guidanceOpenRequested.value = true;
      },
      focusField(nextFocusField) {
        focusField.value = nextFocusField;
      },
    },
    attach(nextRealView) {
      realView.value = nextRealView;
    },
  };
}

function createDeferredSensorsPanelView(): {
  attach(realView: SensorsPanelView): void;
  view: SensorsPanelView;
} {
  return createDeferredModelActionView<
    Parameters<SensorsPanelView["bindModel"]>[0],
    Parameters<SensorsPanelView["bindActions"]>[0],
    SensorsPanelView
  >();
}

function createDeferredSpeedSourcePanelView(): {
  attach(realView: SpeedSourcePanelView): void;
  view: SpeedSourcePanelView;
} {
  type PendingFocusTarget = "manual" | "scan" | "stale";
  const realView = signal<SpeedSourcePanelView | null>(null);
  const actions = createDeferredBindSlot(realView, (view, nextActions: Parameters<SpeedSourcePanelView["bindActions"]>[0]) => {
    view.bindActions(nextActions);
  });
  const diagnostics = createDeferredBindSlot(realView, (view, nextDiagnostics: Parameters<SpeedSourcePanelView["bindDiagnostics"]>[0]) => {
    view.bindDiagnostics(nextDiagnostics);
  });
  const model = createDeferredBindSlot(realView, (view, nextModel: Parameters<SpeedSourcePanelView["bindModel"]>[0]) => {
    view.bindModel(nextModel);
  });
  const pendingFocusTarget = signal<PendingFocusTarget | null>(null);
  effect(() => {
    const view = realView.value;
    const target = pendingFocusTarget.value;
    if (view === null || target === null) {
      return;
    }
    if (target === "manual") {
      view.focusManualSpeedInput();
    } else if (target === "scan") {
      view.focusScanObdDevices();
    } else {
      view.focusStaleTimeoutInput();
    }
    pendingFocusTarget.value = null;
  });

  return {
    view: {
      bindActions(nextActions) {
        actions.bind(nextActions);
      },
      bindDiagnostics(nextDiagnostics) {
        diagnostics.bind(nextDiagnostics);
      },
      bindModel(nextModel) {
        model.bind(nextModel);
      },
      focusManualSpeedInput() {
        pendingFocusTarget.value = "manual";
      },
      focusScanObdDevices() {
        pendingFocusTarget.value = "scan";
      },
      focusStaleTimeoutInput() {
        pendingFocusTarget.value = "stale";
      },
      isObdConfigVisible() {
        const attachedView = realView.value;
        if (attachedView !== null) {
          return attachedView.isObdConfigVisible();
        }
        return model.current.value?.value.obdConfigVisible ?? false;
      },
    },
    attach(nextRealView) {
      realView.value = nextRealView;
    },
  };
}

function createDeferredUpdatePanelView(): {
  attach(realView: UpdatePanelView): void;
  view: UpdatePanelView;
} {
  return createDeferredModelActionView<
    Parameters<UpdatePanelView["bindModel"]>[0],
    Parameters<UpdatePanelView["bindActions"]>[0],
    UpdatePanelView
  >();
}

function createDeferredInternetPanelView(): {
  attach(realView: InternetPanelView): void;
  view: InternetPanelView;
} {
  const realView = signal<InternetPanelView | null>(null);
  const actions = createDeferredBindSlot(realView, (view, nextActions: Parameters<InternetPanelView["bindActions"]>[0]) => {
    view.bindActions(nextActions);
  });
  const model = createDeferredBindSlot(realView, (view, nextModel: Parameters<InternetPanelView["bindModel"]>[0]) => {
    view.bindModel(nextModel);
  });
  const focusSsidRequested = signal(false);
  effect(() => {
    const view = realView.value;
    if (view !== null && focusSsidRequested.value) {
      view.focusSsidInput();
      focusSsidRequested.value = false;
    }
  });

  return {
    view: {
      bindActions(nextActions) {
        actions.bind(nextActions);
      },
      bindModel(nextModel) {
        model.bind(nextModel);
      },
      focusSsidInput() {
        focusSsidRequested.value = true;
      },
    },
    attach(nextRealView) {
      realView.value = nextRealView;
    },
  };
}

function createDeferredEspFlashPanelView(): {
  attach(realView: EspFlashPanelView): void;
  view: EspFlashPanelView;
} {
  return createDeferredModelActionView<
    Parameters<EspFlashPanelView["bindModel"]>[0],
    Parameters<EspFlashPanelView["bindActions"]>[0],
    EspFlashPanelView
  >();
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

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
type SingleArgVoidMethodKey<TView extends object> = Extract<{
  [K in keyof TView]: TView[K] extends (arg: infer _TArg) => void ? K : never;
}[keyof TView], keyof TView>;
type SingleArgMethodArg<
  TView extends object,
  TMethodName extends SingleArgVoidMethodKey<TView>,
> = TView[TMethodName] extends (arg: infer TArg) => void ? TArg : never;

interface DeferredViewContext<
  TView extends object,
  TBindMethodName extends SingleArgVoidMethodKey<TView>,
> {
  getPendingArg<TMethodName extends TBindMethodName>(
    methodName: TMethodName,
  ): SingleArgMethodArg<TView, TMethodName> | null;
  getRealView(): TView | null;
}

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

const DEFERRED_MODEL_ACTION_METHOD_NAMES = ["bindModel", "bindActions"] as const;
const DEFERRED_ANALYSIS_METHOD_NAMES = ["bindModel", "bindActions", "bindCarAvailability"] as const;
const DEFERRED_SPEED_SOURCE_METHOD_NAMES = ["bindModel", "bindActions", "bindDiagnostics"] as const;

function createDeferredView<
  TView extends object,
  const TBindMethodNames extends readonly SingleArgVoidMethodKey<TView>[],
>(config: {
  bindMethodNames: TBindMethodNames;
  createExtraView?: (
    context: DeferredViewContext<TView, TBindMethodNames[number]>,
  ) => Omit<TView, TBindMethodNames[number]>;
  onRealViewSet?: (
    realView: TView,
    context: DeferredViewContext<TView, TBindMethodNames[number]>,
  ) => void;
}): {
  attach(realView: TView): void;
  view: TView;
} {
  type TBindMethodName = TBindMethodNames[number];

  let realView: TView | null = null;
  const pendingArgs = new Map<TBindMethodName, unknown>();
  const context: DeferredViewContext<TView, TBindMethodName> = {
    getPendingArg(methodName) {
      if (!pendingArgs.has(methodName)) {
        return null;
      }
      return pendingArgs.get(methodName) as SingleArgMethodArg<TView, typeof methodName>;
    },
    getRealView() {
      return realView;
    },
  };
  const boundView = {} as Pick<TView, TBindMethodName>;
  for (const methodName of config.bindMethodNames) {
    const bindMethod = ((nextArg: SingleArgMethodArg<TView, typeof methodName>) => {
      pendingArgs.set(methodName, nextArg);
      if (realView !== null) {
        (realView[methodName] as (arg: SingleArgMethodArg<TView, typeof methodName>) => void)(nextArg);
      }
    }) as TView[typeof methodName];
    boundView[methodName] = bindMethod;
  }
  const view = {
    ...boundView,
    ...(config.createExtraView?.(context) ?? {}),
  } as TView;

  return {
    view,
    attach(nextRealView) {
      realView = nextRealView;
      for (const methodName of config.bindMethodNames) {
        if (!pendingArgs.has(methodName)) {
          continue;
        }
        const nextArg = pendingArgs.get(methodName) as SingleArgMethodArg<TView, typeof methodName>;
        (nextRealView[methodName] as (arg: typeof nextArg) => void)(nextArg);
      }
      config.onRealViewSet?.(nextRealView, context);
    },
  };
}

function createDeferredHistoryPanelView(): {
  attach(realView: HistoryPanelView): void;
  view: HistoryPanelView;
} {
  return createDeferredView<HistoryPanelView, typeof DEFERRED_MODEL_ACTION_METHOD_NAMES>({
    bindMethodNames: DEFERRED_MODEL_ACTION_METHOD_NAMES,
  });
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
  type CarsWizardFocusTarget = Parameters<CarsPanelView["wizard"]["focus"]>[0];
  const list = createDeferredView<CarsPanelView["list"], typeof DEFERRED_MODEL_ACTION_METHOD_NAMES>({
    bindMethodNames: DEFERRED_MODEL_ACTION_METHOD_NAMES,
  });
  let wizardFocusTarget: CarsWizardFocusTarget | null = null;
  const flushWizardFocusTarget = (realView: CarsPanelView["wizard"] | null): void => {
    if (realView === null || wizardFocusTarget === null) {
      return;
    }
    realView.focus(wizardFocusTarget);
    wizardFocusTarget = null;
  };
  const wizard = createDeferredView<CarsPanelView["wizard"], typeof DEFERRED_MODEL_ACTION_METHOD_NAMES>({
    bindMethodNames: DEFERRED_MODEL_ACTION_METHOD_NAMES,
    createExtraView(context) {
      return {
        focus(target) {
          wizardFocusTarget = target;
          flushWizardFocusTarget(context.getRealView());
        },
      };
    },
    onRealViewSet(realView) {
      flushWizardFocusTarget(realView);
    },
  });

  return {
    view: {
      list: list.view,
      wizard: wizard.view,
    },
    attach(nextRealView) {
      list.attach(nextRealView.list);
      wizard.attach(nextRealView.wizard);
    },
  };
}

function createDeferredAnalysisPanelView(): {
  attach(realView: AnalysisPanelView): void;
  view: AnalysisPanelView;
} {
  type AnalysisFocusField = Parameters<AnalysisPanelView["focusField"]>[0];
  let focusField: AnalysisFocusField | null = null;
  let guidanceOpenRequested = false;
  const flushPendingEffects = (realView: AnalysisPanelView | null): void => {
    if (realView === null) {
      return;
    }
    if (guidanceOpenRequested) {
      realView.openGuidance();
      guidanceOpenRequested = false;
    }
    if (focusField !== null) {
      realView.focusField(focusField);
      focusField = null;
    }
  };

  return createDeferredView<AnalysisPanelView, typeof DEFERRED_ANALYSIS_METHOD_NAMES>({
    bindMethodNames: DEFERRED_ANALYSIS_METHOD_NAMES,
    createExtraView(context) {
      return {
        openGuidance() {
          guidanceOpenRequested = true;
          flushPendingEffects(context.getRealView());
        },
        focusField(nextFocusField) {
          focusField = nextFocusField;
          flushPendingEffects(context.getRealView());
        },
      };
    },
    onRealViewSet(realView) {
      flushPendingEffects(realView);
    },
  });
}

function createDeferredSensorsPanelView(): {
  attach(realView: SensorsPanelView): void;
  view: SensorsPanelView;
} {
  return createDeferredView<SensorsPanelView, typeof DEFERRED_MODEL_ACTION_METHOD_NAMES>({
    bindMethodNames: DEFERRED_MODEL_ACTION_METHOD_NAMES,
  });
}

function createDeferredSpeedSourcePanelView(): {
  attach(realView: SpeedSourcePanelView): void;
  view: SpeedSourcePanelView;
} {
  type PendingFocusTarget = "manual" | "scan" | "stale";
  let pendingFocusTarget: PendingFocusTarget | null = null;
  const flushPendingFocusTarget = (realView: SpeedSourcePanelView | null): void => {
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

  return createDeferredView<SpeedSourcePanelView, typeof DEFERRED_SPEED_SOURCE_METHOD_NAMES>({
    bindMethodNames: DEFERRED_SPEED_SOURCE_METHOD_NAMES,
    createExtraView(context) {
      return {
        focusManualSpeedInput() {
          pendingFocusTarget = "manual";
          flushPendingFocusTarget(context.getRealView());
        },
        focusScanObdDevices() {
          pendingFocusTarget = "scan";
          flushPendingFocusTarget(context.getRealView());
        },
        focusStaleTimeoutInput() {
          pendingFocusTarget = "stale";
          flushPendingFocusTarget(context.getRealView());
        },
        isObdConfigVisible() {
          const realView = context.getRealView();
          if (realView !== null) {
            return realView.isObdConfigVisible();
          }
          return context.getPendingArg("bindModel")?.value.obdConfigVisible ?? false;
        },
      };
    },
    onRealViewSet(realView) {
      flushPendingFocusTarget(realView);
    },
  });
}

function createDeferredUpdatePanelView(): {
  attach(realView: UpdatePanelView): void;
  view: UpdatePanelView;
} {
  return createDeferredView<UpdatePanelView, typeof DEFERRED_MODEL_ACTION_METHOD_NAMES>({
    bindMethodNames: DEFERRED_MODEL_ACTION_METHOD_NAMES,
  });
}

function createDeferredInternetPanelView(): {
  attach(realView: InternetPanelView): void;
  view: InternetPanelView;
} {
  let focusSsidRequested = false;
  const flushPendingFocusSsid = (realView: InternetPanelView | null): void => {
    if (!focusSsidRequested || realView === null) {
      return;
    }
    realView.focusSsidInput();
    focusSsidRequested = false;
  };

  return createDeferredView<InternetPanelView, typeof DEFERRED_MODEL_ACTION_METHOD_NAMES>({
    bindMethodNames: DEFERRED_MODEL_ACTION_METHOD_NAMES,
    createExtraView(context) {
      return {
        focusSsidInput() {
          focusSsidRequested = true;
          flushPendingFocusSsid(context.getRealView());
        },
      };
    },
    onRealViewSet(realView) {
      flushPendingFocusSsid(realView);
    },
  });
}

function createDeferredEspFlashPanelView(): {
  attach(realView: EspFlashPanelView): void;
  view: EspFlashPanelView;
} {
  return createDeferredView<EspFlashPanelView, typeof DEFERRED_MODEL_ACTION_METHOD_NAMES>({
    bindMethodNames: DEFERRED_MODEL_ACTION_METHOD_NAMES,
  });
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

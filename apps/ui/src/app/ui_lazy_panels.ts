import type { UiPanelHostRegistry } from "./ui_panel_host_registry";
import {
  mountDashboardPanels,
  mountHistoryPanelLazy,
  mountSettingsPanelsLazy,
  type UiMountedDashboardPanels,
  type UiMountedLazyPanelHandles,
  type UiMountedPanels,
} from "./ui_panel_bootstrap";
import { effect, signal } from "./ui_signals";
import type {
  AnalysisPanelActionHandlers,
  AnalysisPanelCarAvailability,
  AnalysisPanelRenderModel,
  AnalysisPanelView,
} from "./views/analysis_panel";
import type {
  CarsFeatureInteractionHandlers,
  CarsListRenderModel,
  CarsPanelView,
} from "./views/cars_panel";
import type {
  EspFlashPanelActionHandlers,
  EspFlashPanelRenderModel,
  EspFlashPanelView,
} from "./views/esp_flash_panel";
import type {
  HistoryPanelActionHandlers,
  HistoryPanelRenderModel,
  HistoryPanelView,
} from "./views/history_table_view";
import type {
  InternetPanelActionHandlers,
  InternetPanelRenderModel,
  InternetPanelView,
} from "./views/internet_panel";
import type {
  SensorsPanelActionHandlers,
  SensorsPanelRenderModel,
  SensorsPanelView,
} from "./views/sensors_panel";
import type { SettingsShellView } from "./views/settings_shell";
import type {
  SpeedSourceDiagnosticsRenderModel,
  SpeedSourcePanelActionHandlers,
  SpeedSourcePanelRenderModel,
  SpeedSourcePanelView,
} from "./views/speed_source_panel";
import type {
  UpdatePanelActionHandlers,
  UpdatePanelRenderModel,
  UpdatePanelView,
} from "./views/update_panel";
import {
  createDeferredModelSignal,
  createModelActionPanelBindings,
} from "./views/view_model_binding";

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
  loadHistoryPanel?: (hosts: UiPanelHostRegistry, view: HistoryPanelView) => Promise<void>;
  loadSettingsPanels?: (
    hosts: UiPanelHostRegistry,
    panels: Pick<UiMountedPanels, "settings">,
  ) => Promise<UiMountedLazyPanelHandles>;
  scheduleDeferredWork?: DeferredWorkScheduler;
}

function scheduleDeferredWork(task: () => void): void {
  setTimeout(task, 0);
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
  attach(realView: Pick<CarsPanelView["wizard"], "focus">): void;
  view: CarsPanelView;
} {
  type CarsWizardFocusTarget = Parameters<CarsPanelView["wizard"]["focus"]>[0];
  const list = createModelActionPanelBindings<
    CarsListRenderModel,
    { onAction(action: import("./views/settings_car_list_view").CarsListAction): void }
  >();
  const wizard = createModelActionPanelBindings<
    import("./views/car_wizard_view").CarsWizardRenderModel,
    CarsFeatureInteractionHandlers
  >();
  const realWizard = signal<Pick<CarsPanelView["wizard"], "focus"> | null>(null);
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
      list,
      wizard: {
        actions: wizard.actions,
        model: wizard.model,
        focus(target) {
          wizardFocusTarget.value = target;
        },
      },
    },
    attach(nextRealView) {
      realWizard.value = nextRealView;
    },
  };
}

function createDeferredAnalysisPanelView(): {
  attach(realView: Pick<AnalysisPanelView, "focusField" | "openGuidance">): void;
  view: AnalysisPanelView;
} {
  type AnalysisFocusField = Parameters<AnalysisPanelView["focusField"]>[0];
  const realView = signal<Pick<AnalysisPanelView, "focusField" | "openGuidance"> | null>(null);
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
      actions: signal<AnalysisPanelActionHandlers | null>(null),
      carAvailability: createDeferredModelSignal<AnalysisPanelCarAvailability>(),
      model: createDeferredModelSignal<AnalysisPanelRenderModel>(),
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

function createDeferredSpeedSourcePanelView(): {
  attach(
    realView: Pick<
      SpeedSourcePanelView,
      "focusManualSpeedInput" | "focusScanObdDevices" | "focusStaleTimeoutInput"
    >,
  ): void;
  view: SpeedSourcePanelView;
} {
  type PendingFocusTarget = "manual" | "scan" | "stale";
  const realView = signal<Pick<
    SpeedSourcePanelView,
    "focusManualSpeedInput" | "focusScanObdDevices" | "focusStaleTimeoutInput"
  > | null>(null);
  const model = createDeferredModelSignal<SpeedSourcePanelRenderModel>();
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
      actions: signal<SpeedSourcePanelActionHandlers | null>(null),
      diagnostics: createDeferredModelSignal<SpeedSourceDiagnosticsRenderModel>(),
      model,
      isObdConfigVisible() {
        return model.value?.value.obdConfigVisible ?? false;
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
    },
    attach(nextRealView) {
      realView.value = nextRealView;
    },
  };
}

function createDeferredInternetPanelView(): {
  attach(realView: Pick<InternetPanelView, "focusSsidInput">): void;
  view: InternetPanelView;
} {
  const realView = signal<Pick<InternetPanelView, "focusSsidInput"> | null>(null);
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
      actions: signal<InternetPanelActionHandlers | null>(null),
      model: createDeferredModelSignal<InternetPanelRenderModel>(),
      focusSsidInput() {
        focusSsidRequested.value = true;
      },
    },
    attach(nextRealView) {
      realView.value = nextRealView;
    },
  };
}

export function createLazyUiPanels(deps: CreateUiLazyPanelsDeps): UiLazyPanels {
  const { hosts } = deps;
  const dashboard = (deps.mountDashboardPanels ?? mountDashboardPanels)(hosts);
  const history = {
    view: createModelActionPanelBindings<
      HistoryPanelRenderModel,
      HistoryPanelActionHandlers
    >(),
  };
  const settingsShell = createDeferredSettingsShellView();
  const settings = {
    analysis: createDeferredAnalysisPanelView(),
    cars: createDeferredCarsPanelView(),
    espFlash: {
      view: createModelActionPanelBindings<
        EspFlashPanelRenderModel,
        EspFlashPanelActionHandlers
      >(),
    },
    internet: createDeferredInternetPanelView(),
    sensors: {
      view: createModelActionPanelBindings<
        SensorsPanelRenderModel,
        SensorsPanelActionHandlers
      >(),
    },
    speedSource: createDeferredSpeedSourcePanelView(),
    update: {
      view: createModelActionPanelBindings<
        UpdatePanelRenderModel,
        UpdatePanelActionHandlers
      >(),
    },
  };
  let historyMountPromise: Promise<void> | null = null;
  let settingsMountPromise: Promise<void> | null = null;

  const attachSettingsPanels = (mountedPanels: UiMountedLazyPanelHandles): void => {
    settingsShell.attach(mountedPanels.settingsShell);
    settings.cars.attach(mountedPanels.settings.cars);
    settings.analysis.attach(mountedPanels.settings.analysis);
    settings.internet.attach(mountedPanels.settings.internet);
    settings.speedSource.attach(mountedPanels.settings.speedSource);
  };

  const ensureHistoryMounted = (): Promise<void> => {
    if (historyMountPromise === null) {
      historyMountPromise = (deps.loadHistoryPanel ?? mountHistoryPanelLazy)(hosts, history.view);
    }
    return historyMountPromise;
  };

  const ensureSettingsMounted = (): Promise<void> => {
    if (settingsMountPromise === null) {
        settingsMountPromise = (deps.loadSettingsPanels ?? mountSettingsPanelsLazy)(
          hosts,
          {
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
        ).then((mountedPanels) => {
          attachSettingsPanels(mountedPanels);
        });
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

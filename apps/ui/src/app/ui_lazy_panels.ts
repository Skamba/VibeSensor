import { effect, signal, type ReadonlySignal } from "./ui_signals";
import type { AnalysisPanelActionHandlers, AnalysisPanelCarAvailability, AnalysisPanelRenderModel, AnalysisPanelView } from "./views/analysis_panel";
import type { CarsFeatureInteractionHandlers, CarsListRenderModel, CarsPanelView } from "./views/cars_panel";
import type { EspFlashPanelActionHandlers, EspFlashPanelRenderModel, EspFlashPanelView } from "./views/esp_flash_panel";
import type { HistoryPanelActionHandlers, HistoryPanelRenderModel, HistoryPanelView } from "./views/history_table_view";
import type { InternetPanelActionHandlers, InternetPanelRenderModel, InternetPanelView } from "./views/internet_panel";
import { createSpectrumPanel, type CreatedSpectrumPanel } from "./views/spectrum_panel";
import type { SensorsPanelActionHandlers, SensorsPanelRenderModel, SensorsPanelView } from "./views/sensors_panel";
import type { SettingsShellView } from "./views/settings_shell";
import type { SpeedSourceDiagnosticsRenderModel, SpeedSourcePanelActionHandlers, SpeedSourcePanelRenderModel, SpeedSourcePanelView } from "./views/speed_source_panel";
import type { RealtimeLoggingPanelBridge, RealtimeLoggingPanelRenderModel, RealtimeLoggingPanelActionHandlers } from "./views/realtime_logging_panel";
import type { RealtimeLiveOverviewBridge, RealtimeLiveOverviewRenderModel } from "./views/realtime_live_overview";
import type { UpdatePanelActionHandlers, UpdatePanelRenderModel, UpdatePanelView } from "./views/update_panel";
import {
  createDeferredModelSignal,
  createModelActionPanelBindings,
  readDeferredModelValue,
} from "./views/view_model_binding";

const DEFAULT_SETTINGS_TAB_ID = "carTab";

type DeferredWorkScheduler = (task: () => void) => void;

export interface UiMountedDashboardPanels {
  spectrum: CreatedSpectrumPanel["view"];
  liveOverview: RealtimeLiveOverviewBridge;
  logging: RealtimeLoggingPanelBridge;
}

export interface UiMountedPanels {
  dashboard: UiMountedDashboardPanels;
  history: HistoryPanelView;
  settingsShell: SettingsShellView;
  settings: {
    analysis: AnalysisPanelView;
    cars: CarsPanelView;
    espFlash: EspFlashPanelView;
    internet: InternetPanelView;
    sensors: SensorsPanelView;
    speedSource: SpeedSourcePanelView;
    update: UpdatePanelView;
  };
}

export interface UiMountedLazyPanelHandles {
  settingsShell: SettingsShellView;
  settings: {
    analysis: Pick<AnalysisPanelView, "focusField" | "openGuidance">;
    cars: Pick<CarsPanelView["wizard"], "focus">;
    internet: Pick<InternetPanelView, "focusSsidInput">;
    speedSource: Pick<
      SpeedSourcePanelView,
      "focusManualSpeedInput" | "focusScanObdDevices" | "focusStaleTimeoutInput"
    >;
  };
}

export interface UiLazyPanels {
  attachSettingsPanels(mountedPanels: UiMountedLazyPanelHandles): void;
  panels: UiMountedPanels;
  prefetchHiddenPanels(): void;
  spectrumPanel: CreatedSpectrumPanel;
}

export interface CreateUiLazyPanelsDeps {
  preloadHistoryView?: () => Promise<unknown> | void;
  preloadSettingsView?: () => Promise<unknown> | void;
  scheduleDeferredWork?: DeferredWorkScheduler;
}

function scheduleDeferredWork(task: () => void): void {
  if (typeof globalThis.requestIdleCallback === "function") {
    globalThis.requestIdleCallback(() => {
      task();
    });
    return;
  }
  setTimeout(task, 0);
}

function preloadHistoryView(): Promise<unknown> {
  return import("./views/history_lazy_view");
}

function preloadSettingsView(): Promise<unknown> {
  return import("./views/settings_lazy_view");
}

function createDeferredTargetAction<TView, TTarget>(
  realView: ReadonlySignal<TView | null>,
  run: (view: TView, target: TTarget) => void,
): (target: TTarget) => void {
  const pendingTarget = signal<TTarget | null>(null);
  effect(() => {
    const view = realView.value;
    const target = pendingTarget.value;
    if (view === null || target === null) {
      return;
    }
    run(view, target);
    pendingTarget.value = null;
  });
  return (target) => {
    pendingTarget.value = target;
  };
}

function createDeferredAction<TView>(
  realView: ReadonlySignal<TView | null>,
  run: (view: TView) => void,
): () => void {
  const pending = signal(false);
  effect(() => {
    const view = realView.value;
    if (view === null || !pending.value) {
      return;
    }
    run(view);
    pending.value = false;
  });
  return () => {
    pending.value = true;
  };
}

function createDeferredViewAttachment<TView>(): {
  attach(nextRealView: TView): void;
  realView: ReadonlySignal<TView | null>;
} {
  const realView = signal<TView | null>(null);
  return {
    attach(nextRealView) {
      realView.value = nextRealView;
    },
    realView,
  };
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
  const realWizard = createDeferredViewAttachment<Pick<CarsPanelView["wizard"], "focus">>();
  const list = createModelActionPanelBindings<
    CarsListRenderModel,
    { onAction(action: import("./views/settings_car_list_view").CarsListAction): void }
  >();
  const wizard = createModelActionPanelBindings<
    import("./views/car_wizard_view").CarsWizardRenderModel,
    CarsFeatureInteractionHandlers
  >();
  const requestWizardFocus = createDeferredTargetAction(
    realWizard.realView,
    (view, target: CarsWizardFocusTarget) => {
      view.focus(target);
    },
  );

  return {
    view: {
      list,
      wizard: {
        actions: wizard.actions,
        model: wizard.model,
        focus(target) {
          requestWizardFocus(target);
        },
      },
    },
    attach: realWizard.attach,
  };
}

function createDeferredAnalysisPanelView(): {
  attach(realView: Pick<AnalysisPanelView, "focusField" | "openGuidance">): void;
  view: AnalysisPanelView;
} {
  type AnalysisFocusField = Parameters<AnalysisPanelView["focusField"]>[0];
  const realView = createDeferredViewAttachment<
    Pick<AnalysisPanelView, "focusField" | "openGuidance">
  >();
  const requestGuidanceOpen = createDeferredAction(realView.realView, (view) => {
    view.openGuidance();
  });
  const requestFocusField = createDeferredTargetAction(
    realView.realView,
    (view, nextFocusField: AnalysisFocusField) => {
      view.focusField(nextFocusField);
    },
  );

  return {
    view: {
      actions: signal<AnalysisPanelActionHandlers | null>(null),
      carAvailability: createDeferredModelSignal<AnalysisPanelCarAvailability>(),
      model: createDeferredModelSignal<AnalysisPanelRenderModel>(),
      openGuidance() {
        requestGuidanceOpen();
      },
      focusField(nextFocusField) {
        requestFocusField(nextFocusField);
      },
    },
    attach: realView.attach,
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
  const realView = createDeferredViewAttachment<
    Pick<
      SpeedSourcePanelView,
      "focusManualSpeedInput" | "focusScanObdDevices" | "focusStaleTimeoutInput"
    >
  >();
  const model = createDeferredModelSignal<SpeedSourcePanelRenderModel>();
  const requestFocusTarget = createDeferredTargetAction(
    realView.realView,
    (view, target: PendingFocusTarget) => {
      if (target === "manual") {
        view.focusManualSpeedInput();
      } else if (target === "scan") {
        view.focusScanObdDevices();
      } else {
        view.focusStaleTimeoutInput();
      }
    },
  );

  return {
    view: {
      actions: signal<SpeedSourcePanelActionHandlers | null>(null),
      diagnostics: createDeferredModelSignal<SpeedSourceDiagnosticsRenderModel>(),
      model,
      isObdConfigVisible() {
        return readDeferredModelValue(model)?.obdConfigVisible ?? false;
      },
      focusManualSpeedInput() {
        requestFocusTarget("manual");
      },
      focusScanObdDevices() {
        requestFocusTarget("scan");
      },
      focusStaleTimeoutInput() {
        requestFocusTarget("stale");
      },
    },
    attach: realView.attach,
  };
}

function createDeferredInternetPanelView(): {
  attach(realView: Pick<InternetPanelView, "focusSsidInput">): void;
  view: InternetPanelView;
} {
  const realView = createDeferredViewAttachment<Pick<InternetPanelView, "focusSsidInput">>();
  const requestSsidFocus = createDeferredAction(realView.realView, (view) => {
    view.focusSsidInput();
  });

  return {
    view: {
      actions: signal<InternetPanelActionHandlers | null>(null),
      model: createDeferredModelSignal<InternetPanelRenderModel>(),
      focusSsidInput() {
        requestSsidFocus();
      },
    },
    attach: realView.attach,
  };
}

export function createLazyUiPanels(deps: CreateUiLazyPanelsDeps = {}): UiLazyPanels {
  const history = {
    view: createModelActionPanelBindings<HistoryPanelRenderModel, HistoryPanelActionHandlers>(),
  };
  const settingsShell = createDeferredSettingsShellView();
  const settings = {
    analysis: createDeferredAnalysisPanelView(),
    cars: createDeferredCarsPanelView(),
    espFlash: {
      view: createModelActionPanelBindings<EspFlashPanelRenderModel, EspFlashPanelActionHandlers>(),
    },
    internet: createDeferredInternetPanelView(),
    sensors: {
      view: createModelActionPanelBindings<SensorsPanelRenderModel, SensorsPanelActionHandlers>(),
    },
    speedSource: createDeferredSpeedSourcePanelView(),
    update: {
      view: createModelActionPanelBindings<UpdatePanelRenderModel, UpdatePanelActionHandlers>(),
    },
  };
  const spectrumPanel = createSpectrumPanel();
  const dashboard = {
    spectrum: spectrumPanel.view,
    liveOverview: {
      model: createDeferredModelSignal<RealtimeLiveOverviewRenderModel>(),
      speedText: createDeferredModelSignal<string>(),
    } satisfies RealtimeLiveOverviewBridge,
    logging: createModelActionPanelBindings<
      RealtimeLoggingPanelRenderModel,
      RealtimeLoggingPanelActionHandlers
    >(),
  } satisfies UiMountedDashboardPanels;

  const attachSettingsPanels = (mountedPanels: UiMountedLazyPanelHandles): void => {
    settingsShell.attach(mountedPanels.settingsShell);
    settings.cars.attach(mountedPanels.settings.cars);
    settings.analysis.attach(mountedPanels.settings.analysis);
    settings.internet.attach(mountedPanels.settings.internet);
    settings.speedSource.attach(mountedPanels.settings.speedSource);
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
    attachSettingsPanels,
    prefetchHiddenPanels() {
      (deps.scheduleDeferredWork ?? scheduleDeferredWork)(() => {
        void (deps.preloadHistoryView ?? preloadHistoryView)();
        void (deps.preloadSettingsView ?? preloadSettingsView)();
      });
    },
    spectrumPanel,
  };
}

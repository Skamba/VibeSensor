import {
  activeView,
  isDemoMode,
  loadPreferences,
  navigate,
  onViewEnter,
  requestConfirmation,
  settingsTab,
  showError,
  speedUnit,
} from "../app_store";
import { fmt, fmtTs, formatIntLocale } from "../format";
import { t } from "../i18n";
import { uiLogger } from "../ui_logger";
import { createCarsFeature } from "./features/cars_feature";
import { loadDashboardStartupState } from "./features/dashboard_startup_state";
import { createHistoryFeature } from "./features/history_feature";
import { createRealtimeFeature } from "./features/realtime_feature";
import { createSettingsAnalysisModule } from "./features/settings_analysis_module";
import type { FeatureServices } from "./feature_deps_base";
import { UiLiveTransportController } from "./runtime/ui_live_transport_controller";
import { createUiQueryClient } from "./runtime/ui_query_client";
import { UiSpectrumController } from "./runtime/ui_spectrum_controller";
import { loadSpeedSource, speedSourceSnapshot } from "../settings_store";
import { deriveSpeedReadoutLabelKey } from "../speed_source";
import { createAppState } from "./ui_app_state";
import { computed, effectOnChange, signal } from "./ui_signals";
import {
  createAnalysisPanel,
  type AnalysisPanelBindings,
} from "./views/analysis_panel";
import {
  createCarsPanel,
  type CarsListPanelView,
  type CarsWizardPanelBridge,
} from "./views/cars_panel";
import type { HistoryPanelView } from "./views/history_table_view";
import type { RealtimeLiveOverviewBridge } from "./views/realtime_live_overview";
import type { RealtimeLoggingPanelBridge } from "./views/realtime_logging_panel";
import type { SensorsPanelView } from "./views/sensors_panel";
import { createSpectrumPanel } from "./views/spectrum_panel";
import type { VisualVariant } from "./visual_variant";
import {
  createDeferredModelSignal,
  createModelActionPanelBindings,
} from "./views/view_model_binding";

/**
 * Wires the pre-rewrite feature controllers to their panels. Each page
 * rewrite moves its feature out of here; the file goes away with the last one.
 */

export const appState = createAppState();
const { settings, realtime } = appState;

const services: FeatureServices = { t, showError, requestConfirmation };
const queryClient = createUiQueryClient();
queryClient.mount();

/** Run-health badge shown next to the link pill outside the dashboard. */
export const liveStatusBadge = signal<{ text: string; variant: VisualVariant }>(
  { text: "No live signal", variant: "muted" },
);

// --- Panel bindings -------------------------------------------------------

function bindings<T>(): T {
  return createModelActionPanelBindings() as T;
}

const analysisBindings: AnalysisPanelBindings = {
  actions: signal(null),
  carAvailability: createDeferredModelSignal(),
  model: createDeferredModelSignal(),
};
const analysisPanel = createAnalysisPanel(analysisBindings);
const carsBindings = {
  list: bindings<CarsListPanelView>(),
  wizard: bindings<Omit<CarsWizardPanelBridge, "focus">>(),
};
const carsPanel = createCarsPanel(carsBindings);
const spectrumPanel = createSpectrumPanel();

export const panels = {
  liveOverview: {
    model: createDeferredModelSignal(),
    speedText: createDeferredModelSignal(),
  } as RealtimeLiveOverviewBridge,
  logging: bindings<RealtimeLoggingPanelBridge>(),
  spectrum: spectrumPanel,
  history: bindings<HistoryPanelView>(),
  analysis: { ...analysisBindings, ...analysisPanel },
  cars: {
    list: carsBindings.list,
    wizard: { ...carsBindings.wizard, focus: carsPanel.focus },
    Panel: carsPanel.Panel,
  },
  sensors: bindings<SensorsPanelView>(),
};

// --- Controllers ------------------------------------------------------------

const spectrum = new UiSpectrumController({
  state: appState,
  panel: spectrumPanel.view,
  t,
});
const liveTransport = new UiLiveTransportController({
  state: appState,
  payloadErrorMessage: () => t("ws.payload_error"),
});
const formatting = {
  fmt,
  fmtTs,
  formatInt: (value: number) =>
    formatIntLocale(value, appState.shell.lang.value),
};

const history = createHistoryFeature({
  history: appState.history,
  shell: appState.shell,
  panel: panels.history,
  navigation: { activatePrimaryView: (view) => navigate(asView(view)) },
  services,
  formatting,
  queryClient,
});

const analysis = createSettingsAnalysisModule({
  panel: panels.analysis,
  settings,
  lang: appState.shell.lang,
  queryClient,
  services,
  refreshSpectrumDecorations: () => spectrum.refreshSpectrumDecorations(),
});

const cars = createCarsFeature({
  settings,
  queryClient,
  panel: panels.cars,
  analysisPanel: panels.analysis,
  activeViewId: activeView,
  activeSettingsTabId: settingsTab,
  openAnalysisTab: () => {
    settingsTab.value = "analysisTab";
  },
  refreshSpectrumDecorations: () => spectrum.refreshSpectrumDecorations(),
  syncAnalysisInputs: analysis.syncSettingsInputs,
  services,
  formatting: { fmt },
});

const realtimeFeature = createRealtimeFeature({
  realtime,
  settings,
  spectrum: appState.spectrum,
  shell: appState.shell,
  sensorsPanel: panels.sensors,
  liveOverview: panels.liveOverview,
  loggingPanel: panels.logging,
  setShellLiveStatus: (variant, text) => {
    liveStatusBadge.value = { text, variant: asVariant(variant) };
  },
  navigation: {
    activatePrimaryView: (view) => navigate(asView(view)),
    activateSettingsTab: (tab) => {
      settingsTab.value = tab as typeof settingsTab.value;
    },
    openCarWizard: () => {
      void cars.openWizard();
    },
  },
  sendSelection: () => liveTransport.sendSelection(),
  onRecordingStatusChanged: () => history.refreshHistory(),
  services,
  formatting: { formatInt: formatting.formatInt },
  queryClient,
});

function asView(view: string): typeof activeView.value {
  return view === "historyView" || view === "settingsView"
    ? view
    : "dashboardView";
}

function asVariant(variant: string): VisualVariant {
  return variant === "bad" || variant === "ok" || variant === "warn"
    ? variant
    : "muted";
}

// --- Dashboard speed readout -----------------------------------------------

panels.liveOverview.speedText.value = computed(() => {
  const mps = speedUnit.value === "mps";
  const unit = t(mps ? "speed.unit.mps" : "speed.unit.kmh");
  const speedMps = realtime.speedMps.value;
  if (typeof speedMps !== "number" || !Number.isFinite(speedMps)) {
    return t("speed.none", { unit });
  }
  const labelKey = deriveSpeedReadoutLabelKey(
    speedSourceSnapshot.value,
    realtime.rotationalSpeeds.value?.basis_speed_source,
  );
  return t(labelKey, {
    unit,
    value: fmt(mps ? speedMps : speedMps * 3.6, 1),
  });
});

// --- Startup ------------------------------------------------------------------

function loadOnce(load: () => Promise<unknown>): () => Promise<void> {
  let done = false;
  let pending: Promise<void> | null = null;
  return () => {
    if (done) {
      return Promise.resolve();
    }
    pending ??= load().then(
      () => {
        done = true;
      },
      (error: unknown) => {
        pending = null;
        throw error;
      },
    );
    return pending;
  };
}

onViewEnter(
  "historyView",
  loadOnce(() => history.refreshHistory()),
);
onViewEnter(
  "settingsView",
  loadOnce(() => analysis.loadAnalysisSettingsFromServer()),
);

function runStartupTask(name: string, task: () => Promise<unknown>): void {
  void task().catch((error: unknown) => {
    uiLogger.warn(`UI startup task failed: ${name}`, error);
  });
}

export function startFeatures(): void {
  realtimeFeature.bindHandlers();
  cars.bindHandlers();
  analysis.bindHandlers();
  history.bindHandlers();
  effectOnChange(activeView, (view) => {
    if (view === "dashboardView") {
      appState.spectrum.spectrumPlot.value?.resize();
    }
  });
  if (!isDemoMode()) {
    runStartupTask("load preferences", loadPreferences);
    runStartupTask("refresh location options", () =>
      realtimeFeature.refreshLocationOptions(),
    );
    runStartupTask("refresh logging status", () =>
      realtimeFeature.refreshLoggingStatus(),
    );
    runStartupTask("hydrate dashboard state", () =>
      Promise.all([
        loadDashboardStartupState(queryClient, settings),
        loadSpeedSource(),
      ]).catch((error: unknown) => {
        showError(
          error instanceof Error ? error.message : t("status.view_load_failed"),
        );
        throw error;
      }),
    );
  }
  liveTransport.startTransportMode();
}

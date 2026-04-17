import { Suspense, lazy } from "preact/compat";

import { render } from "preact";
import { signal } from "./ui_signals";
import {
  createDeferredModelSignal,
  createModelActionPanelBindings,
} from "./views/view_model_binding";
import type { SpectrumPanelView } from "./runtime/spectrum_panel_view";
import {
  type UiPanelHostRegistry,
} from "./ui_panel_host_registry";
import type { AnalysisPanelView } from "./views/analysis_panel";
import type { CarsPanelView } from "./views/cars_panel";
import type { EspFlashPanelView } from "./views/esp_flash_panel";
import type { HistoryPanelView } from "./views/history_table_view";
import type { InternetPanelView } from "./views/internet_panel";
import {
  mountRealtimeLoggingPanel,
  type RealtimeLoggingPanelActionHandlers,
  type RealtimeLoggingPanelBridge,
  type RealtimeLoggingPanelRenderModel,
} from "./views/realtime_logging_panel";
import {
  mountRealtimeLiveOverview,
  type RealtimeLiveOverviewBridge,
  type RealtimeLiveOverviewRenderModel,
} from "./views/realtime_live_overview";
import type { SensorsPanelView } from "./views/sensors_panel";
import type { SettingsShellView } from "./views/settings_shell";
import type { SpeedSourcePanelView } from "./views/speed_source_panel";
import { mountSpectrumPanel } from "./views/spectrum_panel";
import type { UpdatePanelView } from "./views/update_panel";

export interface UiMountedDashboardPanels {
  spectrum: SpectrumPanelView;
  liveOverview: RealtimeLiveOverviewBridge;
  logging: RealtimeLoggingPanelBridge;
}

export interface UiMountedSettingsPanels {
  cars: CarsPanelView;
  analysis: AnalysisPanelView;
  internet: InternetPanelView;
  update: UpdatePanelView;
  sensors: SensorsPanelView;
  speedSource: SpeedSourcePanelView;
  espFlash: EspFlashPanelView;
}

export interface UiMountedPanels {
  dashboard: UiMountedDashboardPanels;
  history: HistoryPanelView;
  settingsShell: SettingsShellView;
  settings: UiMountedSettingsPanels;
}

export interface UiMountedLazyPanelHandles {
  settingsShell: SettingsShellView;
  settings: {
    analysis: Pick<AnalysisPanelView, "focusField" | "openGuidance">;
    cars: Pick<CarsPanelView["wizard"], "focus">;
    internet: Pick<InternetPanelView, "focusSsidInput">;
    speedSource: Pick<
      SpeedSourcePanelView,
      "focusManualSpeedInput" | "focusScanObdDevices" | "focusStaleTimeoutInput" | "isObdConfigVisible"
    >;
  };
}

const HistoryLazyView = lazy(() => import("./views/history_lazy_view"));
const SettingsLazyView = lazy(() => import("./views/settings_lazy_view"));

function LazyPanelFallback(props: { text: string }) {
  return (
    <div class="subtle" aria-busy="true">
      {props.text}
    </div>
  );
}

export function mountDashboardPanels(
  hosts: UiPanelHostRegistry,
): UiMountedDashboardPanels {
  const liveOverview: RealtimeLiveOverviewBridge = {
    model: createDeferredModelSignal<RealtimeLiveOverviewRenderModel>(),
    speedText: signal("--"),
  };
  const logging: RealtimeLoggingPanelBridge = createModelActionPanelBindings<
    RealtimeLoggingPanelRenderModel,
    RealtimeLoggingPanelActionHandlers
  >();
  mountRealtimeLiveOverview(hosts.dashboard.liveOverview, liveOverview);
  mountRealtimeLoggingPanel(hosts.dashboard.logging, logging);
  return {
    spectrum: mountSpectrumPanel(hosts.dashboard.spectrum),
    liveOverview,
    logging,
  };
}

export async function mountHistoryPanelLazy(
  hosts: UiPanelHostRegistry,
  view: HistoryPanelView,
): Promise<void> {
  return new Promise((resolve) => {
    render(
      <Suspense fallback={<LazyPanelFallback text="Loading history..." />}>
        <HistoryLazyView onReady={resolve} view={view} />
      </Suspense>,
      hosts.history,
    );
  });
}

export async function mountSettingsPanelsLazy(
  hosts: UiPanelHostRegistry,
  panels: Pick<UiMountedPanels, "settings">,
): Promise<UiMountedLazyPanelHandles> {
  return new Promise((resolve) => {
    render(
      <Suspense fallback={<LazyPanelFallback text="Loading settings..." />}>
        <SettingsLazyView onReady={resolve} panels={panels} />
      </Suspense>,
      hosts.settingsShell,
    );
  });
}

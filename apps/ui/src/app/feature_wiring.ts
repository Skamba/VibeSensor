import {
  activeView,
  isDemoMode,
  loadPreferences,
  showError,
} from "../app_store";
import { t } from "../i18n";
import * as live from "../live_store";
import { loadCars, loadSpeedSource } from "../settings_store";
import { uiLogger } from "../ui_logger";
import { UiLiveTransportController } from "./runtime/ui_live_transport_controller";
import { UiSpectrumController } from "./runtime/ui_spectrum_controller";
import { createSpectrumState } from "./spectrum_state";
import { createAppState } from "./ui_app_state";
import { effectOnChange } from "./ui_signals";
import { createSpectrumPanel } from "./views/spectrum_panel";

/**
 * Wires the pre-rewrite live transport and spectrum controllers. Their state
 * slices point at the shared live store; the file goes away with them.
 */

export const appState = {
  ...createAppState(),
  realtime: {
    clients: live.clients,
    selectedClientId: live.selectedClientId,
    speedMps: live.speedMps,
    rotationalSpeeds: live.rotationalSpeeds,
    locationCodes: live.locationCodes,
  },
  spectrum: { ...createSpectrumState(), spectra: live.spectra },
};

const spectrumPanel = createSpectrumPanel();

export const panels = { spectrum: spectrumPanel };

const spectrum = new UiSpectrumController({
  state: appState,
  panel: spectrumPanel.view,
  t,
});
const liveTransport = new UiLiveTransportController({
  state: appState,
  payloadErrorMessage: () => t("ws.payload_error"),
});

// --- Startup ------------------------------------------------------------------

function runStartupTask(name: string, task: () => Promise<unknown>): void {
  void task().catch((error: unknown) => {
    uiLogger.warn(`UI startup task failed: ${name}`, error);
  });
}

export function startFeatures(): void {
  effectOnChange(activeView, (view) => {
    if (view === "dashboardView") {
      appState.spectrum.spectrumPlot.value?.resize();
    }
  });
  if (!isDemoMode()) {
    runStartupTask("load preferences", loadPreferences);
    runStartupTask("load location codes", live.loadLocationCodes);
    runStartupTask("hydrate dashboard state", () =>
      Promise.all([loadCars(), loadSpeedSource()]).catch((error: unknown) => {
        showError(
          error instanceof Error ? error.message : t("status.view_load_failed"),
        );
        throw error;
      }),
    );
  }
  liveTransport.startTransportMode();
}

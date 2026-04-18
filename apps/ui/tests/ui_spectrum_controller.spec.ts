import { expect, test } from "@playwright/test";

import type { SpectrumPanelView } from "../src/app/runtime/spectrum_panel_view";
import { applyLivePayloadUpdate, createAppState } from "../src/app/ui_app_state";
import { batch } from "../src/app/ui_signals";
import type { AdaptedPayload } from "../src/transport/live_models";
import { installWindowGlobal } from "./async_test_helpers";
import { createElementStub, installDocumentStub } from "./spectrum_test_support";

async function importUiSpectrumController() {
  return (await import("../src/app/runtime/ui_spectrum_controller")).UiSpectrumController;
}

function makeSpectrumPayload(values: readonly number[]): AdaptedPayload {
  return {
    clients: [{
      id: "sensor-a",
      name: "Sensor A",
      connected: true,
      mac_address: "00:11:22:33:44:55",
      location_code: "",
      last_seen_age_ms: 0,
      dropped_frames: 0,
      frames_total: 1,
      frame_samples: 0,
      sample_rate_hz: 1600,
      firmware_version: "1.0.0",
    }],
    speed_mps: 10,
    rotational_speeds: null,
    spectra: {
      clients: {
        "sensor-a": {
          freq: [10, 20, 30],
          combined: [...values],
          strength_metrics: {
            vibration_strength_db: 12,
            peak_amp_g: 0,
            noise_floor_amp_g: 0,
            strength_bucket: null,
            top_peaks: [],
          },
        },
      },
    },
  };
}

function createPanelStub(): {
  panel: SpectrumPanelView;
  lastHeaderModel: { hintText: string; titleText: string } | null;
  lastOverlayModel: { hidden: boolean; text: string } | null;
} {
  let lastHeaderModel: { hintText: string; titleText: string } | null = null;
  let lastOverlayModel: { hidden: boolean; text: string } | null = null;

  return {
      panel: {
        chartDom: {
          specChartWrap: createElementStub("div"),
          specChart: createElementStub("div"),
        },
        bindBandToggle() {},
        bindBandToggleModel() {},
        bindSensorLegendModel() {},
        bindBandLegendModel() {},
        renderHeader(model) {
          lastHeaderModel = model;
        },
        renderOverlay(model) {
          lastOverlayModel = model;
        },
        renderInspectorText() {},
      },
    get lastHeaderModel() {
      return lastHeaderModel;
    },
    get lastOverlayModel() {
      return lastOverlayModel;
    },
  };
}

test.describe("UiSpectrumController", () => {
  test.beforeEach(() => {
    installWindowGlobal();
  });

  test("renders the connecting overlay through the coordinator surface", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const UiSpectrumController = await importUiSpectrumController();
      const state = createAppState();
      state.transport.wsState.value = "connecting";
      state.transport.hasReceivedPayload.value = false;
      const panel = createPanelStub();

      new UiSpectrumController({
        state,
        panel: panel.panel,
        t: (key) => key,
      });

      expect(panel.lastOverlayModel).toEqual({
        hidden: false,
        text: "spectrum.loading",
      });
    } finally {
      restoreDocument();
    }
  });

  test("reacts to transport state changes without explicit overlay callbacks", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const UiSpectrumController = await importUiSpectrumController();
      const state = createAppState();
      state.transport.wsState.value = "connecting";
      state.transport.hasReceivedPayload.value = false;
      const panel = createPanelStub();

      new UiSpectrumController({
        state,
        panel: panel.panel,
        t: (key) => key,
      });

      state.transport.wsState.value = "stale";

      expect(panel.lastOverlayModel).toEqual({
        hidden: false,
        text: "spectrum.stale",
      });
    } finally {
      restoreDocument();
    }
  });

  test("runs overlay sync when spectra and transport change in the same batch", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const UiSpectrumController = await importUiSpectrumController();
      const state = createAppState();
      const panel = createPanelStub();
      const controller = new UiSpectrumController({
        state,
        panel: panel.panel,
        t: (key) => key,
      });
      let renderCalls = 0;
      let overlayCalls = 0;

      controller.renderSpectrum = () => {
        renderCalls += 1;
      };
      controller.updateSpectrumOverlay = () => {
        overlayCalls += 1;
      };

      batch(() => {
        state.spectrum.spectra.value = { ...state.spectrum.spectra.value };
        state.transport.wsState.value = "stale";
      });

      expect(renderCalls).toBe(1);
      expect(overlayCalls).toBe(1);
    } finally {
      restoreDocument();
    }
  });

  test("skips redraws for repeated heavy frames and redraws when the frame changes", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const UiSpectrumController = await importUiSpectrumController();
      const state = createAppState();
      const panel = createPanelStub();
      const controller = new UiSpectrumController({
        state,
        panel: panel.panel,
        t: (key) => key,
      });
      let renderCalls = 0;
      controller.renderSpectrum = () => {
        renderCalls += 1;
      };

      applyLivePayloadUpdate({
        realtime: state.realtime,
        spectrum: state.spectrum,
        adaptedPayload: makeSpectrumPayload([0.1, 0.2, 0.3]),
      });
      expect(renderCalls).toBe(1);

      applyLivePayloadUpdate({
        realtime: state.realtime,
        spectrum: state.spectrum,
        adaptedPayload: makeSpectrumPayload([0.1, 0.2, 0.3]),
      });
      expect(renderCalls).toBe(1);

      applyLivePayloadUpdate({
        realtime: state.realtime,
        spectrum: state.spectrum,
        adaptedPayload: makeSpectrumPayload([0.1, 0.2, 0.4]),
      });
      expect(renderCalls).toBe(2);
    } finally {
      restoreDocument();
    }
  });

  test("refreshes decorations without rebuilding spectrum data", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const UiSpectrumController = await importUiSpectrumController();
      const state = createAppState();
      const panel = createPanelStub();
      const controller = new UiSpectrumController({
        state,
        panel: panel.panel,
        t: (key) => key,
      });
      const canvas = (controller as unknown as {
        canvas: {
          prepareFrame: () => unknown;
          refreshPreparedFrameMetadata: () => {
            entries: [];
            freqAxis: [];
            chartBands: [];
            frame: null;
            hasData: false;
          };
          refreshDecorations: () => void;
        };
      }).canvas;
      let prepareCalls = 0;
      let refreshCalls = 0;

      canvas.prepareFrame = () => {
        prepareCalls += 1;
        return null;
      };
      canvas.refreshPreparedFrameMetadata = () => ({
        entries: [],
        freqAxis: [],
        chartBands: [],
        frame: null,
        hasData: false,
      });
      canvas.refreshDecorations = () => {
        refreshCalls += 1;
      };

      controller.refreshSpectrumDecorations();

      expect(prepareCalls).toBe(0);
      expect(refreshCalls).toBe(1);
    } finally {
      restoreDocument();
    }
  });

  test("shows the loading overlay while the chart chunk is still loading", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const UiSpectrumController = await importUiSpectrumController();
      const state = createAppState();
      state.transport.wsState.value = "connected";
      state.transport.hasReceivedPayload.value = true;
      state.spectrum.hasSpectrumData.value = true;
      state.spectrum.chartLoading.value = true;
      const panel = createPanelStub();

      new UiSpectrumController({
        state,
        panel: panel.panel,
        t: (key) => key,
      });

      expect(panel.lastOverlayModel).toEqual({
        hidden: false,
        text: "spectrum.loading",
      });
    } finally {
      restoreDocument();
    }
  });

  test("shows chart load errors through the overlay", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const UiSpectrumController = await importUiSpectrumController();
      const state = createAppState();
      state.transport.wsState.value = "connected";
      state.transport.hasReceivedPayload.value = true;
      state.spectrum.hasSpectrumData.value = true;
      state.spectrum.chartLoadErrorDetail.value = "chunk timeout";
      const panel = createPanelStub();

      new UiSpectrumController({
        state,
        panel: panel.panel,
        t: (key, vars) => {
          if (key === "spectrum.chart_load_error") {
            return `chart load failed: ${String(vars?.message)}`;
          }
          return key;
        },
      });

      expect(panel.lastOverlayModel).toEqual({
        hidden: false,
        text: "chart load failed: chunk timeout",
      });
    } finally {
      restoreDocument();
    }
  });

  test("updates spectrum header and overlay when the language changes", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const UiSpectrumController = await importUiSpectrumController();
      const state = createAppState();
      state.transport.wsState.value = "stale";
      const panel = createPanelStub();

      new UiSpectrumController({
        state,
        panel: panel.panel,
        t: (key) => `${state.shell.lang.value}:${key}`,
      });

      expect(panel.lastHeaderModel).toEqual({
        titleText: "en:chart.spectrum_title",
        hintText: "en:spectrum.controls_hint",
      });
      expect(panel.lastOverlayModel).toEqual({
        hidden: false,
        text: "en:spectrum.stale",
      });

      state.shell.lang.value = "nl";

      expect(panel.lastHeaderModel).toEqual({
        titleText: "nl:chart.spectrum_title",
        hintText: "nl:spectrum.controls_hint",
      });
      expect(panel.lastOverlayModel).toEqual({
        hidden: false,
        text: "nl:spectrum.stale",
      });
    } finally {
      restoreDocument();
    }
  });
});

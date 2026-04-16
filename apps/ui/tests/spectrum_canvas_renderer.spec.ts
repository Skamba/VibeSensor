import { expect, test } from "@playwright/test";

import type { SpectrumPanelChartDom } from "../src/app/runtime/spectrum_panel_view";
import { createAppState } from "../src/app/ui_app_state";
import type { SpectrumChart } from "../src/spectrum_chart";
import type { AdaptedClient } from "../src/transport/live_models";
import { createDeferred, flushSignalUpdates, installWindowGlobal } from "./async_test_helpers";
import { createElementStub, installDocumentStub } from "./spectrum_test_support";

function makeClient(id: string, name: string): AdaptedClient {
  return {
    id,
    name,
    connected: true,
    mac_address: id,
    location_code: "front_right_wheel",
    last_seen_age_ms: 25,
    dropped_frames: 0,
    frames_total: 100,
    frame_samples: 200,
    sample_rate_hz: 400,
    firmware_version: "fw-1.0.0",
  };
}

test.describe("SpectrumCanvasRenderer", () => {
  test.beforeEach(() => {
    installWindowGlobal();
  });

  test("prepares aligned dB series without shell DOM bindings", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const { SpectrumCanvasRenderer } = await import(
        "../src/app/runtime/spectrum_canvas_renderer"
      );
      const state = createAppState();
      state.realtime.clients = [
        makeClient("sensor-a", "Front Right Wheel"),
        makeClient("sensor-b", "Rear Left Wheel"),
      ];
      state.spectrum.spectra.clients = {
        "sensor-a": {
          freq: [10, 15, 20],
          combined: [1, 0.75, 0.5],
          strength_metrics: {
            noise_floor_amp_g: 0.1,
            peak_amp_g: 1,
            strength_bucket: null,
            top_peaks: [{
              amp: 1,
              hz: 10,
              strength_bucket: null,
              vibration_strength_db: 12,
            }],
            vibration_strength_db: 12,
          },
        },
        "sensor-b": {
          freq: [10, 20],
          combined: [0.8, 0.4],
          strength_metrics: {
            noise_floor_amp_g: 0.1,
            peak_amp_g: 0.8,
            strength_bucket: null,
            top_peaks: [{
              amp: 0.8,
              hz: 10,
              strength_bucket: null,
              vibration_strength_db: 9,
            }],
            vibration_strength_db: 9,
          },
        },
      };

      const renderer = new SpectrumCanvasRenderer({
        state,
        dom: {
          specChart: createElementStub("div"),
          specChartWrap: createElementStub("div"),
        } as unknown as SpectrumPanelChartDom,
        t: (key) => key,
        getBandsVisible: () => false,
        getChartBands: () => [],
        getFocusMarker: () => null,
        onCursorDataIndexChange: () => undefined,
      });

      const prepared = renderer.prepareFrame();

      expect(prepared.hasData).toBe(true);
      expect(prepared.freqAxis).toEqual([10, 15, 20]);
      expect(prepared.entries.map((entry) => entry.id)).toEqual(["sensor-a", "sensor-b"]);
      expect(prepared.frame?.values[1]).toHaveLength(3);
      expect(prepared.entries[1].values.every((value) => Number.isFinite(value))).toBe(true);
      expect(prepared.entries[1].values[0]).toBeGreaterThan(prepared.entries[1].values[2]);
    } finally {
      restoreDocument();
    }
  });

  test("queues the first render until the chart module finishes loading", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const { SpectrumCanvasRenderer } = await import(
        "../src/app/runtime/spectrum_canvas_renderer"
      );
      const state = createAppState();
      state.transport.wsState = "connected";
      state.realtime.clients = [makeClient("sensor-a", "Front Right Wheel")];
      state.spectrum.spectra.clients = {
        "sensor-a": {
          freq: [10, 15, 20],
          combined: [1, 0.75, 0.5],
          strength_metrics: {
            noise_floor_amp_g: 0.1,
            peak_amp_g: 1,
            strength_bucket: null,
            top_peaks: [{
              amp: 1,
              hz: 10,
              strength_bucket: null,
              vibration_strength_db: 12,
            }],
            vibration_strength_db: 12,
          },
        },
      };

      const chartModule = createDeferred<{ SpectrumChart: typeof SpectrumChart }>();
      const createdCharts: FakeSpectrumChart[] = [];
      class FakeSpectrumChart {
        private seriesCount = 0;
        public readonly setDataCalls: Array<readonly unknown[]> = [];

        constructor(..._args: unknown[]) {
          createdCharts.push(this);
        }

        ensurePlot(seriesMeta: Array<{ label: string; color: string }>): void {
          this.seriesCount = seriesMeta.length + 1;
        }

        setData(data: readonly unknown[]): void {
          this.setDataCalls.push(data);
        }

        setSeriesIsolation(): void {}

        getSeriesCount(): number {
          return this.seriesCount;
        }

        destroy(): void {}
      }

      const renderer = new SpectrumCanvasRenderer({
        state,
        dom: {
          specChart: createElementStub("div"),
          specChartWrap: createElementStub("div"),
        } as unknown as SpectrumPanelChartDom,
        t: (key) => key,
        getBandsVisible: () => false,
        getChartBands: () => [],
        getFocusMarker: () => null,
        onCursorDataIndexChange: () => undefined,
        loadChartModule: () => chartModule.promise,
      });

      const prepared = renderer.prepareFrame();
      renderer.renderPreparedFrame(prepared);

      expect(state.spectrum.chartLoading).toBe(true);
      expect(state.spectrum.spectrumPlot).toBeNull();
      expect(createdCharts).toHaveLength(0);

      chartModule.resolve({
        SpectrumChart: FakeSpectrumChart as unknown as typeof SpectrumChart,
      });
      await flushSignalUpdates();

      expect(state.spectrum.chartLoading).toBe(false);
      expect(state.spectrum.chartLoadErrorDetail).toBeNull();
      expect(createdCharts).toHaveLength(1);
      expect(state.spectrum.spectrumPlot).toBe(createdCharts[0] as unknown as SpectrumChart);
      expect(createdCharts[0].setDataCalls).toHaveLength(1);
      expect(createdCharts[0].setDataCalls[0]?.[0]).toEqual([10, 15, 20]);
    } finally {
      restoreDocument();
    }
  });
});

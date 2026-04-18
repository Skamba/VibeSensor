import { expect, test } from "@playwright/test";

import type { SpectrumPanelChartDom } from "../src/app/runtime/spectrum_panel_view";
import { createAppState } from "../src/app/ui_app_state";
import { effect } from "../src/app/ui_signals";
import type { CreateSpectrumChartDeps, SpectrumChart } from "../src/spectrum_chart";
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

function getRequiredClientSpectrum(state: ReturnType<typeof createAppState>, clientId: string) {
  const spectrum = state.spectrum.spectra.value.clients[clientId];
  if (!spectrum) {
    throw new Error(`Expected spectrum for ${clientId}`);
  }
  return spectrum;
}

test.describe("createSpectrumCanvasRenderer", () => {
  test.beforeEach(() => {
    installWindowGlobal();
  });

  test("prepares aligned dB series without shell DOM bindings", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const { createSpectrumCanvasRenderer } = await import(
        "../src/app/runtime/spectrum_canvas_renderer"
      );
      const state = createAppState();
      state.realtime.clients.value = [
        makeClient("sensor-a", "Front Right Wheel"),
        makeClient("sensor-b", "Rear Left Wheel"),
      ];
      state.spectrum.spectra.value = {
        ...state.spectrum.spectra.value,
        clients: {
          ...state.spectrum.spectra.value.clients,
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
        },
      };

      const renderer = createSpectrumCanvasRenderer({
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
      const { createSpectrumCanvasRenderer } = await import(
        "../src/app/runtime/spectrum_canvas_renderer"
      );
      const state = createAppState();
      state.realtime.clients.value = [makeClient("sensor-a", "Front Right Wheel")];
      state.spectrum.spectra.value = {
        ...state.spectrum.spectra.value,
        clients: {
          ...state.spectrum.spectra.value.clients,
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
        },
      };

      const chartModule = createDeferred<{
        createSpectrumChart: (deps: CreateSpectrumChartDeps) => SpectrumChart;
      }>();
      const createdCharts: Array<{
        dataSnapshots: Array<readonly unknown[]>;
        seriesCount: number;
      }> = [];
      function createFakeSpectrumChart(deps: CreateSpectrumChartDeps): SpectrumChart {
        const chartState = {
          dataSnapshots: [] as Array<readonly unknown[]>,
          seriesCount: 0,
        };
        const stop = effect(() => {
          chartState.seriesCount = deps.seriesMeta.value.length + 1;
          chartState.dataSnapshots.push(deps.data.value as readonly unknown[]);
        });
        createdCharts.push(chartState);
        return {
          destroy() {
            stop();
          },
          redraw() {},
          resize() {},
          setData() {},
          setSeriesIsolation() {},
        };
      }

      const renderer = createSpectrumCanvasRenderer({
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

      expect(state.spectrum.chartLoading.value).toBe(true);
      expect(state.spectrum.spectrumPlot.value).toBeNull();
      expect(createdCharts).toHaveLength(0);

      chartModule.resolve({
        createSpectrumChart: createFakeSpectrumChart,
      });
      await flushSignalUpdates();

      expect(state.spectrum.chartLoading.value).toBe(false);
      expect(state.spectrum.chartLoadErrorDetail.value).toBeNull();
      expect(createdCharts).toHaveLength(1);
      expect(state.spectrum.spectrumPlot.value).not.toBeNull();
      expect(createdCharts[0].dataSnapshots.at(-1)?.[0]).toEqual([10, 15, 20]);
      expect(createdCharts[0].seriesCount).toBe(2);
    } finally {
      restoreDocument();
    }
  });

  test("passes reactive chart text updates through the factory signals", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const { createSpectrumCanvasRenderer } = await import(
        "../src/app/runtime/spectrum_canvas_renderer"
      );
      const state = createAppState();
      state.realtime.clients.value = [makeClient("sensor-a", "Front Right Wheel")];
      state.spectrum.spectra.value = {
        ...state.spectrum.spectra.value,
        clients: {
          ...state.spectrum.spectra.value.clients,
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
        },
      };
      const axisTexts: string[] = [];
      let createCalls = 0;

      const renderer = createSpectrumCanvasRenderer({
        state,
        dom: {
          specChart: createElementStub("div"),
          specChartWrap: createElementStub("div"),
        } as unknown as SpectrumPanelChartDom,
        t: (key) => `${state.shell.lang.value}:${key}`,
        getBandsVisible: () => false,
        getChartBands: () => [],
        getFocusMarker: () => null,
        onCursorDataIndexChange: () => undefined,
        loadChartModule: async () => ({
          createSpectrumChart(deps: CreateSpectrumChartDeps): SpectrumChart {
            createCalls += 1;
            const stop = effect(() => {
              axisTexts.push(deps.text.value.axisHz);
            });
            return {
              destroy() {
                stop();
              },
              redraw() {},
              resize() {},
              setData() {},
              setSeriesIsolation() {},
            };
          },
        }),
      });

      const prepared = renderer.prepareFrame();
      renderer.renderPreparedFrame(prepared);
      await flushSignalUpdates();

      state.shell.lang.value = "nl";
      await flushSignalUpdates();

      expect(createCalls).toBe(1);
      expect(axisTexts).toContain("en:chart.axis.hz");
      expect(axisTexts.at(-1)).toBe("nl:chart.axis.hz");
    } finally {
      restoreDocument();
    }
  });

  test("reuses series metadata when only spectrum values change", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const { createSpectrumCanvasRenderer } = await import(
        "../src/app/runtime/spectrum_canvas_renderer"
      );
      const state = createAppState();
      state.realtime.clients.value = [makeClient("sensor-a", "Front Right Wheel")];
      state.spectrum.spectra.value = {
        ...state.spectrum.spectra.value,
        clients: {
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
        },
      };
      const seriesMetaSnapshots: CreateSpectrumChartDeps["seriesMeta"]["value"][] = [];
      const setDataSnapshots: readonly unknown[][] = [];

      const renderer = createSpectrumCanvasRenderer({
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
        loadChartModule: async () => ({
          createSpectrumChart(deps: CreateSpectrumChartDeps): SpectrumChart {
            const stop = effect(() => {
              seriesMetaSnapshots.push(deps.seriesMeta.value);
            });
            return {
              destroy() {
                stop();
              },
              redraw() {},
              resize() {},
              setData(data) {
                setDataSnapshots.push(data as readonly unknown[]);
              },
              setSeriesIsolation() {},
            };
          },
        }),
      });

      const firstPrepared = renderer.prepareFrame();
      renderer.renderPreparedFrame(firstPrepared);
      await flushSignalUpdates();

      state.spectrum.spectra.value = {
        clients: {
          "sensor-a": {
            ...getRequiredClientSpectrum(state, "sensor-a"),
            combined: [0.9, 0.7, 0.45],
          },
        },
      };

      const nextPrepared = renderer.prepareFrame();
      renderer.renderPreparedFrame(nextPrepared);
      await flushSignalUpdates();

      expect(new Set(seriesMetaSnapshots).size).toBe(1);
      expect(setDataSnapshots).toHaveLength(2);
      expect(setDataSnapshots[0]).toBe(setDataSnapshots[1]);
    } finally {
      restoreDocument();
    }
  });

  test("reuses cached prepared data when only chart-band metadata changes", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const { createSpectrumCanvasRenderer } = await import(
        "../src/app/runtime/spectrum_canvas_renderer"
      );
      const state = createAppState();
      state.realtime.clients.value = [makeClient("sensor-a", "Front Right Wheel")];
      state.spectrum.spectra.value = {
        clients: {
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
        },
      };

      const renderer = createSpectrumCanvasRenderer({
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
        loadChartModule: async () => ({
          createSpectrumChart(): SpectrumChart {
            return {
              destroy() {},
              redraw() {},
              resize() {},
              setData() {},
              setSeriesIsolation() {},
            };
          },
        }),
      });

      const prepared = renderer.prepareFrame();
      renderer.renderPreparedFrame(prepared);
      await flushSignalUpdates();

      state.realtime.rotationalSpeeds.value = {
        wheel_rpm: 600,
        engine_rpm: 1800,
        driveshaft_rpm: 600,
        order_bands: [{
          key: "wheel_1x",
          center_hz: 10,
          tolerance: 0.1,
        }],
      };

      const refreshed = renderer.refreshPreparedFrameMetadata();

      expect(refreshed.entries).toBe(prepared.entries);
      expect(refreshed.freqAxis).toBe(prepared.freqAxis);
      expect(refreshed.frame).toBe(prepared.frame);
      expect(refreshed.hasData).toBe(true);
      expect(refreshed.chartBands).toHaveLength(1);
    } finally {
      restoreDocument();
    }
  });

  test("reuses prepared series when source arrays and target grid are unchanged", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const { createSpectrumCanvasRenderer } = await import(
        "../src/app/runtime/spectrum_canvas_renderer"
      );
      const state = createAppState();
      state.realtime.clients.value = [
        makeClient("sensor-a", "Front Right Wheel"),
        makeClient("sensor-b", "Rear Left Wheel"),
      ];
      const sensorACombined = [1, 0.75, 0.5];
      const sensorAFreq = [10, 15, 20];
      const sensorBCombined = [0.8, 0.4];
      const sensorBFreq = [10, 20];
      state.spectrum.spectra.value = {
        clients: {
          "sensor-a": {
            freq: sensorAFreq,
            combined: sensorACombined,
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
            freq: sensorBFreq,
            combined: sensorBCombined,
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
        },
      };

      const renderer = createSpectrumCanvasRenderer({
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

      const firstPrepared = renderer.prepareFrame();
      const secondPrepared = renderer.prepareFrame();

      expect(secondPrepared.entries[0]?.values).toBe(firstPrepared.entries[0]?.values);
      expect(secondPrepared.entries[1]?.values).toBe(firstPrepared.entries[1]?.values);
    } finally {
      restoreDocument();
    }
  });

  test("recomputes only the changed client when source amplitudes change", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const { createSpectrumCanvasRenderer } = await import(
        "../src/app/runtime/spectrum_canvas_renderer"
      );
      const state = createAppState();
      state.realtime.clients.value = [
        makeClient("sensor-a", "Front Right Wheel"),
        makeClient("sensor-b", "Rear Left Wheel"),
      ];
      state.spectrum.spectra.value = {
        clients: {
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
        },
      };

      const renderer = createSpectrumCanvasRenderer({
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

      const firstPrepared = renderer.prepareFrame();

      state.spectrum.spectra.value = {
        clients: {
          ...state.spectrum.spectra.value.clients,
          "sensor-b": {
            ...getRequiredClientSpectrum(state, "sensor-b"),
            combined: [0.9, 0.45],
          },
        },
      };

      const secondPrepared = renderer.prepareFrame();

      expect(secondPrepared.entries[0]?.values).toBe(firstPrepared.entries[0]?.values);
      expect(secondPrepared.entries[1]?.values).not.toBe(firstPrepared.entries[1]?.values);
    } finally {
      restoreDocument();
    }
  });

  test("rebuilds chart data buffers when the frame shape changes", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const { createSpectrumCanvasRenderer } = await import(
        "../src/app/runtime/spectrum_canvas_renderer"
      );
      const state = createAppState();
      state.transport.wsState.value = "connected";
      state.realtime.clients.value = [makeClient("sensor-a", "Front Right Wheel")];
      state.spectrum.spectra.value = {
        clients: {
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
        },
      };
      const setDataSnapshots: readonly unknown[][] = [];

      const renderer = createSpectrumCanvasRenderer({
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
        loadChartModule: async () => ({
          createSpectrumChart(): SpectrumChart {
            return {
              destroy() {},
              redraw() {},
              resize() {},
              setData(data) {
                setDataSnapshots.push(data as readonly unknown[]);
              },
              setSeriesIsolation() {},
            };
          },
        }),
      });

      renderer.renderPreparedFrame(renderer.prepareFrame());
      await flushSignalUpdates();

      state.spectrum.spectra.value = {
        clients: {
          "sensor-a": {
            ...getRequiredClientSpectrum(state, "sensor-a"),
            freq: [10, 20, 30, 40],
            combined: [1, 0.7, 0.4, 0.2],
          },
        },
      };

      renderer.renderPreparedFrame(renderer.prepareFrame());
      await flushSignalUpdates();

      expect(setDataSnapshots).toHaveLength(2);
      expect(setDataSnapshots[0]).not.toBe(setDataSnapshots[1]);
    } finally {
      restoreDocument();
    }
  });

  test("uses redraw instead of setData for decoration-only refreshes", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const { createSpectrumCanvasRenderer } = await import(
        "../src/app/runtime/spectrum_canvas_renderer"
      );
      const state = createAppState();
      state.transport.wsState.value = "connected";
      state.realtime.clients.value = [makeClient("sensor-a", "Front Right Wheel")];
      state.spectrum.spectra.value = {
        clients: {
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
        },
      };
      let redrawCalls = 0;
      let setDataCalls = 0;

      const renderer = createSpectrumCanvasRenderer({
        state,
        dom: {
          specChart: createElementStub("div"),
          specChartWrap: createElementStub("div"),
        } as unknown as SpectrumPanelChartDom,
        t: (key) => key,
        getBandsVisible: () => true,
        getChartBands: () => [{
          label: "Wheel",
          min_hz: 9,
          max_hz: 11,
          color: "#fff",
        }],
        getFocusMarker: () => null,
        onCursorDataIndexChange: () => undefined,
        loadChartModule: async () => ({
          createSpectrumChart(): SpectrumChart {
            return {
              destroy() {},
              redraw() {
                redrawCalls += 1;
              },
              resize() {},
              setData() {
                setDataCalls += 1;
              },
              setSeriesIsolation() {},
            };
          },
        }),
      });

      renderer.renderPreparedFrame(renderer.prepareFrame());
      await flushSignalUpdates();
      setDataCalls = 0;

      renderer.refreshDecorations();

      expect(redrawCalls).toBe(1);
      expect(setDataCalls).toBe(0);
    } finally {
      restoreDocument();
    }
  });

  test("suppresses tween animations when heavy frames arrive faster than the tween budget", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const { createSpectrumCanvasRenderer } = await import(
        "../src/app/runtime/spectrum_canvas_renderer"
      );
      const state = createAppState();
      state.transport.wsState.value = "connected";
      state.realtime.clients.value = [makeClient("sensor-a", "Front Right Wheel")];
      state.spectrum.spectra.value = {
        clients: {
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
        },
      };
      const animationStarts: number[] = [];
      const renderTimesMs = [1_000, 1_100];

      const renderer = createSpectrumCanvasRenderer({
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
        loadChartModule: async () => ({
          createSpectrumChart(): SpectrumChart {
            return {
              destroy() {},
              redraw() {},
              resize() {},
              setData() {},
              setSeriesIsolation() {},
            };
          },
        }),
        createAnimation: ({ durationMs }) => ({
          start() {
            animationStarts.push(durationMs);
          },
          stop() {},
        }),
        nowMs: () => renderTimesMs.shift() ?? 0,
      });

      renderer.renderPreparedFrame(renderer.prepareFrame());
      await flushSignalUpdates();

      state.spectrum.spectra.value = {
        clients: {
          "sensor-a": {
            ...getRequiredClientSpectrum(state, "sensor-a"),
            combined: [0.9, 0.7, 0.45],
          },
        },
      };

      renderer.renderPreparedFrame(renderer.prepareFrame());
      await flushSignalUpdates();

      expect(animationStarts).toEqual([]);
    } finally {
      restoreDocument();
    }
  });

  test("keeps tween animations enabled when heavy frames arrive slower than the tween budget", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const { createSpectrumCanvasRenderer } = await import(
        "../src/app/runtime/spectrum_canvas_renderer"
      );
      const state = createAppState();
      state.transport.wsState.value = "connected";
      state.realtime.clients.value = [makeClient("sensor-a", "Front Right Wheel")];
      state.spectrum.spectra.value = {
        clients: {
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
        },
      };
      const animationStarts: number[] = [];
      const renderTimesMs = [1_000, 1_250];

      const renderer = createSpectrumCanvasRenderer({
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
        loadChartModule: async () => ({
          createSpectrumChart(): SpectrumChart {
            return {
              destroy() {},
              redraw() {},
              resize() {},
              setData() {},
              setSeriesIsolation() {},
            };
          },
        }),
        createAnimation: ({ durationMs }) => ({
          start() {
            animationStarts.push(durationMs);
          },
          stop() {},
        }),
        nowMs: () => renderTimesMs.shift() ?? 0,
      });

      renderer.renderPreparedFrame(renderer.prepareFrame());
      await flushSignalUpdates();

      state.spectrum.spectra.value = {
        clients: {
          "sensor-a": {
            ...getRequiredClientSpectrum(state, "sensor-a"),
            combined: [0.9, 0.7, 0.45],
          },
        },
      };

      renderer.renderPreparedFrame(renderer.prepareFrame());
      await flushSignalUpdates();

      expect(animationStarts).toEqual([180]);
    } finally {
      restoreDocument();
    }
  });
});

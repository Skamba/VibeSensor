import { beforeEach, describe, expect, test } from "vitest";
import { effect } from "../src/app/ui_signals";
import type {
  CreateSpectrumChartDeps,
  SpectrumChart,
} from "../src/spectrum_chart";
import { flushSignalUpdates, installWindowGlobal } from "./async_test_helpers";
import {
  getRequiredClientSpectrum,
  installClientSpectra,
  makeClient,
  makeSpectrum,
  withSpectrumRendererHarness,
} from "./spectrum_canvas_renderer_test_support";

describe("createSpectrumCanvasRenderer cache reuse", () => {
  beforeEach(() => {
    installWindowGlobal();
  });

  test("reuses series metadata when only spectrum values change", async () => {
    const seriesMetaSnapshots: CreateSpectrumChartDeps["seriesMeta"]["value"][] =
      [];
    const setDataSnapshots: readonly unknown[][] = [];

    await withSpectrumRendererHarness(
      {
        deps: {
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
        },
        seedState(state) {
          installClientSpectra(state, [
            {
              client: makeClient("sensor-a", "Front Right Wheel"),
              spectrum: makeSpectrum(),
            },
          ]);
        },
      },
      async ({ prepareFrame, renderer, state }) => {
        const firstPrepared = prepareFrame();
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

        const nextPrepared = prepareFrame();
        renderer.renderPreparedFrame(nextPrepared);
        await flushSignalUpdates();

        expect(new Set(seriesMetaSnapshots).size).toBe(1);
        expect(setDataSnapshots).toHaveLength(2);
        expect(setDataSnapshots[0]).toBe(setDataSnapshots[1]);
      },
    );
  });

  test("reuses cached prepared data when only chart-band metadata changes", async () => {
    await withSpectrumRendererHarness(
      {
        deps: {
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
        },
        seedState(state) {
          installClientSpectra(state, [
            {
              client: makeClient("sensor-a", "Front Right Wheel"),
              spectrum: makeSpectrum(),
            },
          ]);
        },
      },
      async ({ prepareFrame, renderer, state }) => {
        const prepared = prepareFrame();
        renderer.renderPreparedFrame(prepared);
        await flushSignalUpdates();

        state.realtime.rotationalSpeeds.value = {
          wheel_rpm: 600,
          engine_rpm: 1800,
          driveshaft_rpm: 600,
          order_bands: [
            {
              key: "wheel_1x",
              center_hz: 10,
              tolerance: 0.1,
            },
          ],
        };

        const refreshed = renderer.refreshPreparedFrameMetadata();

        expect(refreshed.entries).toBe(prepared.entries);
        expect(refreshed.freqAxis).toBe(prepared.freqAxis);
        expect(refreshed.frame).toBe(prepared.frame);
        expect(refreshed.hasData).toBe(true);
        expect(refreshed.chartBands).toHaveLength(1);
      },
    );
  });

  test("reuses prepared series when source arrays and target grid are unchanged", async () => {
    const sensorAFreq = [10, 15, 20];
    const sensorACombined = [1, 0.75, 0.5];
    const sensorBFreq = [10, 20];
    const sensorBCombined = [0.8, 0.4];

    await withSpectrumRendererHarness(
      {
        seedState(state) {
          installClientSpectra(state, [
            {
              client: makeClient("sensor-a", "Front Right Wheel"),
              spectrum: makeSpectrum({
                combined: sensorACombined,
                freq: sensorAFreq,
              }),
            },
            {
              client: makeClient("sensor-b", "Rear Left Wheel"),
              spectrum: makeSpectrum({
                combined: sensorBCombined,
                freq: sensorBFreq,
                peakAmp: 0.8,
                vibrationStrengthDb: 9,
              }),
            },
          ]);
        },
      },
      ({ prepareFrame }) => {
        const firstPrepared = prepareFrame();
        const secondPrepared = prepareFrame();

        expect(secondPrepared.entries[0]?.values).toBe(
          firstPrepared.entries[0]?.values,
        );
        expect(secondPrepared.entries[1]?.values).toBe(
          firstPrepared.entries[1]?.values,
        );
      },
    );
  });

  test("recomputes only the changed client when source amplitudes change", async () => {
    await withSpectrumRendererHarness(
      {
        seedState(state) {
          installClientSpectra(state, [
            {
              client: makeClient("sensor-a", "Front Right Wheel"),
              spectrum: makeSpectrum(),
            },
            {
              client: makeClient("sensor-b", "Rear Left Wheel"),
              spectrum: makeSpectrum({
                combined: [0.8, 0.4],
                freq: [10, 20],
                peakAmp: 0.8,
                vibrationStrengthDb: 9,
              }),
            },
          ]);
        },
      },
      ({ prepareFrame, state }) => {
        const firstPrepared = prepareFrame();

        state.spectrum.spectra.value = {
          clients: {
            ...state.spectrum.spectra.value.clients,
            "sensor-b": {
              ...getRequiredClientSpectrum(state, "sensor-b"),
              combined: [0.9, 0.45],
            },
          },
        };

        const secondPrepared = prepareFrame();

        expect(secondPrepared.entries[0]?.values).toBe(
          firstPrepared.entries[0]?.values,
        );
        expect(secondPrepared.entries[1]?.values).not.toBe(
          firstPrepared.entries[1]?.values,
        );
      },
    );
  });

  test("rebuilds chart data buffers when the frame shape changes", async () => {
    const setDataSnapshots: readonly unknown[][] = [];

    await withSpectrumRendererHarness(
      {
        deps: {
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
        },
        seedState(state) {
          state.transport.wsState.value = "connected";
          installClientSpectra(state, [
            {
              client: makeClient("sensor-a", "Front Right Wheel"),
              spectrum: makeSpectrum(),
            },
          ]);
        },
      },
      async ({ prepareFrame, renderer, state }) => {
        renderer.renderPreparedFrame(prepareFrame());
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

        renderer.renderPreparedFrame(prepareFrame());
        await flushSignalUpdates();

        expect(setDataSnapshots).toHaveLength(2);
        expect(setDataSnapshots[0]).not.toBe(setDataSnapshots[1]);
      },
    );
  });
});

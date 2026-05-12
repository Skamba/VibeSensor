import { beforeEach, describe, expect, test } from "vitest";
import type { SpectrumChart } from "../src/spectrum_chart";
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

  test("updates chart data when only spectrum values change", async () => {
    const setDataSnapshots: number[][][] = [];

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
                  setDataSnapshots.push(
                    (data as readonly number[][]).map((row) => [...row]),
                  );
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

        expect(setDataSnapshots).toHaveLength(2);
        const latestSeries = setDataSnapshots.at(-1)?.[1] ?? [];
        expect(latestSeries).toHaveLength(3);
        expect(latestSeries.every((value) => Number.isFinite(value))).toBe(
          true,
        );
        expect(latestSeries[0]).toBeGreaterThan(latestSeries[2] ?? 0);
      },
    );
  });

  test("refreshes chart bands without losing prepared spectrum data", async () => {
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
          basis_speed_source: null,
          wheel: { rpm: 600, mode: null, reason: null },
          engine: { rpm: 1800, mode: null, reason: null },
          driveshaft: { rpm: 600, mode: null, reason: null },
          order_bands: [
            {
              key: "wheel_1x",
              center_hz: 10,
              tolerance: 0.1,
            },
          ],
        };

        const refreshed = renderer.refreshPreparedFrameMetadata();

        expect(refreshed.hasData).toBe(true);
        expect(refreshed.chartBands).toHaveLength(1);
      },
    );
  });

  test("updates chart data when the frame shape changes", async () => {
    const setDataSnapshots: number[][][] = [];

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
                  setDataSnapshots.push(
                    (data as readonly number[][]).map((row) => [...row]),
                  );
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
        expect(setDataSnapshots.at(-1)?.[0]).toEqual([10, 20, 30, 40]);
        const latestSeries = setDataSnapshots.at(-1)?.[1] ?? [];
        expect(latestSeries).toHaveLength(4);
        expect(latestSeries.every((value) => Number.isFinite(value))).toBe(
          true,
        );
        expect(latestSeries[0]).toBeGreaterThan(latestSeries[3] ?? 0);
      },
    );
  });
});

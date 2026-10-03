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

describe("createSpectrumRenderer cache reuse", () => {
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
        renderer.render(firstPrepared);
        await flushSignalUpdates();

        state.spectra.value = {
          clients: {
            "sensor-a": {
              ...getRequiredClientSpectrum(state, "sensor-a"),
              combined: [0.9, 0.7, 0.45],
            },
          },
        };

        const nextPrepared = prepareFrame();
        renderer.render(nextPrepared);
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
          state.wsConnected.value = true;
          installClientSpectra(state, [
            {
              client: makeClient("sensor-a", "Front Right Wheel"),
              spectrum: makeSpectrum(),
            },
          ]);
        },
      },
      async ({ prepareFrame, renderer, state }) => {
        renderer.render(prepareFrame());
        await flushSignalUpdates();

        state.spectra.value = {
          clients: {
            "sensor-a": {
              ...getRequiredClientSpectrum(state, "sensor-a"),
              freq: [10, 20, 30, 40],
              combined: [1, 0.7, 0.4, 0.2],
            },
          },
        };

        renderer.render(prepareFrame());
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

import { beforeEach, describe, expect, test } from "vitest";

import { effect, signal } from "@preact/signals";
import type {
  CreateSpectrumChartDeps,
  SpectrumChart,
} from "../src/spectrum_chart";
import {
  createDeferred,
  flushSignalUpdates,
  installWindowGlobal,
} from "./async_test_helpers";
import {
  installClientSpectra,
  makeClient,
  makeSpectrum,
  withSpectrumRendererHarness,
} from "./spectrum_canvas_renderer_test_support";

describe("createSpectrumRenderer chart lifecycle", () => {
  beforeEach(() => {
    installWindowGlobal();
  });

  test("queues the first render until the chart module finishes loading", async () => {
    const chartModule = createDeferred<{
      createSpectrumChart: (deps: CreateSpectrumChartDeps) => SpectrumChart;
    }>();
    const createdCharts: Array<{
      dataSnapshots: Array<readonly unknown[]>;
      seriesCount: number;
    }> = [];

    function createFakeSpectrumChart(
      deps: CreateSpectrumChartDeps,
    ): SpectrumChart {
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

    await withSpectrumRendererHarness(
      {
        deps: {
          loadChartModule: () => chartModule.promise,
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
        renderer.render(prepared);

        expect(state.chartLoading.value).toBe(true);
        expect(createdCharts).toHaveLength(0);

        chartModule.resolve({
          createSpectrumChart: createFakeSpectrumChart,
        });
        await flushSignalUpdates();

        expect(state.chartLoading.value).toBe(false);
        expect(state.chartLoadError.value).toBeNull();
        expect(createdCharts).toHaveLength(1);
        expect(createdCharts[0]?.dataSnapshots.at(-1)?.[0]).toEqual([
          10, 15, 20,
        ]);
        expect(createdCharts[0]?.seriesCount).toBe(2);
      },
    );
  });

  test("passes reactive chart text updates through the factory signals", async () => {
    const axisTexts: string[] = [];
    let createCalls = 0;
    const locale = signal("en");

    await withSpectrumRendererHarness(
      {
        deps: {
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
          t: (key) => `${locale.value}:${key}`,
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
      async ({ prepareFrame, renderer }) => {
        const prepared = prepareFrame();
        renderer.render(prepared);
        await flushSignalUpdates();

        locale.value = "nl";
        await flushSignalUpdates();

        expect(createCalls).toBe(1);
        expect(axisTexts).toContain("en:chart.axis.hz");
        expect(axisTexts.at(-1)).toBe("nl:chart.axis.hz");
      },
    );
  });
});

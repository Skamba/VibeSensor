import { beforeEach, describe, expect, test } from "vitest";
import { effect } from "../src/app/ui_signals";
import type { CreateSpectrumChartDeps, SpectrumChart } from "../src/spectrum_chart";
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

describe("createSpectrumCanvasRenderer chart lifecycle", () => {
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
      async ({ renderer, state }) => {
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
        expect(createdCharts[0]?.dataSnapshots.at(-1)?.[0]).toEqual([10, 15, 20]);
        expect(createdCharts[0]?.seriesCount).toBe(2);
      },
    );
  });

  test("passes reactive chart text updates through the factory signals", async () => {
    const axisTexts: string[] = [];
    let createCalls = 0;
    let localeState: { shell: { lang: { value: string } } } | null = null;

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
          t: (key) => `${localeState?.shell.lang.value ?? "en"}:${key}`,
        },
        seedState(state) {
          localeState = state;
          installClientSpectra(state, [
            {
              client: makeClient("sensor-a", "Front Right Wheel"),
              spectrum: makeSpectrum(),
            },
          ]);
        },
      },
      async ({ renderer, state }) => {
        const prepared = renderer.prepareFrame();
        renderer.renderPreparedFrame(prepared);
        await flushSignalUpdates();

        state.shell.lang.value = "nl";
        await flushSignalUpdates();

        expect(createCalls).toBe(1);
        expect(axisTexts).toContain("en:chart.axis.hz");
        expect(axisTexts.at(-1)).toBe("nl:chart.axis.hz");
      },
    );
  });

  test("uses redraw instead of setData for decoration-only refreshes", async () => {
    let redrawCalls = 0;
    let setDataCalls = 0;

    await withSpectrumRendererHarness(
      {
        deps: {
          getBandsVisible: () => true,
          getChartBands: () => [
            {
              label: "Wheel",
              min_hz: 9,
              max_hz: 11,
              color: "#fff",
            },
          ],
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
      async ({ renderer }) => {
        renderer.renderPreparedFrame(renderer.prepareFrame());
        await flushSignalUpdates();
        setDataCalls = 0;
        redrawCalls = 0;

        renderer.refreshDecorations();

        expect(redrawCalls).toBe(1);
        expect(setDataCalls).toBe(0);
      },
    );
  });
});

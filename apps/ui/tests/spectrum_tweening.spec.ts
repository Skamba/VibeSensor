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

describe("createSpectrumCanvasRenderer tween cadence", () => {
  beforeEach(() => {
    installWindowGlobal();
  });

  test("animates near-budget heavy frames without recalculating scales", async () => {
    const animationStarts: number[] = [];
    let redrawCalls = 0;
    const resetScaleValues: Array<boolean | undefined> = [];
    const renderTimesMs = [1_000, 1_100];

    await withSpectrumRendererHarness(
      {
        deps: {
          createAnimation: ({ durationMs, onFrame }) => ({
            start() {
              animationStarts.push(durationMs);
              onFrame(0.5);
            },
            stop() {},
          }),
          loadChartModule: async () => ({
            createSpectrumChart(): SpectrumChart {
              return {
                destroy() {},
                redraw(rebuildPaths, recalcAxes) {
                  expect(rebuildPaths).toBe(true);
                  expect(recalcAxes).toBe(false);
                  redrawCalls += 1;
                },
                resize() {},
                setData(_data, resetScales) {
                  resetScaleValues.push(resetScales);
                },
                setSeriesIsolation() {},
              };
            },
          }),
          nowMs: () => renderTimesMs.shift() ?? 0,
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
        resetScaleValues.length = 0;
        redrawCalls = 0;

        state.spectrum.spectra.value = {
          clients: {
            "sensor-a": {
              ...getRequiredClientSpectrum(state, "sensor-a"),
              combined: [0.9, 0.7, 0.45],
            },
          },
        };

        renderer.renderPreparedFrame(prepareFrame());
        await flushSignalUpdates();

        expect(animationStarts[0]).toBeGreaterThan(0);
        expect(animationStarts[0]).toBeLessThan(180);
        expect(resetScaleValues.at(-1)).toBe(false);
        expect(redrawCalls).toBe(1);
      },
    );
  });

  test("still suppresses tween animations for genuinely high-cadence heavy frames", async () => {
    const animationStarts: number[] = [];
    const renderTimesMs = [1_000, 1_050];

    await withSpectrumRendererHarness(
      {
        deps: {
          createAnimation: ({ durationMs }) => ({
            start() {
              animationStarts.push(durationMs);
            },
            stop() {},
          }),
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
          nowMs: () => renderTimesMs.shift() ?? 0,
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
              combined: [0.9, 0.7, 0.45],
            },
          },
        };

        renderer.renderPreparedFrame(prepareFrame());
        await flushSignalUpdates();

        expect(animationStarts).toEqual([]);
      },
    );
  });
});

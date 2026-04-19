import { expect, test } from "@playwright/test";

import type { SpectrumChart } from "../src/spectrum_chart";
import { flushSignalUpdates, installWindowGlobal } from "./async_test_helpers";
import {
  getRequiredClientSpectrum,
  installClientSpectra,
  makeClient,
  makeSpectrum,
  withSpectrumRendererHarness,
} from "./spectrum_canvas_renderer_test_support";

test.describe("createSpectrumCanvasRenderer tween cadence", () => {
  test.beforeEach(() => {
    installWindowGlobal();
  });

  test("keeps tween animations for near-budget heavy frames with shorter duration", async () => {
    const animationStarts: number[] = [];
    const renderTimesMs = [1_000, 1_100];

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
      async ({ renderer, state }) => {
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

        expect(animationStarts).toEqual([75]);
      },
    );
  });

  test("redraws tween frames when setData skips scale recalculation", async () => {
    let redrawCalls = 0;
    let setDataCalls = 0;
    const renderTimesMs = [1_000, 1_165];

    await withSpectrumRendererHarness(
      {
        deps: {
          createAnimation: ({ onFrame }) => ({
            start() {
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
                  expect(resetScales).toBe(false);
                  setDataCalls += 1;
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
      async ({ renderer, state }) => {
        renderer.renderPreparedFrame(renderer.prepareFrame());
        await flushSignalUpdates();
        setDataCalls = 0;
        redrawCalls = 0;

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

        expect(setDataCalls).toBe(1);
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
      async ({ renderer, state }) => {
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
      },
    );
  });

  test("keeps tween animations enabled when heavy frames arrive slower than the tween budget", async () => {
    const animationStarts: number[] = [];
    const renderTimesMs = [1_000, 1_250];

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
      async ({ renderer, state }) => {
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
      },
    );
  });
});

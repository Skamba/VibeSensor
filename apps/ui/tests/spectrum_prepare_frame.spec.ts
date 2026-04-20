import { beforeEach, describe, expect, test } from "vitest";
import { installWindowGlobal } from "./async_test_helpers";
import {
  installClientSpectra,
  makeClient,
  makeSpectrum,
  withSpectrumRendererHarness,
} from "./spectrum_canvas_renderer_test_support";

describe("createSpectrumCanvasRenderer frame preparation", () => {
  beforeEach(() => {
    installWindowGlobal();
  });

  test("prepares aligned dB series without shell DOM bindings", async () => {
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
      ({ renderer }) => {
        const prepared = renderer.prepareFrame();

        expect(prepared.hasData).toBe(true);
        expect(prepared.freqAxis).toEqual([10, 15, 20]);
        expect(prepared.entries.map((entry) => entry.id)).toEqual(["sensor-a", "sensor-b"]);
        expect(prepared.frame?.values[1]).toHaveLength(3);
        expect(prepared.entries[1]?.values.every((value) => Number.isFinite(value))).toBe(true);
        expect(prepared.entries[1]?.values[0]).toBeGreaterThan(prepared.entries[1]?.values[2] ?? 0);
      },
    );
  });
});

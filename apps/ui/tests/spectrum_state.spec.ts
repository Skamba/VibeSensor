import { describe, expect, test } from "vitest";
import { applySpectrumTick } from "../src/app/spectrum_state";
import type { SpectrumFrameData } from "../src/transport/live_models";

function makeStrengthMetrics(vibrationStrengthDb: number) {
  return {
    noise_floor_amp_g: 0,
    peak_amp_g: 0,
    strength_bucket: null,
    top_peaks: [],
    vibration_strength_db: vibrationStrengthDb,
  };
}

describe("applySpectrumTick", () => {
  const heavyFrame: SpectrumFrameData = {
    clients: {
      sensor1: {
        combined: [0.01, 0.02, 0.03],
        freq: [1, 2, 3],
        strength_metrics: makeStrengthMetrics(12),
      },
    },
  };

  test("keeps previous frame and data flag when current tick omits spectra", () => {
    const updated = applySpectrumTick(heavyFrame, true, null);

    expect(updated.spectra).toBe(heavyFrame);
    expect(updated.hasSpectrumData).toBe(true);
    expect(updated.hasNewSpectrumFrame).toBe(false);
  });

  test("stays empty before first heavy frame when spectra are still missing", () => {
    const updated = applySpectrumTick({ clients: {} }, false, null);

    expect(updated.spectra).toEqual({ clients: {} });
    expect(updated.hasSpectrumData).toBe(false);
    expect(updated.hasNewSpectrumFrame).toBe(false);
  });
});

import { describe, expect, test } from "vitest";

import {
  convertSpectrumAmplitudesToDbInPlace,
  spectrumDbDisplayRangeFromDataBounds,
  spectrumDbToMg,
} from "../src/spectrum";

describe("spectrum dB display range", () => {
  test.each([
    [Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, [0, 100]],
    [0, 30.8, [0, 40]],
    [0, 4, [0, 20]],
    [0, 98, [0, 100]],
  ])("keeps spectra readable for data bounds %s..%s", (min, max, expected) => {
    expect(spectrumDbDisplayRangeFromDataBounds(min, max)).toEqual(expected);
  });
});

describe("spectrum amplitude scale", () => {
  test("a steady tone's peak reads the mg the report gives it: the three axes as a vector", () => {
    // A 30 mg tone on one axis: the combined spectrum (the RMS over the
    // three axes) holds 30 / sqrt(3) mg at its bin.
    const values = [0.03 / Math.sqrt(3)];
    convertSpectrumAmplitudesToDbInPlace(values);
    expect(spectrumDbToMg(values[0])).toBeCloseTo(30, 6);
  });
});

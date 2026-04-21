import { describe, expect, test } from "vitest";

import { spectrumDbDisplayRangeFromDataBounds } from "../src/spectrum";

describe("spectrum dB display range", () => {
  test("keeps the canonical full range when no finite data bounds exist", () => {
    expect(
      spectrumDbDisplayRangeFromDataBounds(
        Number.POSITIVE_INFINITY,
        Number.NEGATIVE_INFINITY,
      ),
    ).toEqual([0, 100]);
  });

  test("uses a compact range for low-amplitude live spectra", () => {
    expect(spectrumDbDisplayRangeFromDataBounds(0, 30.8)).toEqual([0, 40]);
  });

  test("preserves a minimum readable span for quiet spectra", () => {
    expect(spectrumDbDisplayRangeFromDataBounds(0, 4)).toEqual([0, 20]);
  });

  test("never expands beyond the canonical maximum", () => {
    expect(spectrumDbDisplayRangeFromDataBounds(0, 98)).toEqual([0, 100]);
  });
});

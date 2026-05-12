import { describe, expect, test } from "vitest";

import { spectrumDbDisplayRangeFromDataBounds } from "../src/spectrum";

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

import { describe, expect, test } from "vitest";

import {
  buildSpectrumChartTickValues,
  calculateSpectrumChartRanges,
  createSpectrumChartBox,
  findClosestSpectrumChartIndex,
  normalizeSpectrumChartData,
  projectSpectrumChartValue,
} from "../src/spectrum_chart_model";

describe("spectrum chart model", () => {
  test("normalizes empty chart data without DOM or canvas", () => {
    expect(normalizeSpectrumChartData([])).toEqual([[]]);
  });

  test("calculates visible-series ranges from finite spectrum values", () => {
    const ranges = calculateSpectrumChartRanges(
      [
        [10, 20, 30],
        [0, 10, 30],
        [0, 80, 90],
      ],
      [1],
    );

    expect(ranges.x).toEqual({ min: 10, max: 30 });
    expect(ranges.y).toEqual({ min: 0, max: 40 });
  });

  test("falls back to all data series when no series is visible", () => {
    const ranges = calculateSpectrumChartRanges(
      [
        [10, 20],
        [10, 20],
        [70, 80],
      ],
      [],
    );

    expect(ranges.y).toEqual({ min: 0, max: 90 });
  });

  test("projects ticks and cursor indexes from the headless chart box", () => {
    const box = createSpectrumChartBox(400, 260);
    const xRange = { min: 10, max: 30 };

    expect(box).toEqual({ top: 16, left: 54, width: 330, height: 208 });
    expect(buildSpectrumChartTickValues(xRange, 3)).toEqual([10, 20, 30]);
    expect(projectSpectrumChartValue(20, xRange, box.left, box.width)).toBe(
      219,
    );
    expect(findClosestSpectrumChartIndex([10, 20, 30], 225, xRange, box)).toBe(
      1,
    );
  });
});

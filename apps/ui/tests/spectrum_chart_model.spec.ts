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

  test.each([
    {
      name: "visible series",
      visibleSeriesIndexes: [1],
      data: [
        [10, 20, 30],
        [0, 10, 30],
        [0, 80, 90],
      ],
      expected: {
        x: { min: 10, max: 30 },
        y: { min: 0, max: 40 },
      },
    },
    {
      name: "all series when none are isolated",
      visibleSeriesIndexes: [],
      data: [
        [10, 20],
        [10, 20],
        [70, 80],
      ],
      expected: {
        x: { min: 10, max: 20 },
        y: { min: 0, max: 90 },
      },
    },
  ])("calculates readable ranges for $name", ({
    data,
    expected,
    visibleSeriesIndexes,
  }) => {
    expect(calculateSpectrumChartRanges(data, visibleSeriesIndexes)).toEqual(
      expected,
    );
  });

  test("maps axis ticks and cursor positions to spectrum values", () => {
    const box = createSpectrumChartBox(400, 260);
    const xRange = { min: 10, max: 30 };
    const cursorX = projectSpectrumChartValue(20, xRange, box.left, box.width);

    expect(buildSpectrumChartTickValues(xRange, 3)).toEqual([10, 20, 30]);
    expect(
      findClosestSpectrumChartIndex([10, 20, 30], cursorX, xRange, box),
    ).toBe(1);
  });
});

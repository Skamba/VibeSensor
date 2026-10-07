import { describe, expect, test } from "vitest";

import {
  buildSpectrumAmplitudeTicks,
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
  ])(
    "calculates readable ranges for $name",
    ({ data, expected, visibleSeriesIndexes }) => {
      expect(calculateSpectrumChartRanges(data, visibleSeriesIndexes)).toEqual(
        expected,
      );
    },
  );

  test("maps axis ticks and cursor positions to spectrum values", () => {
    const box = createSpectrumChartBox(400, 260);
    const xRange = { min: 10, max: 30 };
    const cursorX = projectSpectrumChartValue(20, xRange, box.left, box.width);

    expect(buildSpectrumChartTickValues(xRange, 3)).toEqual([10, 20, 30]);
    expect(
      findClosestSpectrumChartIndex([10, 20, 30], cursorX, xRange, box),
    ).toBe(1);
  });

  test("frequency ticks land on round 1-2-5 steps", () => {
    expect(buildSpectrumChartTickValues({ min: 0, max: 200 }, 6)).toEqual([
      0, 50, 100, 150, 200,
    ]);
    expect(buildSpectrumChartTickValues({ min: 3.3, max: 187.5 }, 6)).toEqual([
      50, 100, 150,
    ]);
    expect(buildSpectrumChartTickValues({ min: 0, max: 1 }, 6)).toEqual([
      0, 0.2, 0.4, 0.6, 0.8, 1,
    ]);
  });

  test("amplitude ticks are round mg values on the dB scale", () => {
    const mg = (range: { min: number; max: number }) =>
      buildSpectrumAmplitudeTicks(range, 7).map((tick) => tick.mg);
    // dB re 0.1 mg: 0 dB is 0.1 mg, every 20 dB is ten times more.
    expect(mg({ min: 0, max: 30 })).toEqual([0.1, 0.2, 0.5, 1, 2]);
    expect(mg({ min: 0, max: 80 })).toEqual([0.1, 1, 10, 100, 1000]);
    const [tenMg] = buildSpectrumAmplitudeTicks({ min: 39, max: 41 }, 7);
    expect(tenMg?.mg).toBe(10);
    expect(tenMg?.db).toBeCloseTo(40, 9);
  });
});

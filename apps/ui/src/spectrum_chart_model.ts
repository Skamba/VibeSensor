import { spectrumDbDisplayRangeFromDataBounds } from "./spectrum";

export interface SpectrumChartRange {
  max: number;
  min: number;
}

export interface SpectrumChartBox {
  height: number;
  left: number;
  top: number;
  width: number;
}

export interface SpectrumChartRanges {
  x: SpectrumChartRange;
  y: SpectrumChartRange;
}

type SpectrumChartData = number[][];

const EMPTY_DATA: SpectrumChartData = [[]];

export function normalizeSpectrumChartData(
  data: SpectrumChartData,
): SpectrumChartData {
  return data.length ? data : EMPTY_DATA;
}

export function createSpectrumChartBox(
  width: number,
  height: number,
): SpectrumChartBox {
  const left = 54;
  const right = 16;
  const top = 16;
  const bottom = 36;
  return {
    top,
    left,
    width: Math.max(1, width - left - right),
    height: Math.max(1, height - top - bottom),
  };
}

export function calculateSpectrumChartRanges(
  data: SpectrumChartData,
  visibleSeriesIndexes: readonly number[],
): SpectrumChartRanges {
  const freqAxis = data[0] ?? [];
  const xMin = freqAxis[0] ?? 0;
  const xMax = freqAxis[freqAxis.length - 1] ?? Math.max(1, xMin);

  let dataMin = Number.POSITIVE_INFINITY;
  let dataMax = Number.NEGATIVE_INFINITY;
  let sawValue = false;
  const sourceIndexes = visibleSeriesIndexes.length
    ? visibleSeriesIndexes
    : Array.from(
        { length: Math.max(0, data.length - 1) },
        (_, index) => index + 1,
      );
  for (const seriesIndex of sourceIndexes) {
    const series = data[seriesIndex];
    if (!series) {
      continue;
    }
    for (const value of series) {
      if (!Number.isFinite(value)) {
        continue;
      }
      sawValue = true;
      dataMin = Math.min(dataMin, value);
      dataMax = Math.max(dataMax, value);
    }
  }

  if (!sawValue) {
    return {
      x: { min: xMin, max: xMax > xMin ? xMax : xMin + 1 },
      y: { min: -120, max: 0 },
    };
  }

  const [min, max] = spectrumDbDisplayRangeFromDataBounds(dataMin, dataMax);
  return {
    x: { min: xMin, max: xMax > xMin ? xMax : xMin + 1 },
    y: { min, max: max > min ? max : min + 1 },
  };
}

export function projectSpectrumChartValue(
  value: number,
  range: SpectrumChartRange,
  start: number,
  span: number,
): number {
  const denominator = range.max - range.min || 1;
  return start + ((value - range.min) / denominator) * span;
}

export function buildSpectrumChartTickValues(
  range: SpectrumChartRange,
  count: number,
): number[] {
  if (count <= 1) {
    return [range.min];
  }
  const step = (range.max - range.min) / (count - 1 || 1);
  const ticks: number[] = [];
  for (let index = 0; index < count; index += 1) {
    ticks.push(range.min + step * index);
  }
  return ticks;
}

export function findClosestSpectrumChartIndex(
  freqAxis: readonly number[],
  x: number,
  xRange: SpectrumChartRange | null,
  bbox: Pick<SpectrumChartBox, "left" | "width">,
): number | null {
  if (freqAxis.length === 0 || xRange === null) {
    return null;
  }
  const freqValue =
    xRange.min +
    ((x - bbox.left) / (bbox.width || 1)) * (xRange.max - xRange.min);
  let low = 0;
  let high = freqAxis.length - 1;
  while (low < high) {
    const mid = Math.floor((low + high) / 2);
    const nextValue = freqAxis[mid];
    if ((nextValue ?? 0) < freqValue) {
      low = mid + 1;
    } else {
      high = mid;
    }
  }
  const candidate = low;
  const previous = Math.max(0, candidate - 1);
  const candidateDistance = Math.abs(
    (freqAxis[candidate] ?? freqValue) - freqValue,
  );
  const previousDistance = Math.abs(
    (freqAxis[previous] ?? freqValue) - freqValue,
  );
  return previousDistance <= candidateDistance ? previous : candidate;
}

import {
  spectrumDbDisplayRangeFromDataBounds,
  spectrumDbToMg,
  spectrumMgToDb,
} from "./spectrum";

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

/** The round 1-2-5 step that splits `span` into about `count` intervals. */
function niceStep(span: number, count: number): number {
  const raw = span / Math.max(1, count);
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].find((m) => m * magnitude >= raw) ?? 10;
  return step * magnitude;
}

/** Round frequency ticks (multiples of a 1-2-5 step) inside the range. */
export function buildSpectrumChartTickValues(
  range: SpectrumChartRange,
  count: number,
): number[] {
  const span = range.max - range.min;
  if (count <= 1 || !(span > 0)) {
    return [range.min];
  }
  const step = niceStep(span, count - 1);
  const ticks: number[] = [];
  const first = Math.ceil(range.min / step - 1e-9);
  for (let n = first; n * step <= range.max + step * 1e-9; n += 1) {
    // Rounded so 0.1 steps do not print as 0.30000000000000004.
    ticks.push(Number((n * step).toPrecision(12)));
  }
  return ticks;
}

export interface AmplitudeTick {
  /** Position on the chart's dB scale. */
  db: number;
  /** The amplitude the tick stands for, in mg. */
  mg: number;
}

/**
 * Amplitude ticks for the dB-scaled axis, labelled in mg: decades (0.1, 1,
 * 10, 100 mg ...), with 2 and 5 in between when the range spans few decades.
 */
export function buildSpectrumAmplitudeTicks(
  range: SpectrumChartRange,
  maxCount: number,
): AmplitudeTick[] {
  const low = spectrumDbToMg(range.min);
  const high = spectrumDbToMg(range.max);
  const ticks = (mantissas: readonly number[]) => {
    const out: AmplitudeTick[] = [];
    for (
      let exponent = Math.floor(Math.log10(low));
      10 ** exponent <= high * (1 + 1e-9);
      exponent += 1
    ) {
      for (const mantissa of mantissas) {
        const mg = Number((mantissa * 10 ** exponent).toPrecision(6));
        if (mg >= low * (1 - 1e-9) && mg <= high * (1 + 1e-9)) {
          out.push({ db: spectrumMgToDb(mg), mg });
        }
      }
    }
    return out;
  };
  const detailed = ticks([1, 2, 5]);
  return detailed.length <= maxCount ? detailed : ticks([1]);
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

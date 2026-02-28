export interface SpectrumHeavyFrame {
  seriesIds: string[];
  freq: number[];
  values: number[][];
}

const FREQ_EPSILON = 1e-6;

export function areHeavyFramesCompatible(previous: SpectrumHeavyFrame | null, next: SpectrumHeavyFrame): boolean {
  if (!previous) return false;
  if (previous.seriesIds.length !== next.seriesIds.length) return false;
  if (previous.values.length !== next.values.length) return false;
  for (let i = 0; i < previous.seriesIds.length; i++) {
    if (previous.seriesIds[i] !== next.seriesIds[i]) return false;
  }
  if (previous.freq.length !== next.freq.length) return false;
  for (let i = 0; i < previous.freq.length; i++) {
    if (Math.abs(previous.freq[i] - next.freq[i]) > FREQ_EPSILON) return false;
  }
  for (let i = 0; i < previous.values.length; i++) {
    if (previous.values[i].length !== next.values[i].length || previous.values[i].length !== previous.freq.length) return false;
  }
  for (let i = 0; i < next.values.length; i++) {
    if (next.values[i].length !== next.freq.length) return false;
  }
  return true;
}

export function interpolateHeavyFrame(previous: SpectrumHeavyFrame, next: SpectrumHeavyFrame, alpha: number): SpectrumHeavyFrame {
  const t = Math.min(1, Math.max(0, alpha));
  const outValues = next.values.map((series, seriesIndex) =>
    series.map((toValue, pointIndex) => {
      const fromValue = previous.values[seriesIndex][pointIndex];
      return fromValue + (toValue - fromValue) * t;
    }),
  );
  return {
    seriesIds: next.seriesIds.slice(),
    freq: next.freq.slice(),
    values: outValues,
  };
}

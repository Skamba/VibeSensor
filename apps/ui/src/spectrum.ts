import {
  SPECTRUM_DB_MAX,
  SPECTRUM_DB_MIN,
  SPECTRUM_DB_REFERENCE_AMP_G,
  SPECTRUM_MIN_RENDER_AMP_G,
} from "./config";

const SPECTRUM_LOG10_REF = Math.log10(SPECTRUM_DB_REFERENCE_AMP_G);
const SPECTRUM_DISPLAY_HEADROOM_DB = 6;
const SPECTRUM_DISPLAY_MIN_SPAN_DB = 20;
const SPECTRUM_DISPLAY_STEP_DB = 10;

export function convertSpectrumAmplitudesToDbInPlace(values: number[]): void {
  for (let i = 0; i < values.length; i += 1) {
    const amplitude = values[i];
    const safe = Number.isFinite(amplitude) && amplitude > 0
      ? Math.max(amplitude, SPECTRUM_MIN_RENDER_AMP_G)
      : SPECTRUM_MIN_RENDER_AMP_G;
    const db = 20 * (Math.log10(safe) - SPECTRUM_LOG10_REF);
    values[i] = Math.max(SPECTRUM_DB_MIN, Math.min(SPECTRUM_DB_MAX, db));
  }
}

export function spectrumDbDisplayRangeFromDataBounds(
  _dataMin: number,
  dataMax: number,
): [number, number] {
  if (!Number.isFinite(dataMax)) {
    return [SPECTRUM_DB_MIN, SPECTRUM_DB_MAX];
  }

  const paddedMax = Math.max(
    SPECTRUM_DB_MIN + SPECTRUM_DISPLAY_MIN_SPAN_DB,
    dataMax + SPECTRUM_DISPLAY_HEADROOM_DB,
  );
  const roundedMax = Math.ceil(paddedMax / SPECTRUM_DISPLAY_STEP_DB)
    * SPECTRUM_DISPLAY_STEP_DB;
  return [
    SPECTRUM_DB_MIN,
    Math.max(
      SPECTRUM_DB_MIN + SPECTRUM_DISPLAY_MIN_SPAN_DB,
      Math.min(SPECTRUM_DB_MAX, roundedMax),
    ),
  ];
}

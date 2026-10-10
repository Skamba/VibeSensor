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

/** A chart value (dB re 0.1 mg) back as the amplitude in mg it was drawn from. */
export function spectrumDbToMg(db: number): number {
  return SPECTRUM_DB_REFERENCE_AMP_G * 1000 * 10 ** (db / 20);
}

/** An amplitude in mg as the chart's dB value (the inverse of `spectrumDbToMg`). */
export function spectrumMgToDb(mg: number): number {
  return 20 * (Math.log10(mg / 1000) - SPECTRUM_LOG10_REF);
}

/**
 * The combined spectrum is the RMS over the three axes; the chart draws the
 * axes as a vector (`sqrt(x² + y² + z²)`, `sqrt(3)` times it), the scale of
 * every mg in the report: a steady tone's peak reads the mg the report gives it.
 */
const AXES_AS_VECTOR = Math.sqrt(3);

/** Combined-spectrum amplitudes (g) as chart values (dB re 0.1 mg), the axes as a vector. */
export function convertSpectrumAmplitudesToDbInPlace(values: number[]): void {
  for (let i = 0; i < values.length; i += 1) {
    const amplitude = values[i] * AXES_AS_VECTOR;
    const safe =
      Number.isFinite(amplitude) && amplitude > 0
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
  const roundedMax =
    Math.ceil(paddedMax / SPECTRUM_DISPLAY_STEP_DB) * SPECTRUM_DISPLAY_STEP_DB;
  return [
    SPECTRUM_DB_MIN,
    Math.max(
      SPECTRUM_DB_MIN + SPECTRUM_DISPLAY_MIN_SPAN_DB,
      Math.min(SPECTRUM_DB_MAX, roundedMax),
    ),
  ];
}

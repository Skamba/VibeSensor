export interface FreshnessClient {
  sample_rate_hz?: number | null;
  frame_samples: number;
}

const LEGACY_FRESH_THRESHOLD_MS = 250;
const LEGACY_DELAYED_THRESHOLD_MS = 1000;
const FRESH_CADENCE_MULTIPLIER = 1.25;
const DELAYED_CADENCE_MULTIPLIER = 2.5;

export function deriveDataFreshnessThresholds(
  clients: readonly FreshnessClient[],
): { freshMs: number; delayedMs: number } {
  let slowestCadenceMs = 0;
  for (const client of clients) {
    const sampleRateHz = Number(client.sample_rate_hz);
    const frameSamples = Number(client.frame_samples);
    if (
      !Number.isFinite(sampleRateHz) ||
      !Number.isFinite(frameSamples) ||
      sampleRateHz <= 0 ||
      frameSamples <= 0
    ) {
      continue;
    }
    slowestCadenceMs = Math.max(slowestCadenceMs, (frameSamples * 1000) / sampleRateHz);
  }
  if (slowestCadenceMs <= 0) {
    return {
      freshMs: LEGACY_FRESH_THRESHOLD_MS,
      delayedMs: LEGACY_DELAYED_THRESHOLD_MS,
    };
  }
  return {
    freshMs: Math.max(
      LEGACY_FRESH_THRESHOLD_MS,
      Math.ceil(slowestCadenceMs * FRESH_CADENCE_MULTIPLIER),
    ),
    delayedMs: Math.max(
      LEGACY_DELAYED_THRESHOLD_MS,
      Math.ceil(slowestCadenceMs * DELAYED_CADENCE_MULTIPLIER),
    ),
  };
}

export function classifyDataFreshness(
  ageMs: number,
  clients: readonly FreshnessClient[],
): "fresh" | "delayed" | "stale" {
  const { freshMs, delayedMs } = deriveDataFreshnessThresholds(clients);
  if (ageMs <= freshMs) {
    return "fresh";
  }
  if (ageMs <= delayedMs) {
    return "delayed";
  }
  return "stale";
}

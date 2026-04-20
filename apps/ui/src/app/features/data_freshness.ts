export interface FreshnessClient {
  sample_rate_hz: number;
  frame_samples: number;
}

const FRESH_CADENCE_MULTIPLIER = 1.25;
const DELAYED_CADENCE_MULTIPLIER = 2.5;

export function deriveDataFreshnessThresholds(
  clients: readonly FreshnessClient[],
): { freshMs: number; delayedMs: number } {
  let slowestCadenceMs = 0;
  for (const client of clients) {
    slowestCadenceMs = Math.max(
      slowestCadenceMs,
      (client.frame_samples * 1000) / client.sample_rate_hz,
    );
  }
  return {
    freshMs: Math.ceil(slowestCadenceMs * FRESH_CADENCE_MULTIPLIER),
    delayedMs: Math.ceil(slowestCadenceMs * DELAYED_CADENCE_MULTIPLIER),
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

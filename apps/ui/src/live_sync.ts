import type {
  SpectrumClientData,
  SpectrumFrameData,
} from "./transport/live_models";

/** Pure helpers for applying live payloads. */

function hasSpectrumFingerprint(
  spectra: SpectrumFrameData,
): spectra is SpectrumFrameData & { frame_fingerprint: string } {
  return typeof spectra.frame_fingerprint === "string";
}

function areNumberArraysEqual(
  left: readonly number[],
  right: readonly number[],
): boolean {
  if (left.length !== right.length) {
    return false;
  }
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) {
      return false;
    }
  }
  return true;
}

function areStrengthPeaksEqual(
  left: ReadonlyArray<
    SpectrumClientData["strength_metrics"]["top_peaks"][number]
  >,
  right: ReadonlyArray<
    SpectrumClientData["strength_metrics"]["top_peaks"][number]
  >,
): boolean {
  if (left.length !== right.length) {
    return false;
  }
  for (let index = 0; index < left.length; index += 1) {
    const leftPeak = left[index];
    const rightPeak = right[index];
    if (
      leftPeak.amp !== rightPeak.amp ||
      leftPeak.hz !== rightPeak.hz ||
      leftPeak.strength_bucket !== rightPeak.strength_bucket ||
      leftPeak.vibration_strength_db !== rightPeak.vibration_strength_db
    ) {
      return false;
    }
  }
  return true;
}

function areStrengthMetricsEqual(
  left: SpectrumClientData["strength_metrics"],
  right: SpectrumClientData["strength_metrics"],
): boolean {
  return (
    left.vibration_strength_db === right.vibration_strength_db &&
    left.peak_amp_g === right.peak_amp_g &&
    left.noise_floor_amp_g === right.noise_floor_amp_g &&
    left.strength_bucket === right.strength_bucket &&
    areStrengthPeaksEqual(left.top_peaks, right.top_peaks)
  );
}

function areSpectrumClientDataEqual(
  left: SpectrumClientData,
  right: SpectrumClientData,
): boolean {
  return (
    areNumberArraysEqual(left.freq, right.freq) &&
    areNumberArraysEqual(left.combined, right.combined) &&
    areStrengthMetricsEqual(left.strength_metrics, right.strength_metrics)
  );
}

function areSpectrumFramesEqual(
  left: SpectrumFrameData,
  right: SpectrumFrameData,
): boolean {
  const leftClientIds = Object.keys(left.clients);
  const rightClientIds = Object.keys(right.clients);
  if (leftClientIds.length !== rightClientIds.length) {
    return false;
  }
  for (const clientId of leftClientIds) {
    const leftClient = left.clients[clientId];
    const rightClient = right.clients[clientId];
    if (
      !leftClient ||
      !rightClient ||
      !areSpectrumClientDataEqual(leftClient, rightClient)
    ) {
      return false;
    }
  }
  return true;
}

/**
 * The spectra to keep after a payload: the previous object when the payload
 * has none or an identical frame (so the chart does not redraw), else the new.
 */
export function mergeSpectra(
  previous: SpectrumFrameData,
  incoming: SpectrumFrameData | null,
): SpectrumFrameData {
  if (!incoming) {
    return previous;
  }
  if (hasSpectrumFingerprint(previous) && hasSpectrumFingerprint(incoming)) {
    return previous.frame_fingerprint === incoming.frame_fingerprint
      ? previous
      : incoming;
  }
  return areSpectrumFramesEqual(previous, incoming) ? previous : incoming;
}

/**
 * Sends the selected sensor to the server once per connection: again after
 * every reconnect, and whenever the selection changes while connected.
 */
export function createSelectionSender(
  send: (clientId: string | null) => void,
): (ready: boolean, clientId: string | null) => void {
  let cycle = 0;
  let wasReady = false;
  let lastSent: string | null = null;
  return (ready, clientId) => {
    if (ready && !wasReady) {
      cycle += 1;
    }
    wasReady = ready;
    const key = `${cycle}:${clientId}`;
    if (ready && key !== lastSent) {
      lastSent = key;
      send(clientId);
    }
  };
}

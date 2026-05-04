import type { SpectrumChart } from "../spectrum_chart";
import type {
  SpectrumClientData,
  SpectrumFrameData,
} from "../transport/live_models";
import { signal } from "./ui_signals";
import type { SignalState } from "./signal_state";

export interface ChartBand {
  label: string;
  min_hz: number;
  max_hz: number;
  color: string;
}

export interface SpectrumTickUpdate {
  spectra: SpectrumFrameData;
  hasSpectrumData: boolean;
  hasNewSpectrumFrame: boolean;
}

export interface SpectrumStateValue {
  spectrumPlot: SpectrumChart | null;
  spectra: SpectrumFrameData;
  chartBands: ChartBand[];
  hasSpectrumData: boolean;
  chartLoading: boolean;
  chartLoadErrorDetail: string | null;
  framePrepareErrorDetail: string | null;
}

export type SpectrumState = SignalState<SpectrumStateValue>;

function hasRenderableSpectrumData(spectra: SpectrumFrameData): boolean {
  return Object.values(spectra.clients).some(
    (clientSpec) =>
      clientSpec.freq.length > 0 && clientSpec.combined.length > 0,
  );
}

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

export function applySpectrumTick(
  previousSpectra: SpectrumFrameData,
  previousHasSpectrumData: boolean,
  incomingSpectra: SpectrumFrameData | null,
): SpectrumTickUpdate {
  if (!incomingSpectra) {
    return {
      spectra: previousSpectra,
      hasSpectrumData: previousHasSpectrumData,
      hasNewSpectrumFrame: false,
    };
  }
  if (
    hasSpectrumFingerprint(previousSpectra) &&
    hasSpectrumFingerprint(incomingSpectra)
  ) {
    if (
      previousSpectra.frame_fingerprint === incomingSpectra.frame_fingerprint
    ) {
      return {
        spectra: previousSpectra,
        hasSpectrumData: previousHasSpectrumData,
        hasNewSpectrumFrame: false,
      };
    }
    return {
      spectra: incomingSpectra,
      hasSpectrumData: hasRenderableSpectrumData(incomingSpectra),
      hasNewSpectrumFrame: true,
    };
  }
  if (areSpectrumFramesEqual(previousSpectra, incomingSpectra)) {
    return {
      spectra: previousSpectra,
      hasSpectrumData: previousHasSpectrumData,
      hasNewSpectrumFrame: false,
    };
  }
  return {
    spectra: incomingSpectra,
    hasSpectrumData: hasRenderableSpectrumData(incomingSpectra),
    hasNewSpectrumFrame: true,
  };
}

export function createSpectrumState(): SpectrumState {
  return {
    spectrumPlot: signal<SpectrumChart | null>(null),
    spectra: signal<SpectrumFrameData>({ clients: {} }),
    chartBands: signal<ChartBand[]>([]),
    hasSpectrumData: signal(false),
    chartLoading: signal(false),
    chartLoadErrorDetail: signal<string | null>(null),
    framePrepareErrorDetail: signal<string | null>(null),
  };
}

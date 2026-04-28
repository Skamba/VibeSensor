import type { SpectrumChart } from "../spectrum_chart";
import type { WsClient, WsUiState } from "../ws";
import type {
  AdaptedClient,
  AdaptedPayload,
  RotationalSpeeds,
  SpectrumFrameData,
  SpectrumClientData,
} from "../transport/live_models";
import { defaultAnalysisSettings, defaultLocationCodes } from "../constants";
import type {
  CarRecord,
  HistoryEntry,
  HistoryInsightsPayload,
  LoggingStatusPayload,
  SpeedSourceKind,
  SpeedSourceStatusPayload,
} from "../api/types";
import { batch, signal, type Signal } from "./ui_signals";

export interface CarAspectSettings {
  tire_width_mm: number;
  tire_aspect_pct: number;
  rim_in: number;
  final_drive_ratio: number;
  current_gear_ratio: number;
  tire_deflection_factor: number;
}

export interface AnalysisTuningSettings {
  wheel_bandwidth_pct: number;
  driveshaft_bandwidth_pct: number;
  engine_bandwidth_pct: number;
  speed_uncertainty_pct: number;
  tire_diameter_uncertainty_pct: number;
  final_drive_uncertainty_pct: number;
  gear_uncertainty_pct: number;
  min_abs_band_hz: number;
  max_band_half_width_pct: number;
}

export interface VehicleSettings extends CarAspectSettings, AnalysisTuningSettings {}

const defaultCarAspectSettings: Readonly<CarAspectSettings> = {
  tire_width_mm: defaultAnalysisSettings.tire_width_mm,
  tire_aspect_pct: defaultAnalysisSettings.tire_aspect_pct,
  rim_in: defaultAnalysisSettings.rim_in,
  final_drive_ratio: defaultAnalysisSettings.final_drive_ratio,
  current_gear_ratio: defaultAnalysisSettings.current_gear_ratio,
  tire_deflection_factor: defaultAnalysisSettings.tire_deflection_factor,
};

const defaultAnalysisTuningSettings: Readonly<AnalysisTuningSettings> = {
  wheel_bandwidth_pct: defaultAnalysisSettings.wheel_bandwidth_pct,
  driveshaft_bandwidth_pct: defaultAnalysisSettings.driveshaft_bandwidth_pct,
  engine_bandwidth_pct: defaultAnalysisSettings.engine_bandwidth_pct,
  speed_uncertainty_pct: defaultAnalysisSettings.speed_uncertainty_pct,
  tire_diameter_uncertainty_pct: defaultAnalysisSettings.tire_diameter_uncertainty_pct,
  final_drive_uncertainty_pct: defaultAnalysisSettings.final_drive_uncertainty_pct,
  gear_uncertainty_pct: defaultAnalysisSettings.gear_uncertainty_pct,
  min_abs_band_hz: defaultAnalysisSettings.min_abs_band_hz,
  max_band_half_width_pct: defaultAnalysisSettings.max_band_half_width_pct,
};

export const defaultVehicleSettings: Readonly<VehicleSettings> = defaultAnalysisSettings;

const carAspectSettingKeys = [
  "tire_width_mm",
  "tire_aspect_pct",
  "rim_in",
  "final_drive_ratio",
  "current_gear_ratio",
  "tire_deflection_factor",
] as const satisfies readonly (keyof CarAspectSettings)[];

const analysisTuningSettingKeys = [
  "wheel_bandwidth_pct",
  "driveshaft_bandwidth_pct",
  "engine_bandwidth_pct",
  "speed_uncertainty_pct",
  "tire_diameter_uncertainty_pct",
  "final_drive_uncertainty_pct",
  "gear_uncertainty_pct",
  "min_abs_band_hz",
  "max_band_half_width_pct",
] as const satisfies readonly (keyof AnalysisTuningSettings)[];

type VehicleSettingsNumericPatch = Partial<
  Record<keyof VehicleSettings, number | null | undefined>
>;

export function composeVehicleSettings(
  car: CarAspectSettings,
  analysis: AnalysisTuningSettings,
): VehicleSettings {
  return {
    ...car,
    ...analysis,
  };
}

export function mergeCarAspectSettings(
  current: CarAspectSettings,
  source: VehicleSettingsNumericPatch,
): CarAspectSettings {
  const next = { ...current };
  for (const key of carAspectSettingKeys) {
    const value = source[key];
    if (typeof value === "number") {
      next[key] = value;
    }
  }
  return next;
}

export function mergeAnalysisTuningSettings(
  current: AnalysisTuningSettings,
  source: VehicleSettingsNumericPatch,
): AnalysisTuningSettings {
  const next = { ...current };
  for (const key of analysisTuningSettingKeys) {
    const value = source[key];
    if (typeof value === "number") {
      next[key] = value;
    }
  }
  return next;
}

export interface RunDetail {
  preview: HistoryInsightsPayload | null;
  previewLoading: boolean;
  previewError: string;
  insights: HistoryInsightsPayload | null;
  insightsLoading: boolean;
  insightsError: string;
  pdfLoading: boolean;
  pdfError: string;
}

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

export interface LivePayloadUpdateDeps {
  realtime: RealtimeState;
  spectrum: SpectrumState;
  adaptedPayload: AdaptedPayload;
}

export interface LivePayloadUpdateResult {
  hasSelectedClientChanged: boolean;
  selectedClient: AdaptedClient | undefined;
  hasNewSpectrumFrame: boolean;
}

function hasRenderableSpectrumData(spectra: SpectrumFrameData): boolean {
  return Object.values(spectra.clients).some((clientSpec) => clientSpec.freq.length > 0 && clientSpec.combined.length > 0);
}

function hasSpectrumFingerprint(
  spectra: SpectrumFrameData,
): spectra is SpectrumFrameData & { frame_fingerprint: string } {
  return typeof spectra.frame_fingerprint === "string";
}

function areNumberArraysEqual(left: readonly number[], right: readonly number[]): boolean {
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
  left: ReadonlyArray<SpectrumClientData["strength_metrics"]["top_peaks"][number]>,
  right: ReadonlyArray<SpectrumClientData["strength_metrics"]["top_peaks"][number]>,
): boolean {
  if (left.length !== right.length) {
    return false;
  }
  for (let index = 0; index < left.length; index += 1) {
    const leftPeak = left[index];
    const rightPeak = right[index];
    if (
      leftPeak.amp !== rightPeak.amp
      || leftPeak.hz !== rightPeak.hz
      || leftPeak.strength_bucket !== rightPeak.strength_bucket
      || leftPeak.vibration_strength_db !== rightPeak.vibration_strength_db
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
  return left.vibration_strength_db === right.vibration_strength_db
    && left.peak_amp_g === right.peak_amp_g
    && left.noise_floor_amp_g === right.noise_floor_amp_g
    && left.strength_bucket === right.strength_bucket
    && areStrengthPeaksEqual(left.top_peaks, right.top_peaks);
}

function areSpectrumClientDataEqual(left: SpectrumClientData, right: SpectrumClientData): boolean {
  return areNumberArraysEqual(left.freq, right.freq)
    && areNumberArraysEqual(left.combined, right.combined)
    && areStrengthMetricsEqual(left.strength_metrics, right.strength_metrics);
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
    if (!leftClient || !rightClient || !areSpectrumClientDataEqual(leftClient, rightClient)) {
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
  if (hasSpectrumFingerprint(previousSpectra) && hasSpectrumFingerprint(incomingSpectra)) {
    if (previousSpectra.frame_fingerprint === incomingSpectra.frame_fingerprint) {
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

export function syncSelectedRealtimeClient(realtime: RealtimeState): void {
  const clients = realtime.clients.value;
  const firstConnected = clients.find((client) => Boolean(client.connected));
  if (!realtime.selectedClientId.value && clients.length > 0) {
    realtime.selectedClientId.value = firstConnected ? firstConnected.id : clients[0]?.id ?? null;
  }
  if (
    realtime.selectedClientId.value
    && !clients.some((client) => client.id === realtime.selectedClientId.value)
  ) {
    realtime.selectedClientId.value = firstConnected
      ? firstConnected.id
      : clients.length
        ? clients[0]?.id ?? null
        : null;
  }
}

export function applyLivePayloadUpdate(deps: LivePayloadUpdateDeps): LivePayloadUpdateResult {
  let update!: LivePayloadUpdateResult;
  batch(() => {
    const { realtime, spectrum, adaptedPayload } = deps;
    const previousSelectedClientId = realtime.selectedClientId.value;
    realtime.clients.value = adaptedPayload.clients;
    const spectrumTick = applySpectrumTick(
      spectrum.spectra.value,
      spectrum.hasSpectrumData.value,
      adaptedPayload.spectra,
    );
    spectrum.spectra.value = spectrumTick.spectra;
    syncSelectedRealtimeClient(realtime);
    realtime.speedMps.value = adaptedPayload.speed_mps;
    realtime.rotationalSpeeds.value = adaptedPayload.rotational_speeds;
    spectrum.hasSpectrumData.value = spectrumTick.hasSpectrumData;
    update = {
      hasSelectedClientChanged: previousSelectedClientId !== realtime.selectedClientId.value,
      selectedClient: realtime.clients.value.find(
        (client) => client.id === realtime.selectedClientId.value,
      ),
      hasNewSpectrumFrame: spectrumTick.hasNewSpectrumFrame,
    };
  });
  return update;
}

export type SignalState<T extends object> = {
  [K in keyof T]: Signal<T[K]>;
};

export interface ShellStateValue {
  lang: string;
  speedUnit: string;
  activeViewId: string;
}

export interface TransportStateValue {
  ws: WsClient | null;
  wsState: WsUiState;
  pendingPayload: unknown | null;
  renderQueued: boolean;
  lastRenderTsMs: number;
  minRenderIntervalMs: number;
  hasReceivedPayload: boolean;
  payloadError: string | null;
}

export interface RealtimeStateValue {
  clients: AdaptedClient[];
  selectedClientId: string | null;
  speedMps: number | null;
  rotationalSpeeds: RotationalSpeeds | null;
  loggingStatus: LoggingStatusPayload;
  locationCodes: string[];
}

export interface HistoryStateValue {
  runs: HistoryEntry[];
  deleteAllRunsInFlight: boolean;
  expandedRunId: string | null;
  runDetailsById: Record<string, RunDetail>;
}

export interface CarSettingsValue {
  activeVehicleSettings: CarAspectSettings;
  cars: CarRecord[];
  carsLoaded: boolean;
  activeCarId: string | null;
}

export interface AnalysisSettingsValue {
  vehicleSettings: AnalysisTuningSettings;
}

export interface SpeedSettingsValue {
  source: SpeedSourceKind;
  manualSpeedKph: number | null;
  obdDeviceMac: string | null;
  obdDeviceName: string | null;
  resolvedSource: SpeedSourceStatusPayload["speed_source"] | null;
  gpsFallbackActive: boolean;
  gpsEffectiveSpeedKph: number | null;
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

export type ShellState = SignalState<ShellStateValue>;
export type TransportState = SignalState<TransportStateValue>;
export type RealtimeState = SignalState<RealtimeStateValue>;
export type HistoryState = SignalState<HistoryStateValue>;
export type CarSettingsState = SignalState<CarSettingsValue>;
export type AnalysisSettingsState = SignalState<AnalysisSettingsValue>;
export type SpeedSettingsState = SignalState<SpeedSettingsValue>;
export interface SettingsState {
  car: CarSettingsState;
  analysis: AnalysisSettingsState;
  speed: SpeedSettingsState;
}
export type SpectrumState = SignalState<SpectrumStateValue>;

export interface AppState {
  shell: ShellState;
  transport: TransportState;
  realtime: RealtimeState;
  history: HistoryState;
  settings: SettingsState;
  spectrum: SpectrumState;
}

export function createAppState(): AppState {
  return {
    shell: {
      lang: signal("en"),
      speedUnit: signal("kmh"),
      activeViewId: signal("dashboardView"),
    },
    transport: {
      ws: signal<WsClient | null>(null),
      wsState: signal<WsUiState>("connecting"),
      pendingPayload: signal<unknown | null>(null),
      renderQueued: signal(false),
      lastRenderTsMs: signal(0),
      minRenderIntervalMs: signal(100),
      hasReceivedPayload: signal(false),
      payloadError: signal<string | null>(null),
    },
    realtime: {
      clients: signal<AdaptedClient[]>([]),
      selectedClientId: signal<string | null>(null),
      speedMps: signal<number | null>(null),
      rotationalSpeeds: signal<RotationalSpeeds | null>(null),
      loggingStatus: signal<LoggingStatusPayload>({
        enabled: false,
        run_id: null,
        write_error: null,
        analysis_in_progress: false,
        start_time_utc: null,
        samples_written: 0,
        samples_dropped: 0,
        last_completed_run_id: null,
        last_completed_run_error: null,
        capture_readiness: null,
      }),
      locationCodes: signal(defaultLocationCodes.slice()),
    },
    history: {
      runs: signal<HistoryEntry[]>([]),
      deleteAllRunsInFlight: signal(false),
      expandedRunId: signal<string | null>(null),
      runDetailsById: signal<Record<string, RunDetail>>({}),
    },
    settings: {
      car: {
        activeVehicleSettings: signal<CarAspectSettings>({ ...defaultCarAspectSettings }),
        cars: signal<CarRecord[]>([]),
        carsLoaded: signal(false),
        activeCarId: signal<string | null>(null),
      },
      analysis: {
        vehicleSettings: signal<AnalysisTuningSettings>({ ...defaultAnalysisTuningSettings }),
      },
      speed: {
        source: signal<SpeedSourceKind>("gps"),
        manualSpeedKph: signal<number | null>(null),
        obdDeviceMac: signal<string | null>(null),
        obdDeviceName: signal<string | null>(null),
        resolvedSource: signal<SpeedSourceStatusPayload["speed_source"] | null>(null),
        gpsFallbackActive: signal(false),
        gpsEffectiveSpeedKph: signal<number | null>(null),
      },
    },
    spectrum: {
      spectrumPlot: signal<SpectrumChart | null>(null),
      spectra: signal<SpectrumFrameData>({ clients: {} }),
      chartBands: signal<ChartBand[]>([]),
      hasSpectrumData: signal(false),
      chartLoading: signal(false),
      chartLoadErrorDetail: signal<string | null>(null),
      framePrepareErrorDetail: signal<string | null>(null),
    },
  };
}

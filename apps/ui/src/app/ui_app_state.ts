import type { SpectrumChart } from "../spectrum";
import type { WsClient } from "../ws";
import type { StrengthMetricsPayload } from "../contracts/ws_payload_types";
import type { RotationalSpeeds } from "../server_payload";
import { defaultLocationCodes } from "../constants";
import type {
  CarRecord,
  HistoryEntry,
  HistoryInsightsPayload,
  LoggingStatusPayload,
} from "../api/types";

export interface LocationOption {
  code: string;
  label: string;
}

export interface VehicleSettings {
  tire_width_mm: number;
  tire_aspect_pct: number;
  rim_in: number;
  final_drive_ratio: number;
  current_gear_ratio: number;
  wheel_bandwidth_pct: number;
  driveshaft_bandwidth_pct: number;
  engine_bandwidth_pct: number;
  speed_uncertainty_pct: number;
  tire_diameter_uncertainty_pct: number;
  final_drive_uncertainty_pct: number;
  gear_uncertainty_pct: number;
  min_abs_band_hz: number;
  max_band_half_width_pct: number;
  [key: string]: number;
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

export interface ClientRow {
  id: string;
  name: string;
  connected: boolean;
  mac_address: string;
  location_code: string;
  last_seen_age_ms: number | null;
  dropped_frames: number | null;
  frames_total: number | null;
}

export interface SpectrumClientData {
  freq: number[];
  strength_metrics: StrengthMetricsPayload;
  combined: number[];
}

export interface SpectrumTickUpdate {
  spectra: { clients: Record<string, SpectrumClientData> };
  hasSpectrumData: boolean;
  hasNewSpectrumFrame: boolean;
}

export function applySpectrumTick(
  previousSpectra: { clients: Record<string, SpectrumClientData> },
  previousHasSpectrumData: boolean,
  incomingSpectra: { clients: Record<string, SpectrumClientData> } | null,
): SpectrumTickUpdate {
  if (!incomingSpectra) {
    return {
      spectra: previousSpectra,
      hasSpectrumData: previousHasSpectrumData,
      hasNewSpectrumFrame: false,
    };
  }
  const hasSpectrumData = Object.values(incomingSpectra.clients).some(
    (clientSpec) => clientSpec.freq.length > 0 && clientSpec.combined.length > 0,
  );
  return {
    spectra: incomingSpectra,
    hasSpectrumData,
    hasNewSpectrumFrame: true,
  };
}

export interface AppState {
  ws: WsClient | null;
  wsState: string;
  lang: string;
  speedUnit: string;
  clients: ClientRow[];
  selectedClientId: string | null;
  spectrumPlot: SpectrumChart | null;
  spectra: { clients: Record<string, SpectrumClientData> };
  speedMps: number | null;
  rotationalSpeeds: RotationalSpeeds | null;
  activeViewId: string;
  runs: HistoryEntry[];
  deleteAllRunsInFlight: boolean;
  expandedRunId: string | null;
  runDetailsById: Record<string, RunDetail>;
  loggingStatus: LoggingStatusPayload;
  locationOptions: LocationOption[];
  vehicleSettings: VehicleSettings;
  cars: CarRecord[];
  activeCarId: string | null;
  speedSource: string;
  manualSpeedKph: number | null;
  gpsFallbackActive: boolean;
  chartBands: ChartBand[];
  pendingPayload: unknown | null;
  renderQueued: boolean;
  lastRenderTsMs: number;
  minRenderIntervalMs: number;
  sensorsSettingsSignature: string;
  locationCodes: string[];
  hasSpectrumData: boolean;
  hasReceivedPayload: boolean;
  payloadError: string | null;
}

export function createAppState(): AppState {
  return {
    ws: null,
    wsState: "connecting",
    lang: "en",
    speedUnit: "kmh",
    clients: [],
    selectedClientId: null,
    spectrumPlot: null,
    spectra: { clients: {} },
    speedMps: null,
    rotationalSpeeds: null,
    activeViewId: "dashboardView",
    runs: [],
    deleteAllRunsInFlight: false,
    expandedRunId: null,
    runDetailsById: {},
    loggingStatus: {
      enabled: false,
      current_file: null,
      run_id: null,
      write_error: null,
      analysis_in_progress: false,
    },
    locationOptions: [],
    vehicleSettings: {
      tire_width_mm: 285,
      tire_aspect_pct: 30,
      rim_in: 21,
      final_drive_ratio: 3.08,
      current_gear_ratio: 0.64,
      wheel_bandwidth_pct: 6.0,
      driveshaft_bandwidth_pct: 5.6,
      engine_bandwidth_pct: 6.2,
      speed_uncertainty_pct: 0.6,
      tire_diameter_uncertainty_pct: 1.2,
      final_drive_uncertainty_pct: 0.2,
      gear_uncertainty_pct: 0.5,
      min_abs_band_hz: 0.4,
      max_band_half_width_pct: 8.0,
    },
    cars: [],
    activeCarId: null,
    speedSource: "gps",
    manualSpeedKph: null,
    gpsFallbackActive: false,
    chartBands: [],
    pendingPayload: null,
    renderQueued: false,
    lastRenderTsMs: 0,
    minRenderIntervalMs: 100,
    sensorsSettingsSignature: "",
    locationCodes: defaultLocationCodes.slice(),
    hasSpectrumData: false,
    hasReceivedPayload: false,
    payloadError: null,
  };
}

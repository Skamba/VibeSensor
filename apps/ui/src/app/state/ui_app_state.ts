import type uPlot from "uplot";
import type { SpectrumChart } from "../../spectrum";
import type { WsClient } from "../../ws";
import type { StrengthBand } from "../../diagnostics";
import { createEmptyMatrix } from "../../diagnostics";
import { defaultLocationCodes } from "../../constants";

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
  preview: Record<string, any> | null;
  previewLoading: boolean;
  previewError: string;
  insights: Record<string, any> | null;
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

export interface VibrationMessage {
  ts: string;
  text: string;
}

export interface CarMapSample {
  ts: number;
  byLocation: Record<string, number>;
}

export interface ClientRow {
  id: string;
  name: string;
  connected: boolean;
  mac_address: string;
  location_code: string;
  locationCode: string;
  last_seen_age_ms: number;
  dropped_frames: number;
  frames_total: number;
}

export interface SpectrumClientData {
  freq: number[];
  combined_spectrum_amp_g: number[];
  strength_metrics: Record<string, any>;
  combined: number[];
}

export interface AppState {
  ws: WsClient | null;
  wsState: string;
  lang: string;
  speedUnit: string;
  clients: ClientRow[];
  selectedClientId: string | null;
  spectrumPlot: SpectrumChart | null;
  spectra: { freq: number[]; clients: Record<string, SpectrumClientData> };
  speedMps: number | null;
  activeViewId: string;
  runs: Record<string, any>[];
  deleteAllRunsInFlight: boolean;
  expandedRunId: string | null;
  runDetailsById: Record<string, RunDetail>;
  loggingStatus: { enabled: boolean; current_file: string | null };
  locationOptions: LocationOption[];
  vehicleSettings: VehicleSettings;
  cars: Record<string, any>[];
  activeCarId: string | null;
  speedSource: string;
  manualSpeedKph: number | null;
  chartBands: ChartBand[];
  vibrationMessages: VibrationMessage[];
  strengthBands: StrengthBand[];
  eventMatrix: Record<string, Record<string, { count: number; seconds: number; contributors: Record<string, number> }>>;
  pendingPayload: Record<string, any> | null;
  renderQueued: boolean;
  lastRenderTsMs: number;
  minRenderIntervalMs: number;
  sensorsSettingsSignature: string;
  locationCodes: string[];
  hasSpectrumData: boolean;
  hasReceivedPayload: boolean;
  payloadError: string | null;
  strengthPlot: uPlot | null;
  strengthFrameTotalsByClient: Record<string, number>;
  strengthHistory: {
    t: number[];
    wheel: number[];
    driveshaft: number[];
    engine: number[];
    other: number[];
  };
  carMapSamples: CarMapSample[];
  carMapPulseLocations: Set<string>;
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
    spectra: { freq: [], clients: {} },
    speedMps: null,
    activeViewId: "dashboardView",
    runs: [],
    deleteAllRunsInFlight: false,
    expandedRunId: null,
    runDetailsById: {},
    loggingStatus: { enabled: false, current_file: null },
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
    chartBands: [],
    vibrationMessages: [],
    strengthBands: [],
    eventMatrix: createEmptyMatrix(),
    pendingPayload: null,
    renderQueued: false,
    lastRenderTsMs: 0,
    minRenderIntervalMs: 100,
    sensorsSettingsSignature: "",
    locationCodes: defaultLocationCodes.slice(),
    hasSpectrumData: false,
    hasReceivedPayload: false,
    payloadError: null,
    strengthPlot: null,
    strengthFrameTotalsByClient: {},
    strengthHistory: { t: [], wheel: [], driveshaft: [], engine: [], other: [] },
    carMapSamples: [],
    carMapPulseLocations: new Set(),
  };
}

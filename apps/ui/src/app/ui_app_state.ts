import type { SpectrumChart } from "../spectrum";
import type { WsClient } from "../ws";
import type { StrengthMetricsPayload } from "../contracts/ws_payload_types";
import type { AdaptedClient, AdaptedPayload, RotationalSpeeds } from "../server_payload";
import { defaultLocationCodes } from "../constants";
import type {
  CarRecord,
  HistoryEntry,
  HistoryInsightsPayload,
  LocationOption,
  LoggingStatusPayload,
  SpeedSourceKind,
  SpeedSourceStatusPayload,
} from "../api/types";

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
  tire_deflection_factor: number;
  [key: string]: number;
}

export const defaultVehicleSettings: Readonly<VehicleSettings> = {
  tire_width_mm: 285.0,
  tire_aspect_pct: 30.0,
  rim_in: 21.0,
  final_drive_ratio: 3.08,
  current_gear_ratio: 0.64,
  wheel_bandwidth_pct: 5.0,
  driveshaft_bandwidth_pct: 4.5,
  engine_bandwidth_pct: 5.2,
  speed_uncertainty_pct: 1.0,
  tire_diameter_uncertainty_pct: 1.0,
  final_drive_uncertainty_pct: 0.1,
  gear_uncertainty_pct: 0.2,
  min_abs_band_hz: 0.2,
  max_band_half_width_pct: 6.0,
  tire_deflection_factor: 0.97,
};

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

export interface LivePayloadUpdateDeps {
  realtime: RealtimeState;
  spectrum: SpectrumState;
  adaptedPayload: AdaptedPayload;
  updateClientSelection: () => void;
}

export interface LivePayloadUpdateResult {
  hasSelectedClientChanged: boolean;
  selectedClient: AdaptedClient | undefined;
  hasNewSpectrumFrame: boolean;
}

function hasRenderableSpectrumData(spectra: { clients: Record<string, SpectrumClientData> }): boolean {
  return Object.values(spectra.clients).some((clientSpec) => clientSpec.freq.length > 0 && clientSpec.combined.length > 0);
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
  return {
    spectra: incomingSpectra,
    hasSpectrumData: hasRenderableSpectrumData(incomingSpectra),
    hasNewSpectrumFrame: true,
  };
}

export function applyLivePayloadUpdate(deps: LivePayloadUpdateDeps): LivePayloadUpdateResult {
  const { realtime, spectrum, adaptedPayload, updateClientSelection } = deps;
  const previousSelectedClientId = realtime.selectedClientId;
  realtime.clients = adaptedPayload.clients;
  const spectrumTick = applySpectrumTick(spectrum.spectra, spectrum.hasSpectrumData, adaptedPayload.spectra);
  spectrum.spectra = spectrumTick.spectra;
  updateClientSelection();
  realtime.speedMps = adaptedPayload.speed_mps;
  realtime.rotationalSpeeds = adaptedPayload.rotational_speeds;
  spectrum.hasSpectrumData = spectrumTick.hasSpectrumData;
  return {
    hasSelectedClientChanged: previousSelectedClientId !== realtime.selectedClientId,
    selectedClient: realtime.clients.find((client) => client.id === realtime.selectedClientId),
    hasNewSpectrumFrame: spectrumTick.hasNewSpectrumFrame,
  };
}

export interface ShellState {
  lang: string;
  speedUnit: string;
  activeViewId: string;
}

export interface TransportState {
  ws: WsClient | null;
  wsState: string;
  pendingPayload: unknown | null;
  renderQueued: boolean;
  lastRenderTsMs: number;
  minRenderIntervalMs: number;
  hasReceivedPayload: boolean;
  payloadError: string | null;
}

export interface RealtimeState {
  clients: AdaptedClient[];
  selectedClientId: string | null;
  speedMps: number | null;
  rotationalSpeeds: RotationalSpeeds | null;
  loggingStatus: LoggingStatusPayload;
  locationOptions: LocationOption[];
  locationCodes: string[];
  sensorsSettingsSignature: string;
}

export interface HistoryState {
  runs: HistoryEntry[];
  deleteAllRunsInFlight: boolean;
  expandedRunId: string | null;
  runDetailsById: Record<string, RunDetail>;
}

export interface SettingsState {
  vehicleSettings: VehicleSettings;
  cars: CarRecord[];
  carsLoaded: boolean;
  activeCarId: string | null;
  speedSource: SpeedSourceKind;
  manualSpeedKph: number | null;
  resolvedSpeedSource: SpeedSourceStatusPayload["speed_source"] | null;
  gpsFallbackActive: boolean;
}

export interface SpectrumState {
  spectrumPlot: SpectrumChart | null;
  spectra: { clients: Record<string, SpectrumClientData> };
  chartBands: ChartBand[];
  hasSpectrumData: boolean;
}

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
      lang: "en",
      speedUnit: "kmh",
      activeViewId: "dashboardView",
    },
    transport: {
      ws: null,
      wsState: "connecting",
      pendingPayload: null,
      renderQueued: false,
      lastRenderTsMs: 0,
      minRenderIntervalMs: 100,
      hasReceivedPayload: false,
      payloadError: null,
    },
    realtime: {
      clients: [],
      selectedClientId: null,
      speedMps: null,
      rotationalSpeeds: null,
      loggingStatus: {
        enabled: false,
        run_id: null,
        write_error: null,
        analysis_in_progress: false,
        start_time_utc: null,
        samples_written: 0,
        samples_dropped: 0,
        last_completed_run_id: null,
        last_completed_run_error: null,
      },
      locationOptions: [],
      locationCodes: defaultLocationCodes.slice(),
      sensorsSettingsSignature: "",
    },
    history: {
      runs: [],
      deleteAllRunsInFlight: false,
      expandedRunId: null,
      runDetailsById: {},
    },
    settings: {
      vehicleSettings: { ...defaultVehicleSettings },
      cars: [],
      carsLoaded: false,
      activeCarId: null,
      speedSource: "gps",
      manualSpeedKph: null,
      resolvedSpeedSource: null,
      gpsFallbackActive: false,
    },
    spectrum: {
      spectrumPlot: null,
      spectra: { clients: {} },
      chartBands: [],
      hasSpectrumData: false,
    },
  };
}

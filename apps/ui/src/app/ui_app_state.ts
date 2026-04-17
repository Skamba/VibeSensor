import type { SpectrumChart } from "../spectrum_chart";
import type { WsClient, WsUiState } from "../ws";
import type {
  AdaptedClient,
  AdaptedPayload,
  RotationalSpeeds,
  SpectrumClientData,
} from "../transport/live_models";
import { defaultLocationCodes } from "../constants";
import type {
  CarRecord,
  HistoryEntry,
  HistoryInsightsPayload,
  LoggingStatusPayload,
  SpeedSourceKind,
  SpeedSourceStatusPayload,
} from "../api/types";
import { batch, signal, type Signal } from "./ui_signals";

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

export interface SpectrumTickUpdate {
  spectra: { clients: Record<string, SpectrumClientData> };
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

export interface SettingsStateValue {
  vehicleSettings: VehicleSettings;
  cars: CarRecord[];
  carsLoaded: boolean;
  activeCarId: string | null;
  speedSource: SpeedSourceKind;
  manualSpeedKph: number | null;
  obdDeviceMac: string | null;
  obdDeviceName: string | null;
  resolvedSpeedSource: SpeedSourceStatusPayload["speed_source"] | null;
  gpsFallbackActive: boolean;
  gpsEffectiveSpeedKph: number | null;
}

export interface SpectrumStateValue {
  spectrumPlot: SpectrumChart | null;
  spectra: { clients: Record<string, SpectrumClientData> };
  chartBands: ChartBand[];
  hasSpectrumData: boolean;
  chartLoading: boolean;
  chartLoadErrorDetail: string | null;
}

export type ShellState = SignalState<ShellStateValue>;
export type TransportState = SignalState<TransportStateValue>;
export type RealtimeState = SignalState<RealtimeStateValue>;
export type HistoryState = SignalState<HistoryStateValue>;
export type SettingsState = SignalState<SettingsStateValue>;
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
      vehicleSettings: signal<VehicleSettings>({ ...defaultVehicleSettings }),
      cars: signal<CarRecord[]>([]),
      carsLoaded: signal(false),
      activeCarId: signal<string | null>(null),
      speedSource: signal<SpeedSourceKind>("gps"),
      manualSpeedKph: signal<number | null>(null),
      obdDeviceMac: signal<string | null>(null),
      obdDeviceName: signal<string | null>(null),
      resolvedSpeedSource: signal<SpeedSourceStatusPayload["speed_source"] | null>(null),
      gpsFallbackActive: signal(false),
      gpsEffectiveSpeedKph: signal<number | null>(null),
    },
    spectrum: {
      spectrumPlot: signal<SpectrumChart | null>(null),
      spectra: signal<{ clients: Record<string, SpectrumClientData> }>({ clients: {} }),
      chartBands: signal<ChartBand[]>([]),
      hasSpectrumData: signal(false),
      chartLoading: signal(false),
      chartLoadErrorDetail: signal<string | null>(null),
    },
  };
}

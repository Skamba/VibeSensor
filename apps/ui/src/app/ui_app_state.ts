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
import { batch, signal, type ReadonlySignal, type Signal } from "./ui_signals";

const reactiveTargetProxies = new WeakMap<object, WeakMap<Signal<number>, object>>();
const reactiveProxyTargets = new WeakMap<object, object>();
const reactiveSliceSignals = new WeakMap<object, Signal<number>>();

type SignalStateScalar = boolean | null | number | string | undefined;

function isProxyableObject(value: unknown): value is object {
  if (value === null || typeof value !== "object") {
    return false;
  }
  if (Array.isArray(value)) {
    return true;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function unwrapReactiveValue<T>(value: T): T {
  if (value === null || typeof value !== "object") {
    return value;
  }
  return (reactiveProxyTargets.get(value) as T | undefined) ?? value;
}

function createReactiveProxy<T extends object>(target: T, rootSignal: Signal<number>): T {
  let proxiesBySignal = reactiveTargetProxies.get(target);
  if (!proxiesBySignal) {
    proxiesBySignal = new WeakMap<Signal<number>, object>();
    reactiveTargetProxies.set(target, proxiesBySignal);
  }
  const existingProxy = proxiesBySignal.get(rootSignal);
  if (existingProxy) {
    return existingProxy as T;
  }

  const proxy = new Proxy(target, {
    get(current, property) {
      const value = Reflect.get(current, property);
      if (isProxyableObject(value)) {
        return createReactiveProxy(unwrapReactiveValue(value), rootSignal);
      }
      return value;
    },
    set(current, property, nextValue) {
      const rawNextValue = unwrapReactiveValue(nextValue);
      const previousValue = unwrapReactiveValue(Reflect.get(current, property));
      if (Object.is(previousValue, rawNextValue)) {
        return true;
      }
      const didSet = Reflect.set(current, property, rawNextValue);
      if (didSet) {
        rootSignal.value += 1;
      }
      return didSet;
    },
    deleteProperty(current, property) {
      if (!Reflect.has(current, property)) {
        return true;
      }
      const didDelete = Reflect.deleteProperty(current, property);
      if (didDelete) {
        rootSignal.value += 1;
      }
      return didDelete;
    },
  });

  proxiesBySignal.set(rootSignal, proxy);
  reactiveProxyTargets.set(proxy, target);
  reactiveSliceSignals.set(proxy, rootSignal);
  return proxy as T;
}

function createReactiveStateSlice<T extends object>(value: T): T {
  return createReactiveProxy(value, signal(0));
}

function createSignalStateSlice<T extends Record<string, SignalStateScalar>>(value: T): T {
  const sliceSignal = signal(0);
  const slice = {} as T;
  for (const [key, initialValue] of Object.entries(value) as [keyof T, T[keyof T]][]) {
    const propertySignal = signal(initialValue);
    Object.defineProperty(slice, key, {
      enumerable: true,
      get() {
        return propertySignal.value;
      },
      set(nextValue: T[keyof T]) {
        if (Object.is(propertySignal.value, nextValue)) {
          return;
        }
        propertySignal.value = nextValue;
        sliceSignal.value += 1;
      },
    });
  }
  reactiveSliceSignals.set(slice as object, sliceSignal);
  return slice;
}

function requireReactiveSliceSignal<T extends object>(slice: T): Signal<number> {
  const sliceSignal = reactiveSliceSignals.get(slice as object);
  if (!sliceSignal) {
    throw new Error("AppState slice signal is unavailable outside createAppState()");
  }
  return sliceSignal;
}

export function getAppStateSliceSignal<T extends object>(slice: T): ReadonlySignal<number> {
  return requireReactiveSliceSignal(slice);
}

export function trackAppStateSlice<T extends object>(slice: T): T {
  requireReactiveSliceSignal(slice).value;
  return slice;
}

export function batchAppStateUpdates<T>(callback: () => T): T {
  let result!: T;
  batch(() => {
    result = callback();
  });
  return result;
}

export function unwrapAppStateValue<T>(value: T): T {
  return unwrapReactiveValue(value);
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
  const firstConnected = realtime.clients.find((client) => Boolean(client.connected));
  if (!realtime.selectedClientId && realtime.clients.length > 0) {
    realtime.selectedClientId = firstConnected ? firstConnected.id : realtime.clients[0]?.id ?? null;
  }
  if (
    realtime.selectedClientId
    && !realtime.clients.some((client) => client.id === realtime.selectedClientId)
  ) {
    realtime.selectedClientId = firstConnected
      ? firstConnected.id
      : realtime.clients.length
        ? realtime.clients[0]?.id ?? null
        : null;
  }
}

export function applyLivePayloadUpdate(deps: LivePayloadUpdateDeps): LivePayloadUpdateResult {
  return batchAppStateUpdates(() => {
    const { realtime, spectrum, adaptedPayload } = deps;
    const previousSelectedClientId = realtime.selectedClientId;
    realtime.clients = adaptedPayload.clients;
    const spectrumTick = applySpectrumTick(
      spectrum.spectra,
      spectrum.hasSpectrumData,
      adaptedPayload.spectra,
    );
    spectrum.spectra = spectrumTick.spectra;
    syncSelectedRealtimeClient(realtime);
    realtime.speedMps = adaptedPayload.speed_mps;
    realtime.rotationalSpeeds = adaptedPayload.rotational_speeds;
    spectrum.hasSpectrumData = spectrumTick.hasSpectrumData;
    return {
      hasSelectedClientChanged: previousSelectedClientId !== realtime.selectedClientId,
      selectedClient: realtime.clients.find((client) => client.id === realtime.selectedClientId),
      hasNewSpectrumFrame: spectrumTick.hasNewSpectrumFrame,
    };
  });
}

export interface ShellState {
  lang: string;
  speedUnit: string;
  activeViewId: string;
}

export interface TransportState {
  ws: WsClient | null;
  wsState: WsUiState;
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
  locationCodes: string[];
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
  obdDeviceMac: string | null;
  obdDeviceName: string | null;
  resolvedSpeedSource: SpeedSourceStatusPayload["speed_source"] | null;
  gpsFallbackActive: boolean;
  gpsEffectiveSpeedKph: number | null;
}

export interface SpectrumState {
  spectrumPlot: SpectrumChart | null;
  spectra: { clients: Record<string, SpectrumClientData> };
  chartBands: ChartBand[];
  hasSpectrumData: boolean;
  chartLoading: boolean;
  chartLoadErrorDetail: string | null;
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
    shell: createSignalStateSlice({
      lang: "en",
      speedUnit: "kmh",
      activeViewId: "dashboardView",
    }),
    transport: createReactiveStateSlice({
      ws: null,
      wsState: "connecting",
      pendingPayload: null,
      renderQueued: false,
      lastRenderTsMs: 0,
      minRenderIntervalMs: 100,
      hasReceivedPayload: false,
      payloadError: null,
    }),
    realtime: createReactiveStateSlice({
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
        capture_readiness: null,
      },
      locationCodes: defaultLocationCodes.slice(),
    }),
    history: createReactiveStateSlice({
      runs: [],
      deleteAllRunsInFlight: false,
      expandedRunId: null,
      runDetailsById: {},
    }),
    settings: createReactiveStateSlice({
      vehicleSettings: { ...defaultVehicleSettings },
      cars: [],
      carsLoaded: false,
      activeCarId: null,
      speedSource: "gps",
      manualSpeedKph: null,
      obdDeviceMac: null,
      obdDeviceName: null,
      resolvedSpeedSource: null,
      gpsFallbackActive: false,
      gpsEffectiveSpeedKph: null,
    }),
    spectrum: createReactiveStateSlice({
      spectrumPlot: null,
      spectra: { clients: {} },
      chartBands: [],
      hasSpectrumData: false,
      chartLoading: false,
      chartLoadErrorDetail: null,
    }),
  };
}

import type {
  AnalysisSettingsPayload,
  CarLibraryBrandsPayload,
  CarLibraryModel,
  CarLibraryModelsPayload,
  CarLibraryTypesPayload,
  CarRecord,
  CarsPayload,
  ObdDevicePayload,
  ObdPairPayload,
  ObdScanPayload,
  SpeedSourcePayload,
  SpeedSourceStatusPayload,
} from "../../../src/api/types";
import type { JsonBodyType } from "msw";

import { HttpResponse, http, uiRoutePath } from "../http";

type ErrorResponse = {
  detail: string;
  status?: number;
};

type StaticOrFactory<T extends JsonBodyType> = T | ((request: Request) => T | Promise<T>);
type HandlerResult<T extends JsonBodyType> = StaticOrFactory<T> | ErrorResponse;

function isErrorResponse(value: unknown): value is ErrorResponse {
  return !!value && typeof value === "object" && "detail" in value;
}

async function resolveHandlerResult<T extends JsonBodyType>(
  request: Request,
  result: HandlerResult<T>,
): Promise<Response> {
  const resolved = typeof result === "function" ? await result(request) : result;
  if (isErrorResponse(resolved)) {
    return HttpResponse.json(
      { detail: resolved.detail },
      { status: resolved.status ?? 400 },
    );
  }
  return HttpResponse.json(resolved);
}

export function makeAnalysisSettingsPayload(
  overrides: Partial<AnalysisSettingsPayload> = {},
): AnalysisSettingsPayload {
  const payload = {
    tire_width_mm: 225,
    tire_aspect_pct: 45,
    rim_in: 18,
    default_axle_for_speed: "rear" as const,
    final_drive_ratio: 3.08,
    current_gear_ratio: 0.64,
    driveshaft_bandwidth_pct: 10,
    engine_bandwidth_pct: 10,
    final_drive_uncertainty_pct: 1,
    gear_uncertainty_pct: 1,
    max_band_half_width_pct: 20,
    tire_deflection_factor: 0.95,
    tire_diameter_uncertainty_pct: 1,
    wheel_bandwidth_pct: 5,
    speed_uncertainty_pct: 1,
    min_abs_band_hz: 0.2,
    ...overrides,
  };
  return {
    ...payload,
    default_axle_for_speed: payload.default_axle_for_speed ?? "rear",
    front_tire_width_mm: payload.front_tire_width_mm ?? undefined,
    front_tire_aspect_pct: payload.front_tire_aspect_pct ?? undefined,
    front_rim_in: payload.front_rim_in ?? undefined,
    rear_tire_width_mm: payload.rear_tire_width_mm ?? undefined,
    rear_tire_aspect_pct: payload.rear_tire_aspect_pct ?? undefined,
    rear_rim_in: payload.rear_rim_in ?? undefined,
  };
}

function makeCarRecord(overrides: Partial<CarRecord> = {}): CarRecord {
  return {
    id: "car-1",
    name: "Track Demo",
    type: "Coupe",
    variant: null,
    aspects: makeCarAspects(),
    ...overrides,
  };
}

function makeCarAspects(
  overrides: Partial<CarRecord["aspects"]> = {},
): CarRecord["aspects"] {
  const payload = {
    tire_width_mm: 225,
    tire_aspect_pct: 45,
    rim_in: 18,
    default_axle_for_speed: "rear" as const,
    final_drive_ratio: 3.08,
    current_gear_ratio: 0.64,
    driveshaft_bandwidth_pct: 10,
    engine_bandwidth_pct: 10,
    final_drive_uncertainty_pct: 1,
    gear_uncertainty_pct: 1,
    max_band_half_width_pct: 20,
    tire_deflection_factor: 0.95,
    tire_diameter_uncertainty_pct: 1,
    wheel_bandwidth_pct: 5,
    speed_uncertainty_pct: 1,
    min_abs_band_hz: 0.2,
    ...overrides,
  };
  return {
    ...payload,
    current_gear_ratio: payload.current_gear_ratio ?? undefined,
    default_axle_for_speed: payload.default_axle_for_speed ?? undefined,
    driveshaft_bandwidth_pct: payload.driveshaft_bandwidth_pct ?? undefined,
    engine_bandwidth_pct: payload.engine_bandwidth_pct ?? undefined,
    final_drive_ratio: payload.final_drive_ratio ?? undefined,
    final_drive_uncertainty_pct: payload.final_drive_uncertainty_pct ?? undefined,
    front_tire_width_mm: payload.front_tire_width_mm ?? undefined,
    front_tire_aspect_pct: payload.front_tire_aspect_pct ?? undefined,
    front_rim_in: payload.front_rim_in ?? undefined,
    gear_uncertainty_pct: payload.gear_uncertainty_pct ?? undefined,
    max_band_half_width_pct: payload.max_band_half_width_pct ?? undefined,
    min_abs_band_hz: payload.min_abs_band_hz ?? undefined,
    rear_tire_width_mm: payload.rear_tire_width_mm ?? undefined,
    rear_tire_aspect_pct: payload.rear_tire_aspect_pct ?? undefined,
    rear_rim_in: payload.rear_rim_in ?? undefined,
    rim_in: payload.rim_in ?? undefined,
    speed_uncertainty_pct: payload.speed_uncertainty_pct ?? undefined,
    tire_aspect_pct: payload.tire_aspect_pct ?? undefined,
    tire_deflection_factor: payload.tire_deflection_factor ?? undefined,
    tire_diameter_uncertainty_pct: payload.tire_diameter_uncertainty_pct ?? undefined,
    tire_width_mm: payload.tire_width_mm ?? undefined,
    wheel_bandwidth_pct: payload.wheel_bandwidth_pct ?? undefined,
  };
}

export function makeCarsPayload(
  overrides: Partial<CarsPayload> = {},
): CarsPayload {
  return {
    active_car_id: "car-1",
    cars: [makeCarRecord()],
    ...overrides,
  };
}

function makeSpeedSourcePayload(
  overrides: Partial<SpeedSourcePayload> = {},
): SpeedSourcePayload {
  return {
    manual_speed_kph: null,
    obd_device_mac: null,
    obd_device_name: null,
    speed_source: "gps",
    stale_timeout_s: 5,
    ...overrides,
  };
}

function makeSpeedSourceStatusPayload(
  overrides: Partial<SpeedSourceStatusPayload> = {},
): SpeedSourceStatusPayload {
  return {
    connection_state: "connected",
    device: "gpsd",
    effective_speed_kmh: 36,
    epv_m: null,
    epx_m: null,
    epy_m: null,
    fallback_active: false,
    fix_dimension: "3d",
    fix_mode: 3,
    gps_enabled: true,
    last_error: null,
    last_update_age_s: 0.25,
    raw_speed_kmh: 36,
    reconnect_delay_s: null,
    speed_confidence: "high",
    speed_source: "gps",
    stale_timeout_s: 5,
    ...overrides,
  };
}

function makeObdDevicePayload(
  overrides: Partial<ObdDevicePayload> = {},
): ObdDevicePayload {
  return {
    connected: false,
    mac_address: "00:22:d9:00:1b:b1",
    name: "OBDLink CX",
    paired: false,
    rfcomm_channel: null,
    trusted: false,
    ...overrides,
  };
}

function makeObdScanPayload(
  overrides: Partial<ObdScanPayload> = {},
): ObdScanPayload {
  return {
    devices: [makeObdDevicePayload()],
    ...overrides,
  };
}

function makeObdPairPayload(
  overrides: Partial<ObdPairPayload> = {},
): ObdPairPayload {
  return {
    configured_device_mac: "00:22:d9:00:1b:b1",
    configured_device_name: "OBDLink CX",
    connected: true,
    paired: true,
    rfcomm_channel: 1,
    trusted: true,
    ...overrides,
  };
}

function makeCarLibraryBrandsPayload(
  overrides: Partial<CarLibraryBrandsPayload> = {},
): CarLibraryBrandsPayload {
  return {
    brands: ["BMW", "Volvo"],
    ...overrides,
  };
}

function makeCarLibraryTypesPayload(
  overrides: Partial<CarLibraryTypesPayload> = {},
): CarLibraryTypesPayload {
  return {
    types: ["SUV"],
    ...overrides,
  };
}

function makeCarLibraryModel(
  overrides: Partial<CarLibraryModel> = {},
): CarLibraryModel {
  return {
    brand: "BMW",
    gearboxes: [],
    model: "X5",
    rim_in: 21,
    tire_aspect_pct: 40,
    tire_options: [],
    tire_width_mm: 275,
    type: "SUV",
    variants: [],
    ...overrides,
  };
}

function makeCarLibraryModelsPayload(
  overrides: Partial<CarLibraryModelsPayload> = {},
): CarLibraryModelsPayload {
  return {
    models: [makeCarLibraryModel()],
    ...overrides,
  };
}

export function buildAnalysisSettingsHandlers(options: {
  load?: HandlerResult<AnalysisSettingsPayload>;
  save?: HandlerResult<AnalysisSettingsPayload>;
} = {}) {
  const load = options.load ?? makeAnalysisSettingsPayload();
  const save = options.save ?? load;
  return [
    http.get(uiRoutePath("/api/settings/analysis"), async ({ request }) =>
      await resolveHandlerResult(request, load)),
    http.put(uiRoutePath("/api/settings/analysis"), async ({ request }) =>
      await resolveHandlerResult(request, save)),
  ];
}

export function buildCarsHandlers(options: {
  load?: HandlerResult<CarsPayload>;
  create?: HandlerResult<CarsPayload>;
  update?: HandlerResult<CarsPayload>;
  activate?: HandlerResult<CarsPayload>;
  remove?: HandlerResult<CarsPayload>;
} = {}) {
  const load = options.load ?? makeCarsPayload();
  const create = options.create ?? load;
  const update = options.update ?? create;
  const activate = options.activate ?? update;
  const remove = options.remove ?? activate;
  return [
    http.get(uiRoutePath("/api/settings/cars"), async ({ request }) =>
      await resolveHandlerResult(request, load)),
    http.post(uiRoutePath("/api/settings/cars"), async ({ request }) =>
      await resolveHandlerResult(request, create)),
    http.put(uiRoutePath("/api/settings/cars/active"), async ({ request }) =>
      await resolveHandlerResult(request, activate)),
    http.put(uiRoutePath("/api/settings/cars/:carId"), async ({ request }) =>
      await resolveHandlerResult(request, update)),
    http.delete(uiRoutePath("/api/settings/cars/:carId"), async ({ request }) =>
      await resolveHandlerResult(request, remove)),
  ];
}

export function buildSpeedSourceHandlers(options: {
  load?: HandlerResult<SpeedSourcePayload>;
  save?: HandlerResult<SpeedSourcePayload>;
  status?: HandlerResult<SpeedSourceStatusPayload>;
  scan?: HandlerResult<ObdScanPayload>;
  pair?: HandlerResult<ObdPairPayload>;
} = {}) {
  const load = options.load ?? makeSpeedSourcePayload();
  const save = options.save ?? load;
  const status = options.status ?? makeSpeedSourceStatusPayload();
  const scan = options.scan ?? makeObdScanPayload();
  const pair = options.pair ?? makeObdPairPayload();
  return [
    http.get(uiRoutePath("/api/settings/speed-source"), async ({ request }) =>
      await resolveHandlerResult(request, load)),
    http.put(uiRoutePath("/api/settings/speed-source"), async ({ request }) =>
      await resolveHandlerResult(request, save)),
    http.get(uiRoutePath("/api/settings/speed-source/status"), async ({ request }) =>
      await resolveHandlerResult(request, status)),
    http.post(uiRoutePath("/api/settings/obd/scan"), async ({ request }) =>
      await resolveHandlerResult(request, scan)),
    http.post(uiRoutePath("/api/settings/obd/pair"), async ({ request }) =>
      await resolveHandlerResult(request, pair)),
  ];
}

export function buildCarLibraryHandlers(options: {
  brands?: HandlerResult<CarLibraryBrandsPayload>;
  types?: HandlerResult<CarLibraryTypesPayload>;
  models?: HandlerResult<CarLibraryModelsPayload>;
} = {}) {
  const brands = options.brands ?? makeCarLibraryBrandsPayload();
  const types = options.types ?? makeCarLibraryTypesPayload();
  const models = options.models ?? makeCarLibraryModelsPayload();
  return [
    http.get(uiRoutePath("/api/car-library/brands"), async ({ request }) =>
      await resolveHandlerResult(request, brands)),
    http.get(uiRoutePath("/api/car-library/types"), async ({ request }) =>
      await resolveHandlerResult(request, types)),
    http.get(uiRoutePath("/api/car-library/models"), async ({ request }) =>
      await resolveHandlerResult(request, models)),
  ];
}

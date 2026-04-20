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
import { HttpResponse, http, uiTestUrl } from "../http";

type ErrorResponse = {
  detail: string;
  status?: number;
};

type StaticOrFactory<T> = T | ((request: Request) => T | Promise<T>);
type HandlerResult<T> = StaticOrFactory<T> | ErrorResponse;

function isErrorResponse(value: unknown): value is ErrorResponse {
  return !!value && typeof value === "object" && "detail" in value;
}

async function resolveHandlerResult<T>(
  request: Request,
  result: HandlerResult<T>,
): Promise<HttpResponse> {
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
  return {
    tire_width_mm: 225,
    tire_aspect_pct: 45,
    rim_in: 18,
    final_drive_ratio: 3.08,
    current_gear_ratio: 0.64,
    tire_deflection_factor: 0.95,
    wheel_bandwidth_pct: 5,
    speed_uncertainty_pct: 1,
    min_abs_band_hz: 0.2,
    ...overrides,
  };
}

export function makeCarRecord(overrides: Partial<CarRecord> = {}): CarRecord {
  return {
    id: "car-1",
    name: "Track Demo",
    type: "Coupe",
    variant: null,
    aspects: makeAnalysisSettingsPayload(),
    ...overrides,
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

export function makeSpeedSourcePayload(
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

export function makeSpeedSourceStatusPayload(
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
    speed_confidence: null,
    speed_source: "gps",
    ...overrides,
  };
}

export function makeObdDevicePayload(
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

export function makeObdScanPayload(
  overrides: Partial<ObdScanPayload> = {},
): ObdScanPayload {
  return {
    devices: [makeObdDevicePayload()],
    ...overrides,
  };
}

export function makeObdPairPayload(
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

export function makeCarLibraryBrandsPayload(
  overrides: Partial<CarLibraryBrandsPayload> = {},
): CarLibraryBrandsPayload {
  return {
    brands: ["BMW", "Volvo"],
    ...overrides,
  };
}

export function makeCarLibraryTypesPayload(
  overrides: Partial<CarLibraryTypesPayload> = {},
): CarLibraryTypesPayload {
  return {
    types: ["SUV"],
    ...overrides,
  };
}

export function makeCarLibraryModel(
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

export function makeCarLibraryModelsPayload(
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
    http.get(uiTestUrl("/api/settings/analysis"), async ({ request }) =>
      await resolveHandlerResult(request, load)),
    http.put(uiTestUrl("/api/settings/analysis"), async ({ request }) =>
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
    http.get(uiTestUrl("/api/settings/cars"), async ({ request }) =>
      await resolveHandlerResult(request, load)),
    http.post(uiTestUrl("/api/settings/cars"), async ({ request }) =>
      await resolveHandlerResult(request, create)),
    http.put(uiTestUrl("/api/settings/cars/active"), async ({ request }) =>
      await resolveHandlerResult(request, activate)),
    http.put(uiTestUrl("/api/settings/cars/:carId"), async ({ request }) =>
      await resolveHandlerResult(request, update)),
    http.delete(uiTestUrl("/api/settings/cars/:carId"), async ({ request }) =>
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
    http.get(uiTestUrl("/api/settings/speed-source"), async ({ request }) =>
      await resolveHandlerResult(request, load)),
    http.put(uiTestUrl("/api/settings/speed-source"), async ({ request }) =>
      await resolveHandlerResult(request, save)),
    http.get(uiTestUrl("/api/settings/speed-source/status"), async ({ request }) =>
      await resolveHandlerResult(request, status)),
    http.post(uiTestUrl("/api/settings/obd/scan"), async ({ request }) =>
      await resolveHandlerResult(request, scan)),
    http.post(uiTestUrl("/api/settings/obd/pair"), async ({ request }) =>
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
    http.get(uiTestUrl("/api/car-library/brands"), async ({ request }) =>
      await resolveHandlerResult(request, brands)),
    http.get(uiTestUrl("/api/car-library/types"), async ({ request }) =>
      await resolveHandlerResult(request, types)),
    http.get(uiTestUrl("/api/car-library/models"), async ({ request }) =>
      await resolveHandlerResult(request, models)),
  ];
}

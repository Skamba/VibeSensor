import type { CarRecord, CarsPayload } from "../../../src/api/types";
import type { JsonBodyType } from "msw";

import { HttpResponse, http, uiRoutePath } from "../http";

type ErrorResponse = {
  detail: string;
  status?: number;
};

type StaticOrFactory<T extends JsonBodyType> =
  | T
  | ((request: Request) => T | Promise<T>);
type HandlerResult<T extends JsonBodyType> = StaticOrFactory<T> | ErrorResponse;

function isErrorResponse(value: unknown): value is ErrorResponse {
  return !!value && typeof value === "object" && "detail" in value;
}

async function resolveHandlerResult<T extends JsonBodyType>(
  request: Request,
  result: HandlerResult<T>,
): Promise<Response> {
  const resolved =
    typeof result === "function" ? await result(request) : result;
  if (isErrorResponse(resolved)) {
    return HttpResponse.json(
      { detail: resolved.detail },
      { status: resolved.status ?? 400 },
    );
  }
  return HttpResponse.json(resolved);
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
    final_drive_uncertainty_pct: 1,
    gear_uncertainty_pct: 1,
    tire_deflection_factor: 0.95,
    tire_diameter_uncertainty_pct: 1,
    speed_uncertainty_pct: 1,
    ...overrides,
  };
  return {
    ...payload,
    current_gear_ratio: payload.current_gear_ratio ?? undefined,
    default_axle_for_speed: payload.default_axle_for_speed ?? undefined,
    final_drive_ratio: payload.final_drive_ratio ?? undefined,
    final_drive_uncertainty_pct:
      payload.final_drive_uncertainty_pct ?? undefined,
    front_tire_width_mm: payload.front_tire_width_mm ?? undefined,
    front_tire_aspect_pct: payload.front_tire_aspect_pct ?? undefined,
    front_rim_in: payload.front_rim_in ?? undefined,
    gear_uncertainty_pct: payload.gear_uncertainty_pct ?? undefined,
    rear_tire_width_mm: payload.rear_tire_width_mm ?? undefined,
    rear_tire_aspect_pct: payload.rear_tire_aspect_pct ?? undefined,
    rear_rim_in: payload.rear_rim_in ?? undefined,
    rim_in: payload.rim_in ?? undefined,
    speed_uncertainty_pct: payload.speed_uncertainty_pct ?? undefined,
    tire_aspect_pct: payload.tire_aspect_pct ?? undefined,
    tire_deflection_factor: payload.tire_deflection_factor ?? undefined,
    tire_diameter_uncertainty_pct:
      payload.tire_diameter_uncertainty_pct ?? undefined,
    tire_width_mm: payload.tire_width_mm ?? undefined,
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

export function buildCarsHandlers(
  options: {
    load?: HandlerResult<CarsPayload>;
    create?: HandlerResult<CarsPayload>;
    update?: HandlerResult<CarsPayload>;
    activate?: HandlerResult<CarsPayload>;
    remove?: HandlerResult<CarsPayload>;
  } = {},
) {
  const load = options.load ?? makeCarsPayload();
  const create = options.create ?? load;
  const update = options.update ?? create;
  const activate = options.activate ?? update;
  const remove = options.remove ?? activate;
  return [
    http.get(
      uiRoutePath("/api/settings/cars"),
      async ({ request }) => await resolveHandlerResult(request, load),
    ),
    http.post(
      uiRoutePath("/api/settings/cars"),
      async ({ request }) => await resolveHandlerResult(request, create),
    ),
    http.put(
      uiRoutePath("/api/settings/cars/active"),
      async ({ request }) => await resolveHandlerResult(request, activate),
    ),
    http.put(
      uiRoutePath("/api/settings/cars/:carId"),
      async ({ request }) => await resolveHandlerResult(request, update),
    ),
    http.delete(
      uiRoutePath("/api/settings/cars/:carId"),
      async ({ request }) => await resolveHandlerResult(request, remove),
    ),
  ];
}

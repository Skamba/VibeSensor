import type {
  HealthStatusPayload,
  UpdateCancelPayload,
  UpdateStartPayload,
  UpdateStartRequestPayload,
  UpdateStatusPayload,
  UsbInternetStatusPayload,
} from "../../../src/api/types";
import type { JsonBodyType } from "msw";
import {
  createHealthyUpdateStatus,
  createIdleUpdateStatus,
  createUsbInternetStatus,
} from "../../maintenance_payload_test_support";
import { HttpResponse, http, uiTestUrl } from "../http";

type ErrorResponse = {
  detail: string;
  status?: number;
};

type ScenarioValue<T> = T | ErrorResponse;
type ScenarioResolver<T> = (
  request: Request,
) => ScenarioValue<T> | Promise<ScenarioValue<T>>;
type ScenarioInput<T> =
  | ScenarioValue<T>
  | readonly ScenarioValue<T>[]
  | ScenarioResolver<T>;

function isErrorResponse(value: unknown): value is ErrorResponse {
  return !!value && typeof value === "object" && "detail" in value;
}

function createScenarioResolver<T>(input: ScenarioInput<T>) {
  let index = 0;
  return async (request: Request): Promise<ScenarioValue<T>> => {
    if (typeof input === "function") {
      return await (input as ScenarioResolver<T>)(request);
    }
    if (Array.isArray(input)) {
      if (input.length === 0) {
        throw new Error("Scenario input arrays must not be empty");
      }
      const value = input[Math.min(index, input.length - 1)];
      if (index < input.length - 1) {
        index += 1;
      }
      return value ?? input[input.length - 1];
    }
    return input as ScenarioValue<T>;
  };
}

async function resolveJsonScenario<T>(
  request: Request,
  resolve: (request: Request) => Promise<ScenarioValue<T>>,
): Promise<HttpResponse<JsonBodyType>> {
  const resolved = await resolve(request);
  if (isErrorResponse(resolved)) {
    return HttpResponse.json(
      { detail: resolved.detail },
      { status: resolved.status ?? 400 },
    );
  }
  return HttpResponse.json(resolved as JsonBodyType);
}

export function makeUpdateStartPayload(
  overrides: Partial<UpdateStartPayload> = {},
): UpdateStartPayload {
  return {
    status: "started",
    transport: "wifi",
    ssid: "MyWiFi",
    ...overrides,
  };
}

function makeUpdateCancelPayload(
  overrides: Partial<UpdateCancelPayload> = {},
): UpdateCancelPayload {
  return {
    cancelled: true,
    ...overrides,
  };
}

export function buildUpdateHandlers(
  options: {
    status?: ScenarioInput<UpdateStatusPayload>;
    health?: ScenarioInput<HealthStatusPayload>;
    internet?: ScenarioInput<UsbInternetStatusPayload>;
    start?: ScenarioInput<UpdateStartPayload>;
    cancel?: ScenarioInput<UpdateCancelPayload>;
    startRequests?: UpdateStartRequestPayload[];
    onStartRequest?: (payload: UpdateStartRequestPayload) => void;
  } = {},
) {
  const resolveStatus = createScenarioResolver(
    options.status ?? createIdleUpdateStatus(),
  );
  const resolveHealth = createScenarioResolver(
    options.health ?? createHealthyUpdateStatus(),
  );
  const resolveInternet = createScenarioResolver(
    options.internet ?? createUsbInternetStatus(),
  );
  const resolveStart = createScenarioResolver(
    options.start ?? makeUpdateStartPayload(),
  );
  const resolveCancel = createScenarioResolver(
    options.cancel ?? makeUpdateCancelPayload(),
  );
  return [
    http.get(
      uiTestUrl("/api/update/status"),
      async ({ request }) => await resolveJsonScenario(request, resolveStatus),
    ),
    http.get(
      uiTestUrl("/api/health"),
      async ({ request }) => await resolveJsonScenario(request, resolveHealth),
    ),
    http.get(
      uiTestUrl("/api/update/internet-status"),
      async ({ request }) =>
        await resolveJsonScenario(request, resolveInternet),
    ),
    http.post(uiTestUrl("/api/update/start"), async ({ request }) => {
      const payload = (await request.json()) as UpdateStartRequestPayload;
      options.startRequests?.push(payload);
      options.onStartRequest?.(payload);
      return await resolveJsonScenario(request, resolveStart);
    }),
    http.post(
      uiTestUrl("/api/update/cancel"),
      async ({ request }) => await resolveJsonScenario(request, resolveCancel),
    ),
  ];
}

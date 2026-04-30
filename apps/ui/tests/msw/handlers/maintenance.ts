import type {
  EspFlashCancelPayload,
  EspFlashHistoryPayload,
  EspFlashLogsPayload,
  EspFlashPortsPayload,
  EspFlashStartPayload,
  EspFlashStatusPayload,
  HealthStatusPayload,
  UpdateCancelPayload,
  UpdateStartPayload,
  UpdateStartRequestPayload,
  UpdateStatusPayload,
  UsbInternetStatusPayload,
} from "../../../src/api/types";
import {
  createEspFlashPort,
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
type ScenarioInput<T> =
  | ScenarioValue<T>
  | readonly ScenarioValue<T>[]
  | ((request: Request) => ScenarioValue<T> | Promise<ScenarioValue<T>>);

export type EspFlashStartRequestPayload = {
  auto_detect: boolean;
  port: string | null;
};

function isErrorResponse(value: unknown): value is ErrorResponse {
  return !!value && typeof value === "object" && "detail" in value;
}

function createScenarioResolver<T>(input: ScenarioInput<T>) {
  let index = 0;
  return async (request: Request): Promise<ScenarioValue<T>> => {
    if (typeof input === "function") {
      return await input(request);
    }
    if (Array.isArray(input)) {
      const value = input[Math.min(index, input.length - 1)];
      if (index < input.length - 1) {
        index += 1;
      }
      return value;
    }
    return input;
  };
}

async function resolveJsonScenario<T>(
  request: Request,
  resolve: (request: Request) => Promise<ScenarioValue<T>>,
): Promise<HttpResponse> {
  const resolved = await resolve(request);
  if (isErrorResponse(resolved)) {
    return HttpResponse.json(
      { detail: resolved.detail },
      { status: resolved.status ?? 400 },
    );
  }
  return HttpResponse.json(resolved);
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

export function makeEspFlashPortsPayload(
  overrides: Partial<EspFlashPortsPayload> = {},
): EspFlashPortsPayload {
  return {
    ports: [createEspFlashPort()],
    ...overrides,
  };
}

export function makeEspFlashStatusPayload(
  overrides: Partial<EspFlashStatusPayload> = {},
): EspFlashStatusPayload {
  return {
    state: "idle",
    phase: "idle",
    selected_port: null,
    auto_detect: true,
    last_success_at: null,
    error: null,
    log_count: 0,
    job_id: null,
    started_at: null,
    finished_at: null,
    exit_code: null,
    ...overrides,
  };
}

export function makeEspFlashLogsPayload(
  overrides: Partial<EspFlashLogsPayload> = {},
): EspFlashLogsPayload {
  return {
    from_index: 0,
    next_index: 0,
    lines: [],
    ...overrides,
  };
}

export function makeEspFlashHistoryPayload(
  overrides: Partial<EspFlashHistoryPayload> = {},
): EspFlashHistoryPayload {
  return {
    attempts: [],
    ...overrides,
  };
}

function makeEspFlashStartPayload(
  overrides: Partial<EspFlashStartPayload> = {},
): EspFlashStartPayload {
  return {
    status: "started",
    job_id: 1,
    ...overrides,
  };
}

function makeEspFlashCancelPayload(
  overrides: Partial<EspFlashCancelPayload> = {},
): EspFlashCancelPayload {
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

export function buildEspFlashHandlers(
  options: {
    ports?: ScenarioInput<EspFlashPortsPayload>;
    status?: ScenarioInput<EspFlashStatusPayload>;
    logs?: ScenarioInput<EspFlashLogsPayload>;
    history?: ScenarioInput<EspFlashHistoryPayload>;
    start?: ScenarioInput<EspFlashStartPayload>;
    cancel?: ScenarioInput<EspFlashCancelPayload>;
    startRequests?: EspFlashStartRequestPayload[];
    onStartRequest?: (payload: EspFlashStartRequestPayload) => void;
  } = {},
) {
  const resolvePorts = createScenarioResolver(
    options.ports ?? makeEspFlashPortsPayload(),
  );
  const resolveStatus = createScenarioResolver(
    options.status ?? makeEspFlashStatusPayload(),
  );
  const resolveLogs = createScenarioResolver(
    options.logs ?? makeEspFlashLogsPayload(),
  );
  const resolveHistory = createScenarioResolver(
    options.history ?? makeEspFlashHistoryPayload(),
  );
  const resolveStart = createScenarioResolver(
    options.start ?? makeEspFlashStartPayload(),
  );
  const resolveCancel = createScenarioResolver(
    options.cancel ?? makeEspFlashCancelPayload(),
  );
  return [
    http.get(
      uiTestUrl("/api/esp-flash/ports"),
      async ({ request }) => await resolveJsonScenario(request, resolvePorts),
    ),
    http.get(
      uiTestUrl("/api/esp-flash/status"),
      async ({ request }) => await resolveJsonScenario(request, resolveStatus),
    ),
    http.get(
      uiTestUrl("/api/esp-flash/logs"),
      async ({ request }) => await resolveJsonScenario(request, resolveLogs),
    ),
    http.get(
      uiTestUrl("/api/esp-flash/history"),
      async ({ request }) => await resolveJsonScenario(request, resolveHistory),
    ),
    http.post(uiTestUrl("/api/esp-flash/start"), async ({ request }) => {
      const payload = (await request.json()) as EspFlashStartRequestPayload;
      options.startRequests?.push(payload);
      options.onStartRequest?.(payload);
      return await resolveJsonScenario(request, resolveStart);
    }),
    http.post(
      uiTestUrl("/api/esp-flash/cancel"),
      async ({ request }) => await resolveJsonScenario(request, resolveCancel),
    ),
  ];
}

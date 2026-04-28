import type {
  DeleteHistoryRunPayload,
  HistoryEntry,
  HistoryListPayload,
  HistoryRunPayload,
} from "../../../src/api/types";
import type { JsonBodyType } from "msw";

import { HttpResponse, http, uiRoutePath } from "../http";

type ErrorResponse = {
  detail: string;
  status?: number;
};

type JsonResponseInit<T> = {
  headers?: HeadersInit;
  json: T;
  status?: number;
  statusText?: string;
};
type JsonResult<T extends JsonBodyType> = T | ErrorResponse | JsonResponseInit<T> | Response;
type JsonHandlerFactory<T extends JsonBodyType> =
  (request: Request) => JsonResult<T> | Promise<JsonResult<T>>;
type JsonHandlerResult<T extends JsonBodyType> = JsonResult<T> | JsonHandlerFactory<T>;
type BinaryResponseInit = {
  body?: BodyInit | null;
  contentType?: string;
  filename?: string | null;
  headers?: HeadersInit;
  status?: number;
  statusText?: string;
};
type BinaryHandlerResult =
  | BinaryResponseInit
  | ErrorResponse
  | ((request: Request) => BinaryResponseInit | ErrorResponse | Promise<BinaryResponseInit | ErrorResponse>);

type HistoryInsightsLike = ErrorResponse | {
  run_id: string;
  status: "analyzing" | "complete";
  [key: string]: unknown;
};

const objectHasOwnProperty = Object.prototype.hasOwnProperty;

function isErrorResponse(value: unknown): value is ErrorResponse {
  return !!value && typeof value === "object" && "detail" in value;
}

function isJsonResponseInit<T extends JsonBodyType>(value: unknown): value is JsonResponseInit<T> {
  return !!value
    && typeof value === "object"
    && !(value instanceof Response)
    && objectHasOwnProperty.call(value, "json");
}

async function resolveJsonResult<T extends JsonBodyType>(
  request: Request,
  result: JsonHandlerResult<T>,
): Promise<Response> {
  const resolved = typeof result === "function" ? await result(request) : result;
  if (isErrorResponse(resolved)) {
    return HttpResponse.json(
      { detail: resolved.detail },
      { status: resolved.status ?? 400 },
    );
  }
  if (isJsonResponseInit<T>(resolved)) {
    return HttpResponse.json(resolved.json, {
      status: resolved.status,
      statusText: resolved.statusText,
      headers: resolved.headers,
    });
  }
  if (resolved instanceof Response) {
    return resolved;
  }
  return HttpResponse.json(resolved);
}

async function resolveBinaryResult(
  request: Request,
  result: BinaryHandlerResult,
): Promise<Response> {
  const resolved = typeof result === "function" ? await result(request) : result;
  if (isErrorResponse(resolved)) {
    return HttpResponse.json(
      { detail: resolved.detail },
      { status: resolved.status ?? 400 },
    );
  }
  const headers = new Headers(resolved.headers);
  headers.set("content-type", resolved.contentType ?? "application/octet-stream");
  if (resolved.filename) {
    headers.set(
      "content-disposition",
      `attachment; filename*=UTF-8''${encodeURIComponent(resolved.filename)}`,
    );
  }
  return new HttpResponse(resolved.body ?? "", {
    status: resolved.status ?? 200,
    statusText: resolved.statusText,
    headers,
  });
}

export function makeHistoryListRun(
  runId: string,
  overrides: Partial<HistoryEntry> = {},
): HistoryEntry {
  return {
    run_id: runId,
    status: "complete",
    start_time_utc: "2026-01-01T00:00:00Z",
    end_time_utc: "2026-01-01T00:00:12Z",
    created_at: "2026-01-01T00:00:00Z",
    sample_count: 42,
    car_name: "Track Car",
    error_message: null,
    ...overrides,
  };
}

export function makeHistoryListPayload(
  overrides: Partial<HistoryListPayload> = {},
): HistoryListPayload {
  return {
    runs: [makeHistoryListRun("run-001")],
    ...overrides,
  };
}

export function makeDeleteHistoryRunPayload(
  overrides: Partial<DeleteHistoryRunPayload> = {},
): DeleteHistoryRunPayload {
  return {
    run_id: "run-001",
    status: "deleted",
    ...overrides,
  };
}

function makeHistoryRunPayload(
  overrides: Partial<HistoryRunPayload> = {},
): HistoryRunPayload {
  return {
    analysis: null,
    error_message: null,
    metadata: undefined,
    run_id: "run-001",
    sample_count: 42,
    status: "complete",
    ...overrides,
  };
}

function makeHistoryInsightsAnalyzingPayload(runId: string): HistoryInsightsLike {
  return {
    run_id: runId,
    status: "analyzing",
  };
}

export function makeHistoryBinaryDownloadResponse(
  overrides: Partial<BinaryResponseInit> = {},
): BinaryResponseInit {
  return {
    body: "PDF",
    contentType: "application/pdf",
    filename: "run-001_report.pdf",
    status: 200,
    ...overrides,
  };
}

export function buildHistoryHandlers(options: {
  list?: JsonHandlerResult<HistoryListPayload>;
  deleteRun?: JsonHandlerResult<DeleteHistoryRunPayload>;
  runDetail?: JsonHandlerResult<HistoryRunPayload>;
  insights?: JsonHandlerResult<HistoryInsightsLike>;
} = {}) {
  const list = options.list ?? makeHistoryListPayload();
  const deleteRun = options.deleteRun ?? makeDeleteHistoryRunPayload();
  const runDetail = options.runDetail ?? makeHistoryRunPayload();
  const insights = options.insights ?? makeHistoryInsightsAnalyzingPayload("run-001");
  return [
    http.get(uiRoutePath("/api/history"), async ({ request }) =>
      await resolveJsonResult(request, list)),
    http.delete(uiRoutePath("/api/history/:runId"), async ({ request }) =>
      await resolveJsonResult(request, deleteRun)),
    http.get(uiRoutePath("/api/history/:runId"), async ({ request }) =>
      await resolveJsonResult(request, runDetail)),
    http.get(uiRoutePath("/api/history/:runId/insights"), async ({ request }) =>
      await resolveJsonResult(request, insights)),
  ];
}

export function buildHistoryDownloadHandlers(options: {
  reportPdf?: BinaryHandlerResult;
  exportArchive?: BinaryHandlerResult;
} = {}) {
  const reportPdf = options.reportPdf ?? makeHistoryBinaryDownloadResponse();
  const exportArchive = options.exportArchive ?? makeHistoryBinaryDownloadResponse({
    body: "ZIP",
    contentType: "application/zip",
    filename: "run-001_export.zip",
  });
  return [
    http.get(uiRoutePath("/api/history/:runId/report.pdf"), async ({ request }) =>
      await resolveBinaryResult(request, reportPdf)),
    http.get(uiRoutePath("/api/history/:runId/export"), async ({ request }) =>
      await resolveBinaryResult(request, exportArchive)),
  ];
}

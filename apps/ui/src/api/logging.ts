import { apiJson } from "./http";
import type { LoggingStatusPayload } from "./types";

export async function getLoggingStatus(): Promise<LoggingStatusPayload> {
  return apiJson("/api/logging/status");
}

export async function startLoggingRun(): Promise<LoggingStatusPayload> {
  return apiJson("/api/logging/start", { method: "POST" });
}

export async function stopLoggingRun(): Promise<LoggingStatusPayload> {
  return apiJson("/api/logging/stop", { method: "POST" });
}

import { apiJson } from "./http";
import type { LoggingStatusPayload } from "./types";

export async function getLoggingStatus(): Promise<LoggingStatusPayload> {
  return apiJson("/api/recording/status");
}

export async function startLoggingRun(): Promise<LoggingStatusPayload> {
  return apiJson("/api/recording/start", { method: "POST" });
}

export async function stopLoggingRun(): Promise<LoggingStatusPayload> {
  return apiJson("/api/recording/stop", { method: "POST" });
}

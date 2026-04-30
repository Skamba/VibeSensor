import { apiJson } from "./http";
import type * as Local from "../api/types";
import type * as Transport from "./types";

export async function getLoggingStatus(): Promise<Local.LoggingStatusPayload> {
  return await apiJson<Transport.LoggingStatusPayload>("/api/recording/status");
}

export async function startLoggingRun(): Promise<Local.LoggingStatusPayload> {
  return await apiJson<Transport.LoggingStatusPayload>("/api/recording/start", {
    method: "POST",
  });
}

export async function stopLoggingRun(): Promise<Local.LoggingStatusPayload> {
  return await apiJson<Transport.LoggingStatusPayload>("/api/recording/stop", {
    method: "POST",
  });
}

import { apiJson } from "./http";
import type * as Local from "../api/types";
import type * as Transport from "./types";

const JSON_HEADERS: HeadersInit = { "Content-Type": "application/json" };

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

/** Marks the guided test-drive step the driver starts now; `null` ends the guided test. */
export async function markGuidedPhase(
  phase: Local.GuidedPhase | null,
): Promise<Local.LoggingStatusPayload> {
  return await apiJson<Transport.LoggingStatusPayload>(
    "/api/recording/guided-phase",
    { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ phase }) },
  );
}

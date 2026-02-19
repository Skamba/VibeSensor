import { apiJson } from "./http";

export async function getLoggingStatus(): Promise<unknown> {
  return apiJson("/api/logging/status");
}

export async function startLoggingRun(): Promise<unknown> {
  return apiJson("/api/logging/start", { method: "POST" });
}

export async function stopLoggingRun(): Promise<unknown> {
  return apiJson("/api/logging/stop", { method: "POST" });
}

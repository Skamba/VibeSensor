import { apiJson } from "./http";
import { fromTransportPayload } from "../transport/http_adapters";
import type * as Local from "../transport/http_models";
import type * as Transport from "./types";

export async function getLoggingStatus(): Promise<Local.LoggingStatusPayload> {
  return fromTransportPayload<Transport.LoggingStatusPayload, Local.LoggingStatusPayload>(
    await apiJson<Transport.LoggingStatusPayload>("/api/recording/status"),
  );
}

export async function startLoggingRun(): Promise<Local.LoggingStatusPayload> {
  return fromTransportPayload<Transport.LoggingStatusPayload, Local.LoggingStatusPayload>(
    await apiJson<Transport.LoggingStatusPayload>("/api/recording/start", { method: "POST" }),
  );
}

export async function stopLoggingRun(): Promise<Local.LoggingStatusPayload> {
  return fromTransportPayload<Transport.LoggingStatusPayload, Local.LoggingStatusPayload>(
    await apiJson<Transport.LoggingStatusPayload>("/api/recording/stop", { method: "POST" }),
  );
}

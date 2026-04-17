import { apiJson } from "./http";
import type * as Local from "../api/types";
import type * as Transport from "./types";

const JSON_HEADERS: HeadersInit = { "Content-Type": "application/json" };

export async function getClientLocations(): Promise<Local.ClientLocationsResponse> {
  return await apiJson<Transport.ClientLocationsResponse>("/api/client-locations");
}

export async function setClientLocation(clientId: string, locationCode: string): Promise<void> {
  await apiJson(`/api/clients/${encodeURIComponent(clientId)}/location`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ location_code: locationCode }),
  });
}

export async function identifyClient(clientId: string, durationMs = 1500): Promise<void> {
  await apiJson(`/api/clients/${encodeURIComponent(clientId)}/identify`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ duration_ms: durationMs }),
  });
}

export async function removeClient(clientId: string): Promise<void> {
  await apiJson(`/api/clients/${encodeURIComponent(clientId)}`, {
    method: "DELETE",
  });
}

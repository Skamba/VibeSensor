import { apiJson } from "./http";

export type LocationOption = {
  code: string;
  label: string;
};

export type ClientLocationsResponse = {
  locations: LocationOption[];
};

export async function getClientLocations(): Promise<ClientLocationsResponse> {
  return apiJson("/api/client-locations");
}

export async function setClientLocation(clientId: string, locationCode: string): Promise<unknown> {
  return apiJson(`/api/clients/${encodeURIComponent(clientId)}/location`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ location_code: locationCode }),
  });
}

export async function identifyClient(clientId: string, durationMs = 1500): Promise<unknown> {
  return apiJson(`/api/clients/${encodeURIComponent(clientId)}/identify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ duration_ms: durationMs }),
  });
}

export async function removeClient(clientId: string): Promise<unknown> {
  return apiJson(`/api/clients/${encodeURIComponent(clientId)}`, {
    method: "DELETE",
  });
}

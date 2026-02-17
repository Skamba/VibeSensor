export async function apiJson<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      if (payload && typeof payload.detail === "string") {
        detail = payload.detail;
      }
    } catch {
      // Ignore parse errors on non-JSON responses.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

// -- Response types -----------------------------------------------------------

export type CarRecord = {
  id: string;
  name: string;
  type: string;
  aspects: Record<string, number>;
  [key: string]: unknown;
};

export type CarsPayload = {
  cars: CarRecord[];
  activeCarId: string | null;
};

export type SpeedSourcePayload = {
  speedSource: string;
  manualSpeedKph: number | null;
};

export type LogEntry = {
  name: string;
  size: number;
  [key: string]: unknown;
};

export type CarLibraryModel = {
  model: string;
  tire_width_mm: number;
  tire_aspect_pct: number;
  rim_in: number;
  [key: string]: unknown;
};

export function logDownloadUrl(logName: string): string {
  return `/api/logs/${encodeURIComponent(logName)}`;
}

export function reportPdfUrl(logName: string, lang: string): string {
  return `/api/logs/${encodeURIComponent(logName)}/report.pdf?lang=${encodeURIComponent(lang)}`;
}

export async function getClientLocations(): Promise<Record<string, string>> {
  return apiJson("/api/client-locations");
}

export async function getSpeedOverride(): Promise<{ speed_kmh: number | null }> {
  return apiJson("/api/speed-override");
}

export async function setSpeedOverride(speedKmh: number | null): Promise<{ speed_kmh: number | null }> {
  return apiJson("/api/speed-override", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ speed_kmh: speedKmh }),
  });
}

export async function getAnalysisSettings(): Promise<Record<string, number>> {
  return apiJson("/api/analysis-settings");
}

export async function setAnalysisSettings(payload: Record<string, number>): Promise<Record<string, number>> {
  return apiJson("/api/analysis-settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// -- Car library API ----------------------------------------------------------

export async function getCarLibraryBrands(): Promise<{ brands: string[] }> {
  return apiJson("/api/car-library/brands");
}

export async function getCarLibraryTypes(brand: string): Promise<{ types: string[] }> {
  return apiJson(`/api/car-library/types?brand=${encodeURIComponent(brand)}`);
}

export async function getCarLibraryModels(brand: string, type: string): Promise<{ models: CarLibraryModel[] }> {
  return apiJson(`/api/car-library/models?brand=${encodeURIComponent(brand)}&type=${encodeURIComponent(type)}`);
}

// -- New settings API (3-tab model) -------------------------------------------

export async function getSettingsCars(): Promise<CarsPayload> {
  return apiJson("/api/settings/cars");
}

export async function addSettingsCar(car: Record<string, unknown>): Promise<CarsPayload> {
  return apiJson("/api/settings/cars", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(car),
  });
}

export async function updateSettingsCar(carId: string, car: Record<string, unknown>): Promise<CarsPayload> {
  return apiJson(`/api/settings/cars/${encodeURIComponent(carId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(car),
  });
}

export async function deleteSettingsCar(carId: string): Promise<CarsPayload> {
  return apiJson(`/api/settings/cars/${encodeURIComponent(carId)}`, {
    method: "DELETE",
  });
}

export async function setActiveSettingsCar(carId: string): Promise<CarsPayload> {
  return apiJson("/api/settings/cars/active", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ carId }),
  });
}

export async function getSettingsSpeedSource(): Promise<SpeedSourcePayload> {
  return apiJson("/api/settings/speed-source");
}

export async function updateSettingsSpeedSource(data: Record<string, unknown>): Promise<SpeedSourcePayload> {
  return apiJson("/api/settings/speed-source", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function getSettingsSensors(): Promise<unknown> {
  return apiJson("/api/settings/sensors");
}

export async function updateSettingsSensor(mac: string, data: Record<string, unknown>): Promise<unknown> {
  return apiJson(`/api/settings/sensors/${encodeURIComponent(mac)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function deleteSettingsSensor(mac: string): Promise<unknown> {
  return apiJson(`/api/settings/sensors/${encodeURIComponent(mac)}`, {
    method: "DELETE",
  });
}

export async function getLoggingStatus(): Promise<unknown> {
  return apiJson("/api/logging/status");
}

export async function startLoggingRun(): Promise<unknown> {
  return apiJson("/api/logging/start", { method: "POST" });
}

export async function stopLoggingRun(): Promise<unknown> {
  return apiJson("/api/logging/stop", { method: "POST" });
}

export async function getLogs(): Promise<{ logs: LogEntry[] }> {
  return apiJson("/api/logs");
}

export async function deleteLog(logName: string): Promise<void> {
  await apiJson(`/api/logs/${encodeURIComponent(logName)}`, { method: "DELETE" });
}

export async function getLogInsights(
  logName: string,
  lang: string,
  includeSamples = false,
): Promise<unknown> {
  return apiJson(
    `/api/logs/${encodeURIComponent(logName)}/insights?lang=${encodeURIComponent(lang)}&include_samples=${includeSamples ? "1" : "0"}`,
  );
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

export async function apiJson(path: string, init?: RequestInit): Promise<any> {
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
  return response.json();
}

export function logDownloadUrl(logName: string): string {
  return `/api/logs/${encodeURIComponent(logName)}`;
}

export function reportPdfUrl(logName: string, lang: string): string {
  return `/api/logs/${encodeURIComponent(logName)}/report.pdf?lang=${encodeURIComponent(lang)}`;
}

export async function getClientLocations(): Promise<any> {
  return apiJson("/api/client-locations");
}

export async function getSpeedOverride(): Promise<any> {
  return apiJson("/api/speed-override");
}

export async function setSpeedOverride(speedKmh: number | null): Promise<any> {
  return apiJson("/api/speed-override", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ speed_kmh: speedKmh }),
  });
}

export async function getAnalysisSettings(): Promise<any> {
  return apiJson("/api/analysis-settings");
}

export async function setAnalysisSettings(payload: Record<string, number>): Promise<any> {
  return apiJson("/api/analysis-settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// -- New settings API (3-tab model) -------------------------------------------

export async function getSettingsCars(): Promise<any> {
  return apiJson("/api/settings/cars");
}

export async function addSettingsCar(car: Record<string, any>): Promise<any> {
  return apiJson("/api/settings/cars", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(car),
  });
}

export async function updateSettingsCar(carId: string, car: Record<string, any>): Promise<any> {
  return apiJson(`/api/settings/cars/${encodeURIComponent(carId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(car),
  });
}

export async function deleteSettingsCar(carId: string): Promise<any> {
  return apiJson(`/api/settings/cars/${encodeURIComponent(carId)}`, {
    method: "DELETE",
  });
}

export async function setActiveSettingsCar(carId: string): Promise<any> {
  return apiJson("/api/settings/cars/active", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ carId }),
  });
}

export async function getSettingsSpeedSource(): Promise<any> {
  return apiJson("/api/settings/speed-source");
}

export async function updateSettingsSpeedSource(data: Record<string, any>): Promise<any> {
  return apiJson("/api/settings/speed-source", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function getSettingsSensors(): Promise<any> {
  return apiJson("/api/settings/sensors");
}

export async function updateSettingsSensor(mac: string, data: Record<string, any>): Promise<any> {
  return apiJson(`/api/settings/sensors/${encodeURIComponent(mac)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function deleteSettingsSensor(mac: string): Promise<any> {
  return apiJson(`/api/settings/sensors/${encodeURIComponent(mac)}`, {
    method: "DELETE",
  });
}

export async function getLoggingStatus(): Promise<any> {
  return apiJson("/api/logging/status");
}

export async function startLoggingRun(): Promise<any> {
  return apiJson("/api/logging/start", { method: "POST" });
}

export async function stopLoggingRun(): Promise<any> {
  return apiJson("/api/logging/stop", { method: "POST" });
}

export async function getLogs(): Promise<any> {
  return apiJson("/api/logs");
}

export async function deleteLog(logName: string): Promise<void> {
  await apiJson(`/api/logs/${encodeURIComponent(logName)}`, { method: "DELETE" });
}

export async function getLogInsights(
  logName: string,
  lang: string,
  includeSamples = false,
): Promise<any> {
  return apiJson(
    `/api/logs/${encodeURIComponent(logName)}/insights?lang=${encodeURIComponent(lang)}&include_samples=${includeSamples ? "1" : "0"}`,
  );
}

export async function setClientLocation(clientId: string, locationCode: string): Promise<any> {
  return apiJson(`/api/clients/${encodeURIComponent(clientId)}/location`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ location_code: locationCode }),
  });
}

export async function identifyClient(clientId: string, durationMs = 1500): Promise<any> {
  return apiJson(`/api/clients/${encodeURIComponent(clientId)}/identify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ duration_ms: durationMs }),
  });
}

export async function removeClient(clientId: string): Promise<any> {
  return apiJson(`/api/clients/${encodeURIComponent(clientId)}`, {
    method: "DELETE",
  });
}

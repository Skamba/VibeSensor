import { apiJson } from "./http";
import type { CarsPayload, SpeedSourcePayload } from "./types";

export async function getSettingsLanguage(): Promise<{ language: string }> {
  return apiJson("/api/settings/language");
}

export async function setSettingsLanguage(language: string): Promise<{ language: string }> {
  return apiJson("/api/settings/language", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ language }),
  });
}

export async function getSettingsSpeedUnit(): Promise<{ speedUnit: string }> {
  return apiJson("/api/settings/speed-unit");
}

export async function setSettingsSpeedUnit(speedUnit: string): Promise<{ speedUnit: string }> {
  return apiJson("/api/settings/speed-unit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ speedUnit }),
  });
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

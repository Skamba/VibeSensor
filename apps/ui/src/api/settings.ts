import { apiJson } from "./http";
import type {
  AnalysisSettingsPayload,
  CarsPayload,
  EspFlashCancelPayload,
  EspFlashHistoryPayload,
  EspFlashLogsPayload,
  EspFlashPortsPayload,
  EspFlashStartPayload,
  EspFlashStatusPayload,
  HealthStatusPayload,
  LanguagePayload,
  SpeedSourcePayload,
  SpeedSourceStatusPayload,
  SpeedUnitPayload,
  UpdateCancelPayload,
  UpdateStartPayload,
  UpdateStatusPayload,
} from "./types";

const JSON_HEADERS: HeadersInit = { "Content-Type": "application/json" };

export async function getSettingsLanguage(): Promise<LanguagePayload> {
  return apiJson("/api/settings/language");
}

export async function setSettingsLanguage(language: string): Promise<LanguagePayload> {
  return apiJson("/api/settings/language", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ language }),
  });
}

export async function getSettingsSpeedUnit(): Promise<SpeedUnitPayload> {
  return apiJson("/api/settings/speed-unit");
}

export async function setSettingsSpeedUnit(speedUnit: string): Promise<SpeedUnitPayload> {
  return apiJson("/api/settings/speed-unit", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ speedUnit }),
  });
}

export async function getAnalysisSettings(): Promise<AnalysisSettingsPayload> {
  return apiJson("/api/analysis-settings");
}

export async function setAnalysisSettings(payload: Record<string, number>): Promise<AnalysisSettingsPayload> {
  return apiJson("/api/analysis-settings", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export async function getSettingsCars(): Promise<CarsPayload> {
  return apiJson("/api/settings/cars");
}

export async function addSettingsCar(car: Record<string, unknown>): Promise<CarsPayload> {
  return apiJson("/api/settings/cars", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(car),
  });
}

export async function updateSettingsCar(carId: string, car: Record<string, unknown>): Promise<CarsPayload> {
  return apiJson(`/api/settings/cars/${encodeURIComponent(carId)}`, {
    method: "PUT",
    headers: JSON_HEADERS,
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
    headers: JSON_HEADERS,
    body: JSON.stringify({ carId }),
  });
}

export async function getSettingsSpeedSource(): Promise<SpeedSourcePayload> {
  return apiJson("/api/settings/speed-source");
}

export async function updateSettingsSpeedSource(data: Record<string, unknown>): Promise<SpeedSourcePayload> {
  return apiJson("/api/settings/speed-source", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(data),
  });
}

export async function getSpeedSourceStatus(): Promise<SpeedSourceStatusPayload> {
  return apiJson("/api/settings/speed-source/status");
}

export async function getUpdateStatus(): Promise<UpdateStatusPayload> {
  return apiJson("/api/settings/update/status");
}

export async function getHealthStatus(): Promise<HealthStatusPayload> {
  return apiJson("/api/health");
}

export async function startUpdate(ssid: string, password: string): Promise<UpdateStartPayload> {
  return apiJson("/api/settings/update/start", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ ssid, password }),
  });
}

export async function cancelUpdate(): Promise<UpdateCancelPayload> {
  return apiJson("/api/settings/update/cancel", {
    method: "POST",
  });
}

export async function getEspFlashPorts(): Promise<EspFlashPortsPayload> {
  return apiJson("/api/settings/esp-flash/ports");
}

export async function startEspFlash(port: string | null, auto_detect: boolean): Promise<EspFlashStartPayload> {
  return apiJson("/api/settings/esp-flash/start", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ port, auto_detect }),
  });
}

export async function getEspFlashStatus(): Promise<EspFlashStatusPayload> {
  return apiJson("/api/settings/esp-flash/status");
}

export async function getEspFlashLogs(after: number): Promise<EspFlashLogsPayload> {
  return apiJson(`/api/settings/esp-flash/logs?after=${encodeURIComponent(String(after))}`);
}

export async function cancelEspFlash(): Promise<EspFlashCancelPayload> {
  return apiJson("/api/settings/esp-flash/cancel", {
    method: "POST",
  });
}

export async function getEspFlashHistory(): Promise<EspFlashHistoryPayload> {
  return apiJson("/api/settings/esp-flash/history");
}

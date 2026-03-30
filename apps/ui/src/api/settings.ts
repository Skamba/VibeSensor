import { apiJson } from "./http";
import type {
  AnalysisSettingsRequest,
  AnalysisSettingsPayload,
  CarUpsertRequest,
  CarsPayload,
  EspFlashCancelPayload,
  EspFlashHistoryPayload,
  EspFlashLogsPayload,
  EspFlashPortsPayload,
  EspFlashStartPayload,
  EspFlashStatusPayload,
  HealthStatusPayload,
  LanguagePayload,
  ObdPairPayload,
  ObdScanPayload,
  ObdStatusPayload,
  SpeedSourceRequest,
  SpeedSourcePayload,
  SpeedSourceStatusPayload,
  SpeedUnitPayload,
  UpdateCancelPayload,
  UpdateStartRequestPayload,
  UpdateStartPayload,
  UpdateStatusPayload,
  UsbInternetStatusPayload,
} from "./types";

const JSON_HEADERS: HeadersInit = { "Content-Type": "application/json" };
const OBD_SCAN_TIMEOUT_MS = 20_000;

export async function getSettingsLanguage(): Promise<LanguagePayload> {
  return apiJson("/api/settings/language");
}

export async function setSettingsLanguage(language: string): Promise<LanguagePayload> {
  return apiJson("/api/settings/language", {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify({ language }),
  });
}

export async function getSettingsSpeedUnit(): Promise<SpeedUnitPayload> {
  return apiJson("/api/settings/speed-unit");
}

export async function setSettingsSpeedUnit(speedUnit: string): Promise<SpeedUnitPayload> {
  return apiJson("/api/settings/speed-unit", {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify({ speed_unit: speedUnit }),
  });
}

export async function getAnalysisSettings(): Promise<AnalysisSettingsPayload> {
  return apiJson("/api/settings/analysis");
}

export async function setAnalysisSettings(payload: AnalysisSettingsRequest): Promise<AnalysisSettingsPayload> {
  return apiJson("/api/settings/analysis", {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export async function getSettingsCars(): Promise<CarsPayload> {
  return apiJson("/api/settings/cars");
}

export async function addSettingsCar(car: CarUpsertRequest): Promise<CarsPayload> {
  return apiJson("/api/settings/cars", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(car),
  });
}

export async function updateSettingsCar(carId: string, car: CarUpsertRequest): Promise<CarsPayload> {
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
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify({ car_id: carId }),
  });
}

export async function getSettingsSpeedSource(): Promise<SpeedSourcePayload> {
  return apiJson("/api/settings/speed-source");
}

export async function updateSettingsSpeedSource(data: SpeedSourceRequest): Promise<SpeedSourcePayload> {
  return apiJson("/api/settings/speed-source", {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify(data),
  });
}

export async function getSpeedSourceStatus(): Promise<SpeedSourceStatusPayload> {
  return apiJson("/api/settings/speed-source/status");
}

export async function scanSettingsObdDevices(): Promise<ObdScanPayload> {
  return apiJson("/api/settings/obd/scan", {
    method: "POST",
    timeoutMs: OBD_SCAN_TIMEOUT_MS,
  });
}

export async function pairSettingsObdDevice(macAddress: string): Promise<ObdPairPayload> {
  return apiJson("/api/settings/obd/pair", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ mac_address: macAddress }),
  });
}

export async function getSettingsObdStatus(): Promise<ObdStatusPayload> {
  return apiJson("/api/settings/obd/status");
}

export async function getUpdateStatus(): Promise<UpdateStatusPayload> {
  return apiJson("/api/update/status");
}

export async function getUpdateInternetStatus(): Promise<UsbInternetStatusPayload> {
  return apiJson("/api/update/internet-status");
}

export async function getHealthStatus(): Promise<HealthStatusPayload> {
  return apiJson("/api/health");
}

export async function startUpdate(payload: UpdateStartRequestPayload): Promise<UpdateStartPayload> {
  return apiJson("/api/update/start", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export async function cancelUpdate(): Promise<UpdateCancelPayload> {
  return apiJson("/api/update/cancel", {
    method: "POST",
  });
}

export async function getEspFlashPorts(): Promise<EspFlashPortsPayload> {
  return apiJson("/api/esp-flash/ports");
}

export async function startEspFlash(port: string | null, auto_detect: boolean): Promise<EspFlashStartPayload> {
  return apiJson("/api/esp-flash/start", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ port, auto_detect }),
  });
}

export async function getEspFlashStatus(): Promise<EspFlashStatusPayload> {
  return apiJson("/api/esp-flash/status");
}

export async function getEspFlashLogs(after: number): Promise<EspFlashLogsPayload> {
  return apiJson(`/api/esp-flash/logs?after=${encodeURIComponent(String(after))}`);
}

export async function cancelEspFlash(): Promise<EspFlashCancelPayload> {
  return apiJson("/api/esp-flash/cancel", {
    method: "POST",
  });
}

export async function getEspFlashHistory(): Promise<EspFlashHistoryPayload> {
  return apiJson("/api/esp-flash/history");
}

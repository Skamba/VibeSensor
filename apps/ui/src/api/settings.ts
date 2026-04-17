import { apiJson } from "./http";
import { cloneTransportValue } from "../transport/clone";
import type * as Local from "../transport/http_models";
import type * as Transport from "./types";

const JSON_HEADERS: HeadersInit = { "Content-Type": "application/json" };
const OBD_SCAN_TIMEOUT_MS = 20_000;

export async function getSettingsLanguage(): Promise<Local.LanguagePayload> {
  return cloneTransportValue(
    await apiJson<Transport.LanguagePayload>("/api/settings/language"),
  );
}

export async function setSettingsLanguage(language: string): Promise<Local.LanguagePayload> {
  return cloneTransportValue(
    await apiJson<Transport.LanguagePayload>("/api/settings/language", {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify({ language }),
    }),
  );
}

export async function getSettingsSpeedUnit(): Promise<Local.SpeedUnitPayload> {
  return cloneTransportValue(
    await apiJson<Transport.SpeedUnitPayload>("/api/settings/speed-unit"),
  );
}

export async function setSettingsSpeedUnit(speedUnit: string): Promise<Local.SpeedUnitPayload> {
  return cloneTransportValue(
    await apiJson<Transport.SpeedUnitPayload>("/api/settings/speed-unit", {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify({ speed_unit: speedUnit }),
    }),
  );
}

export async function getAnalysisSettings(): Promise<Local.AnalysisSettingsPayload> {
  return cloneTransportValue(
    await apiJson<Transport.AnalysisSettingsPayload>("/api/settings/analysis"),
  );
}

export async function setAnalysisSettings(
  payload: Local.AnalysisSettingsRequest,
): Promise<Local.AnalysisSettingsPayload> {
  return cloneTransportValue(
    await apiJson<Transport.AnalysisSettingsPayload>("/api/settings/analysis", {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify(
        cloneTransportValue(payload),
      ),
    }),
  );
}

export async function getSettingsCars(): Promise<Local.CarsPayload> {
  return cloneTransportValue(
    await apiJson<Transport.CarsPayload>("/api/settings/cars"),
  );
}

export async function addSettingsCar(car: Local.CarUpsertRequest): Promise<Local.CarsPayload> {
  return cloneTransportValue(
    await apiJson<Transport.CarsPayload>("/api/settings/cars", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(cloneTransportValue(car)),
    }),
  );
}

export async function updateSettingsCar(
  carId: string,
  car: Local.CarUpsertRequest,
): Promise<Local.CarsPayload> {
  return cloneTransportValue(
    await apiJson<Transport.CarsPayload>(`/api/settings/cars/${encodeURIComponent(carId)}`, {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify(cloneTransportValue(car)),
    }),
  );
}

export async function deleteSettingsCar(carId: string): Promise<Local.CarsPayload> {
  return cloneTransportValue(
    await apiJson<Transport.CarsPayload>(`/api/settings/cars/${encodeURIComponent(carId)}`, {
      method: "DELETE",
    }),
  );
}

export async function setActiveSettingsCar(carId: string): Promise<Local.CarsPayload> {
  return cloneTransportValue(
    await apiJson<Transport.CarsPayload>("/api/settings/cars/active", {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify({ car_id: carId }),
    }),
  );
}

export async function getSettingsSpeedSource(): Promise<Local.SpeedSourcePayload> {
  return cloneTransportValue(
    await apiJson<Transport.SpeedSourcePayload>("/api/settings/speed-source"),
  );
}

export async function updateSettingsSpeedSource(
  data: Local.SpeedSourceRequest,
): Promise<Local.SpeedSourcePayload> {
  return cloneTransportValue(
    await apiJson<Transport.SpeedSourcePayload>("/api/settings/speed-source", {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify(cloneTransportValue(data)),
    }),
  );
}

export async function getSpeedSourceStatus(): Promise<Local.SpeedSourceStatusPayload> {
  return cloneTransportValue(
    await apiJson<Transport.SpeedSourceStatusPayload>("/api/settings/speed-source/status"),
  );
}

export async function scanSettingsObdDevices(): Promise<Local.ObdScanPayload> {
  return cloneTransportValue(
    await apiJson<Transport.ObdScanPayload>("/api/settings/obd/scan", {
      method: "POST",
      timeoutMs: OBD_SCAN_TIMEOUT_MS,
    }),
  );
}

export async function pairSettingsObdDevice(macAddress: string): Promise<Local.ObdPairPayload> {
  return cloneTransportValue(
    await apiJson<Transport.ObdPairPayload>("/api/settings/obd/pair", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ mac_address: macAddress }),
    }),
  );
}

export async function getSettingsObdStatus(): Promise<Local.ObdStatusPayload> {
  return cloneTransportValue(
    await apiJson<Transport.ObdStatusPayload>("/api/settings/obd/status"),
  );
}

export async function getUpdateStatus(): Promise<Local.UpdateStatusPayload> {
  return cloneTransportValue(
    await apiJson<Transport.UpdateStatusPayload>("/api/update/status"),
  );
}

export async function getUpdateInternetStatus(): Promise<Local.UsbInternetStatusPayload> {
  return cloneTransportValue(
    await apiJson<Transport.UsbInternetStatusPayload>("/api/update/internet-status"),
  );
}

export async function getHealthStatus(): Promise<Local.HealthStatusPayload> {
  return cloneTransportValue(
    await apiJson<Transport.HealthStatusPayload>("/api/health"),
  );
}

export async function startUpdate(
  payload: Local.UpdateStartRequestPayload,
): Promise<Local.UpdateStartPayload> {
  return cloneTransportValue(
    await apiJson<Transport.UpdateStartPayload>("/api/update/start", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(
        cloneTransportValue(payload),
      ),
    }),
  );
}

export async function cancelUpdate(): Promise<Local.UpdateCancelPayload> {
  return cloneTransportValue(
    await apiJson<Transport.UpdateCancelPayload>("/api/update/cancel", {
      method: "POST",
    }),
  );
}

export async function getEspFlashPorts(): Promise<Local.EspFlashPortsPayload> {
  return cloneTransportValue(
    await apiJson<Transport.EspFlashPortsPayload>("/api/esp-flash/ports"),
  );
}

export async function startEspFlash(
  port: string | null,
  auto_detect: boolean,
): Promise<Local.EspFlashStartPayload> {
  return cloneTransportValue(
    await apiJson<Transport.EspFlashStartPayload>("/api/esp-flash/start", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ port, auto_detect }),
    }),
  );
}

export async function getEspFlashStatus(): Promise<Local.EspFlashStatusPayload> {
  return cloneTransportValue(
    await apiJson<Transport.EspFlashStatusPayload>("/api/esp-flash/status"),
  );
}

export async function getEspFlashLogs(after: number): Promise<Local.EspFlashLogsPayload> {
  return cloneTransportValue(
    await apiJson<Transport.EspFlashLogsPayload>(
      `/api/esp-flash/logs?after=${encodeURIComponent(String(after))}`,
    ),
  );
}

export async function cancelEspFlash(): Promise<Local.EspFlashCancelPayload> {
  return cloneTransportValue(
    await apiJson<Transport.EspFlashCancelPayload>("/api/esp-flash/cancel", {
      method: "POST",
    }),
  );
}

export async function getEspFlashHistory(): Promise<Local.EspFlashHistoryPayload> {
  return cloneTransportValue(
    await apiJson<Transport.EspFlashHistoryPayload>("/api/esp-flash/history"),
  );
}

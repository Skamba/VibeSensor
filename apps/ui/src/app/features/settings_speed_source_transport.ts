import {
  getSettingsSpeedSource as getSettingsSpeedSourceApi,
  pairSettingsObdDevice as pairSettingsObdDeviceApi,
  scanSettingsObdDevices as scanSettingsObdDevicesApi,
  updateSettingsSpeedSource as updateSettingsSpeedSourceApi,
} from "../../api/settings";
import type {
  ObdPairPayload,
  ObdScanPayload,
  SpeedSourcePayload,
  SpeedSourceRequest,
} from "../../api/types";

export interface SettingsSpeedSourceTransport {
  loadSpeedSource(): Promise<SpeedSourcePayload>;
  pairObdDevice(macAddress: string): Promise<ObdPairPayload>;
  saveSpeedSource(payload: SpeedSourceRequest): Promise<SpeedSourcePayload>;
  scanObdDevices(): Promise<ObdScanPayload>;
}

export function createSettingsSpeedSourceTransport(
  overrides: Partial<SettingsSpeedSourceTransport> = {},
): SettingsSpeedSourceTransport {
  return {
    loadSpeedSource: overrides.loadSpeedSource ?? getSettingsSpeedSourceApi,
    pairObdDevice: overrides.pairObdDevice ?? pairSettingsObdDeviceApi,
    saveSpeedSource: overrides.saveSpeedSource ?? updateSettingsSpeedSourceApi,
    scanObdDevices: overrides.scanObdDevices ?? scanSettingsObdDevicesApi,
  };
}

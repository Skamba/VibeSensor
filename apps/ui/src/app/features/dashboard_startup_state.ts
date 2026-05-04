import type { QueryClient } from "@tanstack/query-core";

import type { CarsPayload, SpeedSourcePayload } from "../../api/types";
import type { SettingsState } from "../settings_state";
import { batch } from "../ui_signals";
import { serverStateQueryKeys } from "./server_state_query_keys";
import { createSettingsCarsTransport } from "./settings_cars_transport";
import { createSettingsSpeedSourceTransport } from "./settings_speed_source_transport";

export function applyCarsPayloadToSettings(
  settings: SettingsState["car"],
  payload: CarsPayload,
): void {
  batch(() => {
    settings.cars.value = payload.cars;
    settings.carsLoaded.value = true;
    const requestedActiveCarId = payload.active_car_id;
    const hasRequestedActive = requestedActiveCarId
      ? settings.cars.value.some((car) => car.id === requestedActiveCarId)
      : false;
    settings.activeCarId.value = hasRequestedActive
      ? requestedActiveCarId
      : null;
  });
}

export function applySpeedSourcePayloadToSettings(
  settings: SettingsState["speed"],
  payload: SpeedSourcePayload,
  options: { preserveResolvedSource?: boolean } = {},
): void {
  batch(() => {
    settings.source.value = payload.speed_source;
    settings.manualSpeedKph.value = payload.manual_speed_kph;
    settings.obdDeviceMac.value = payload.obd_device_mac ?? null;
    settings.obdDeviceName.value = payload.obd_device_name ?? null;
    if (!options.preserveResolvedSource) {
      settings.resolvedSource.value = null;
    }
  });
}

export async function loadDashboardStartupState(
  queryClient: QueryClient,
  settings: SettingsState,
): Promise<void> {
  const carsTransport = createSettingsCarsTransport(undefined);
  const speedSourceTransport = createSettingsSpeedSourceTransport();
  const [carsPayload, speedSourcePayload] = await Promise.all([
    queryClient.fetchQuery({
      queryFn: () => carsTransport.loadCars(),
      queryKey: serverStateQueryKeys.settings.cars(),
      staleTime: 0,
    }),
    queryClient.fetchQuery({
      queryFn: () => speedSourceTransport.loadSpeedSource(),
      queryKey: serverStateQueryKeys.settings.speedSource(),
      staleTime: 0,
    }),
  ]);
  applyCarsPayloadToSettings(settings.car, carsPayload);
  applySpeedSourcePayloadToSettings(settings.speed, speedSourcePayload, {
    preserveResolvedSource: true,
  });
}

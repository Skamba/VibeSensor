import type { QueryClient } from "@tanstack/query-core";

import { getSettingsCars } from "../../api/settings";
import type { CarsPayload } from "../../api/types";
import type { SettingsState } from "../ui_app_state";
import { batch } from "../ui_signals";
import { serverStateQueryKeys } from "./server_state_query_keys";

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

export async function loadDashboardStartupState(
  queryClient: QueryClient,
  settings: SettingsState,
): Promise<void> {
  const carsPayload = await queryClient.fetchQuery({
    queryFn: () => getSettingsCars(),
    queryKey: serverStateQueryKeys.settings.cars(),
    staleTime: 0,
  });
  applyCarsPayloadToSettings(settings.car, carsPayload);
}

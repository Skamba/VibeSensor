import { batch, computed } from "@preact/signals";

import {
  identifyClient,
  removeClient,
  setClientLocation,
} from "../../api/clients";
import {
  errorMessage,
  navigate,
  requestConfirmation,
  showError,
} from "../../app_store";
import { t } from "../../i18n";
import { clients, syncSelection } from "../../live_store";

/** Sensors whose firmware is older than the build this Pi flashes. */
export const outdatedFirmwareCount = computed(
  () =>
    clients.value.filter((client) => client.firmware_status === "outdated")
      .length,
);

/** Sensor firmware is updated over USB with the ESP Flash tab. */
export function openFirmwareUpdate(): void {
  navigate("settingsView", "espFlashTab");
}

export async function setLocation(
  clientId: string,
  locationCode: string,
): Promise<void> {
  const current = clients.value.find((client) => client.id === clientId);
  if (current && String(current.location_code || "").trim() === locationCode) {
    return;
  }
  try {
    await setClientLocation(clientId, locationCode);
  } catch (error) {
    showError(errorMessage(error, t("actions.set_location_failed")));
    return;
  }
  clients.value = clients.value.map((client) =>
    client.id === clientId
      ? { ...client, location_code: locationCode }
      : client,
  );
}

export async function identify(clientId: string): Promise<void> {
  try {
    await identifyClient(clientId);
  } catch (error) {
    showError(errorMessage(error, t("actions.identify_failed")));
  }
}

export async function remove(clientId: string): Promise<void> {
  if (
    !(await requestConfirmation(
      t("actions.remove_client_confirm", { id: clientId }),
    ))
  ) {
    return;
  }
  try {
    await removeClient(clientId);
  } catch (error) {
    showError(errorMessage(error, t("actions.remove_client_failed")));
    return;
  }
  batch(() => {
    clients.value = clients.value.filter((client) => client.id !== clientId);
    syncSelection();
  });
}

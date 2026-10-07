import { batch, computed, signal } from "@preact/signals";

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
import { clients, locationOf, syncSelection } from "../../live_store";
import { type Choice, placementModel, placesOnTap } from "./placement_model";

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

/** Which sensor the owner is placing (see `Choice`). */
const choice = signal<Choice>(undefined);
/** A location change is on its way to the server. */
export const placing = signal(false);

export const placement = computed(() =>
  placementModel(clients.value, locationOf, choice.value),
);

export function select(clientId: string | null): void {
  choice.value = clientId;
}

async function setLocation(
  clientId: string,
  locationCode: string,
): Promise<boolean> {
  try {
    await setClientLocation(clientId, locationCode);
  } catch (error) {
    showError(errorMessage(error, t("actions.set_location_failed")));
    return false;
  }
  clients.value = clients.value.map((client) =>
    client.id === clientId
      ? { ...client, location_code: locationCode }
      : client,
  );
  return true;
}

/**
 * A tap on a spot (see `placesOnTap`). Placing moves on to the next sensor to
 * place; a sensor already there becomes unplaced, as a location holds one
 * sensor. Tapping the selected sensor's own spot closes the selection.
 */
export async function tapSpot(code: string): Promise<void> {
  const model = placement.value;
  const { selected } = model;
  const occupant = model.byCode.get(code);
  if (placing.value) {
    return;
  }
  if (!selected || !placesOnTap(model, occupant)) {
    choice.value =
      occupant && occupant.id !== selected?.id ? occupant.id : null;
    return;
  }
  placing.value = true;
  try {
    if (occupant && !(await setLocation(occupant.id, ""))) {
      return;
    }
    if (await setLocation(selected.id, code)) {
      choice.value = undefined;
    }
  } finally {
    placing.value = false;
  }
}

/** Clears the sensor's location; it stays selected so it can go elsewhere. */
export async function unplace(clientId: string): Promise<void> {
  if (placing.value) {
    return;
  }
  placing.value = true;
  try {
    if (await setLocation(clientId, "")) {
      choice.value = clientId;
    }
  } finally {
    placing.value = false;
  }
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

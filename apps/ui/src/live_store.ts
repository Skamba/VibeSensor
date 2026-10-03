import { computed, signal } from "@preact/signals";

import { getClientLocations } from "./api/clients";
import { defaultLocationCodes } from "./constants";
import { t, translationsOf } from "./i18n";
import { locationCodeForClient, locationOptions } from "./sensor_locations";
import type {
  AdaptedClient,
  RotationalSpeeds,
  SpectrumFrameData,
} from "./transport/live_models";

/** Live data shared by the dashboard, sensors, and spectrum pages. */

export const clients = signal<AdaptedClient[]>([]);
export const selectedClientId = signal<string | null>(null);
export const speedMps = signal<number | null>(null);
export const rotationalSpeeds = signal<RotationalSpeeds | null>(null);
export const spectra = signal<SpectrumFrameData>({ clients: {} });

/** Location codes a sensor can be assigned to. */
export const locationCodes = signal<string[]>(defaultLocationCodes.slice());
export const locationChoices = computed(() =>
  locationOptions(locationCodes.value, t),
);

/** Bumped when a recording starts, stops, or finishes, so History reloads. */
export const runsChanged = signal(0);

/** The sensor's location code, inferred from its name when unassigned. */
export function locationOf(client: AdaptedClient): string {
  return locationCodeForClient(
    client,
    locationCodes.value,
    locationChoices.value,
    (code) => translationsOf(`location.${code}`),
  );
}

export async function loadLocationCodes(): Promise<void> {
  const { locations } = await getClientLocations();
  const codes = Array.isArray(locations)
    ? locations
        .map((row) => row.code)
        .filter((code): code is string => typeof code === "string")
    : [];
  locationCodes.value = codes.length ? codes : defaultLocationCodes.slice();
}

/** Keeps the selected sensor valid: first connected one, else the first. */
export function syncSelection(): void {
  const list = clients.value;
  const current = selectedClientId.value;
  if (current && list.some((client) => client.id === current)) {
    return;
  }
  const fallback = list.find((client) => client.connected) ?? list[0];
  selectedClientId.value = fallback?.id ?? null;
}
